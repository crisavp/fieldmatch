"""matchup -- satellite/model wind collocation.

Usage:
    matchup datasets                                  # list models + sat sources
    matchup regions
    matchup collocate --data ASCAT_med --model IFS_HRES_neutral_med
    matchup merge     --data ASCAT_med --model IFS_HRES_neutral_med
    matchup run       --data ASCAT_med --model IFS_HRES_neutral_med   # collocate + merge
    matchup subset merged.nc --lonmin 2 --lonmax 20 --latmin 36 --latmax 44 \
                   --t0 2023-11-01 --t1 2023-11-10 --out storm.nc
"""
import datetime as _dt
from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint

from . import config as _cfg


def _version():
    try:
        from importlib.metadata import version
        return version("matchup")
    except Exception:
        return "unknown"

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="Config-driven satellite/model wind collocation "
                       "(collocate -> merge -> subset).")

_CONFIG = typer.Option(None, "--config", help="Path to config.yaml (default: packaged).")
_DATA = typer.Option(..., "--data", help="Satellite source name (see `matchup datasets`).")
_MODEL = typer.Option(..., "--model", help="Model name (see `matchup datasets`).")


@app.command()
def datasets(config: Optional[Path] = _CONFIG):
    """List configured models and satellite sources."""
    cfg = _cfg.load_config(config)
    rprint(f"[bold]data_root[/bold]: {cfg['roots']['data_root']}")
    rprint("\n[bold]models[/bold] (region  uvar/vvar  glob):")
    for name, m in cfg["models"].items():
        rprint(f"  {name:32} {m['region']:9} {m['uvar']}/{m['vvar']:6} {m['glob']}")
    rprint("\n[bold]sat_sources[/bold] (kind  region  raw_glob):")
    for name, s in cfg["sat_sources"].items():
        rprint(f"  {name:20} {s['kind']:10} {s['region']:9} {s['raw_glob']}")


@app.command()
def regions(config: Optional[Path] = _CONFIG):
    """List configured region crop boxes."""
    cfg = _cfg.load_config(config)
    for name, b in cfg["regions"].items():
        rprint(f"  {name:10} lon [{b['lonmin']}, {b['lonmax']}]  lat [{b['latmin']}, {b['latmax']}]")


def _parse_years(spec):
    """'2026' | '2024,2026' | '2024-2026' -> sorted list of ints (or None)."""
    if not spec:
        return None
    out = set()
    for part in str(spec).split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            out.update(range(int(a), int(b) + 1))
        elif part:
            out.add(int(part))
    return sorted(out)


@app.command()
def collocate(data: str = _DATA, model: str = _MODEL,
              years: Optional[str] = typer.Option(
                  None, help="Restrict to years: '2026', '2024,2026', '2024-2026'."),
              jobs: int = typer.Option(-1, help="joblib n_jobs (-1 = all cores)."),
              config: Optional[Path] = _CONFIG):
    """Stage 1: interpolate model winds onto each satellite file (skips existing)."""
    from .collocate import run_collocation
    cfg = _cfg.load_config(config)
    outdir = run_collocation(cfg, data, model, n_jobs=jobs, years=_parse_years(years))
    rprint(f"[green]collocated ->[/green] {outdir}")


@app.command()
def merge(data: str = _DATA, model: str = _MODEL,
          prune: bool = typer.Option(True, help="Remove stale merged*.nc (keep one file)."),
          drop_colloc: bool = typer.Option(
              False, "--drop-colloc",
              help="Delete per-file *_colloc.nc after they are folded into parts (saves storage)."),
          dry_run: bool = typer.Option(False, "--dry-run", help="Report fold/skip years; write nothing."),
          config: Optional[Path] = _CONFIG):
    """Stage 2: fold collocated files into year parts -> single canonical merged file."""
    from .merge import run_merge
    cfg = _cfg.load_config(config)
    res = run_merge(cfg, data, model, prune=prune, drop_colloc=drop_colloc, dry_run=dry_run)
    rprint(f"folded (year, n): {res['folded'] or '(none)'}")
    rprint(f"skipped years:    {res['skipped'] or '(none)'}")
    if res.get("merged"):
        rprint(f"[green]merged ->[/green] {res['merged']}")
        if res.get("pruned"):
            rprint(f"pruned stale: {res['pruned']}")
        if res.get("dropped_colloc"):
            rprint(f"dropped {res['dropped_colloc']} per-file colloc")


@app.command()
def status(data: str = _DATA, model: str = _MODEL, config: Optional[Path] = _CONFIG):
    """Show ledger coverage (ingested obs-files per month) for a product."""
    from . import ledger as _led
    cfg = _cfg.load_config(config)
    sat = _cfg.get_sat(cfg, data)
    mdl = _cfg.get_model(cfg, model)
    led = _led.load_ledger(cfg, sat, mdl)
    counts = _led.month_counts(led)
    rprint(f"[bold]{data} x {model}[/bold]  "
           f"ingested={len(led['ingested'])}  empty={len(led['empty'])}")
    for ym, n in counts.items():
        rprint(f"  {ym}: {n}")


@app.command()
def run(data: str = _DATA, model: str = _MODEL,
        years: Optional[str] = typer.Option(None, help="Restrict collocation to years."),
        jobs: int = typer.Option(-1, help="joblib n_jobs for collocation."),
        prune: bool = typer.Option(True, help="Remove stale merged*.nc after merge."),
        drop_colloc: bool = typer.Option(
            False, "--drop-colloc", help="Delete per-file colloc after folding."),
        config: Optional[Path] = _CONFIG):
    """Routine flow: collocate then merge."""
    from .collocate import run_collocation
    from .merge import run_merge
    cfg = _cfg.load_config(config)
    run_collocation(cfg, data, model, n_jobs=jobs, years=_parse_years(years))
    res = run_merge(cfg, data, model, prune=prune, drop_colloc=drop_colloc)
    rprint(f"[green]merged ->[/green] {res['merged']}")


@app.command()
def doctor():
    """Verify the installation: dependencies, netCDF and GRIB engines, package."""
    from .doctor import run_doctor
    rprint("[bold]matchup doctor[/bold]")
    if not run_doctor():
        raise typer.Exit(1)
    rprint("[green]all checks passed[/green]")


# ── campaign workflow (scan / match / cstats) ──────────────────────────────
@app.command()
def scan(campaign: Path = typer.Argument(..., exists=True, dir_okay=False,
                                         help="Campaign YAML (see config/campaigns/).")):
    """Inventory a campaign: files found, readable, obs in box, time coverage."""
    from .campaign import load_campaign
    from .scan import format_report, scan_campaign
    camp = load_campaign(campaign)
    rprint(format_report(camp, scan_campaign(camp)))


def _load_pair(campaign, obs_name, model_name):
    from .campaign import MODEL_KINDS, load_campaign
    camp = load_campaign(campaign)
    od, md = camp.get(obs_name), camp.get(model_name)
    if od.role != "obs" or md.role != "model":
        raise typer.BadParameter(
            f"need <obs> <model>; got {obs_name}={od.role}, {model_name}={md.role}")
    return camp, od, md, MODEL_KINDS[md.kind]


@app.command()
def match(campaign: Path = typer.Argument(..., exists=True, dir_okay=False),
          obs: str = typer.Argument(..., help="Obs dataset name in the campaign."),
          model: str = typer.Argument(..., help="Model dataset name in the campaign."),
          tol_minutes: Optional[float] = typer.Option(
              None, help="Max |obs-model| time gap in minutes (default: 30, "
                         "independent of the model timestep -- observations "
                         "are instantaneous). Widen for coarse-output models."),
          lead: Optional[str] = typer.Option(
              None, help="Forecast lead window in hours across every init: "
                         "'24' (single lead) or '12-35' (e.g. forecast day 1 "
                         "from daily 00 UTC runs)."),
          lead_tol: float = typer.Option(
              6.0, help="Tolerance (h) when no step falls inside the window."),
          csv: bool = typer.Option(True, help="Also write a flat CSV.")):
    """Collocate one obs dataset with one model dataset -> flat .nc (+ .csv)."""
    import warnings

    import numpy as np
    import xarray as xr

    from .campaign import combine_provenance, crop_obs
    from .collocate_track import NoMatchInTime, collocate_track, write_pair
    from .models import open_model
    from .readers import read_obs

    camp, od, md, engine = _load_pair(campaign, obs, model)
    opts = dict(md.options)
    if lead is not None:
        opts.pop("init", None)          # --lead overrides a configured init
        opts.update(lead=lead, lead_tol=lead_tol)
    mod = open_model(md.paths, engine=engine, **opts)

    clouds = []
    for f in od.files():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ds = read_obs(od.kind, f, **od.options)
        if ds is None:
            continue
        ds = crop_obs(ds, camp.bbox, camp.period)
        if ds is not None:
            clouds.append(ds)
    if not clouds:
        rprint(f"[red]no {obs} observations inside the campaign box/period[/red]")
        raise typer.Exit(1)
    # concat keeps only the first file's attrs: rebuild the record over all files
    obs_prov = combine_provenance(clouds)
    cloud = xr.concat(clouds, dim="obs").sortby("time")
    cloud.attrs = obs_prov

    tol = np.timedelta64(int(tol_minutes * 60), "s") if tol_minutes else None
    try:
        pair = collocate_track(cloud, mod, tol=tol)
    except NoMatchInTime as e:
        rprint(f"[red]{e}[/red]")
        raise typer.Exit(1)
    if pair is None:
        rprint("[red]no usable model values for these observations[/red]")
        raise typer.Exit(1)

    # Full provenance travels with the data: obs side, model side, matching.
    pair.attrs.update(obs_prov)
    pair.attrs["obs_reader"] = pair.attrs.pop("reader", od.kind)
    pair.attrs.update(
        campaign=camp.name, obs_dataset=obs, model_dataset=model,
        obs_files=len(od.files()), model_files=len(md.files()),
        model_kind=md.kind,
        region=(f"lon [{camp.bbox['lonmin']}, {camp.bbox['lonmax']}] "
                f"lat [{camp.bbox['latmin']}, {camp.bbox['latmax']}]"),
        period=f"{camp.period[0]} .. {camp.period[1]}",
        created=_dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        matchup_version=_version(),
    )
    if lead is not None:
        pair.attrs["lead_window_hours"] = lead

    camp.outdir.mkdir(parents=True, exist_ok=True)
    suffix = ""
    if lead is not None:
        from .models import parse_lead
        lo, hi = parse_lead(lead)
        suffix = (f"_lead{int(lo):03d}h" if lo == hi
                  else f"_lead{int(lo):03d}-{int(hi):03d}h")
    stem = camp.outdir / f"{camp.name}_{obs}_x_{model}{suffix}"
    write_pair(pair, f"{stem}.nc", f"{stem}.csv" if csv else None)
    rprint(f"[green]{pair.sizes['obs']} collocated obs ->[/green] {stem}.nc"
           + (f" + {stem}.csv" if csv else ""))
    tolm = pair.attrs.get("time_tolerance_minutes", 30)
    nrej = pair.attrs.get("n_rejected_time", 0)
    if nrej:
        rprint(f"  [yellow]{nrej} obs rejected: no model step within "
               f"{tolm:.0f} min[/yellow] (widen with --tol-minutes)")
    # A variable can be empty while the row survives on another variable --
    # say so, or an all-NaN column looks like missing data rather than a
    # cadence mismatch.
    for item in pair.attrs.get("matched_per_variable", "").split("; "):
        if item.startswith(tuple(f"{v}: 0/" for v in pair.data_vars)):
            rprint(f"  [yellow]{item} -- no pairs at {tolm:.0f} min "
                   f"tolerance[/yellow]")
    if "lead_hours" in pair:
        lh = pair["lead_hours"].values
        spread = np.nanmax(lh) - np.nanmin(lh)
        msg = f"  lead times: {np.nanmin(lh):.0f}-{np.nanmax(lh):.0f} h"
        if spread > 1 and lead is None:
            # Leads vary because a single init was followed across its whole
            # run -- pooling those is not a forecast skill number.
            msg += ("  [yellow](one init, mixed leads -- use --lead for a "
                    "verification sample, or `cstats --by-lead`)[/yellow]")
        rprint(msg)


@app.command()
def cstats(campaign: Path = typer.Argument(..., exists=True, dir_okay=False),
           obs: str = typer.Argument(...),
           model: str = typer.Argument(...),
           by_lead: bool = typer.Option(
               False, "--by-lead",
               help="Group statistics by forecast lead time instead of pooling "
                    "them (forecast datasets only)."),
           lead_bin: float = typer.Option(24.0, help="--by-lead bin width in hours."),
           suffix: str = typer.Option("", help="Filename suffix, e.g. _lead024h."),
           plots: bool = typer.Option(True, help="Write scatter+map PNG per variable.")):
    """Stats table (bias/RMSE/SI/corr) for a collocated pair (after `match`)."""
    import numpy as np
    import xarray as xr

    from .campaign import load_campaign
    from .pairstats import format_stats, plot_pair, stats_table
    camp = load_campaign(campaign)
    stem = camp.outdir / f"{camp.name}_{obs}_x_{model}{suffix}"
    nc = Path(f"{stem}.nc")
    if not nc.exists():
        rprint(f"[red]{nc} not found -- run `matchup match` first[/red]")
        raise typer.Exit(1)
    ds = xr.open_dataset(nc)
    rprint(f"[bold]{camp.name}: {obs} x {model}[/bold]")

    if by_lead:
        if "lead_hours" not in ds:
            rprint("[red]no lead_hours column -- not a forecast collocation[/red]")
            raise typer.Exit(1)
        lh = ds["lead_hours"].values
        edges = np.arange(0, np.nanmax(lh) + lead_bin, lead_bin)
        for lo in edges:
            sel = np.flatnonzero((lh >= lo) & (lh < lo + lead_bin))
            if sel.size == 0:
                continue
            rprint(f"\n[bold]lead {lo:.0f}-{lo + lead_bin:.0f} h[/bold]  "
                   f"({sel.size} obs)")
            print(format_stats(stats_table(ds.isel(obs=sel))))
        return

    table = stats_table(ds)
    if "lead_hours" in ds:
        lh = ds["lead_hours"].values
        if np.nanmax(lh) - np.nanmin(lh) > 1:
            rprint(f"[yellow]warning: pooling lead times "
                   f"{np.nanmin(lh):.0f}-{np.nanmax(lh):.0f} h into one number; "
                   f"use --by-lead[/yellow]")
    print(format_stats(table))
    if plots:
        for v in table:
            png = f"{stem}_{v}.png"
            plot_pair(ds, v, png, title=f"{obs} x {model}")
            rprint(f"  plot -> {png}")


@app.command()
def subset(merged: Path = typer.Argument(..., exists=True, dir_okay=False),
           lonmin: Optional[float] = typer.Option(None),
           lonmax: Optional[float] = typer.Option(None),
           latmin: Optional[float] = typer.Option(None),
           latmax: Optional[float] = typer.Option(None),
           t0: Optional[str] = typer.Option(None, help="Start date, e.g. 2023-11-01."),
           t1: Optional[str] = typer.Option(None, help="End date, e.g. 2023-11-10."),
           out: Optional[Path] = typer.Option(None, help="Write result to this .nc.")):
    """Carve a subregion (bbox + time range) out of a merged product."""
    from .subset import subset as _subset
    bbox = None
    if None not in (lonmin, lonmax, latmin, latmax):
        bbox = (lonmin, lonmax, latmin, latmax)
    time = (t0, t1) if (t0 and t1) else None
    ds = _subset(merged, bbox=bbox, time=time)
    n = int(ds.sizes.get("time", 0))
    rprint(f"subset: {n} observations")
    if out:
        ds.to_netcdf(out)
        rprint(f"[green]wrote ->[/green] {out}")


if __name__ == "__main__":
    app()
