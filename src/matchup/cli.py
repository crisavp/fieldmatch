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
from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint

from . import config as _cfg

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


@app.command()
def collocate(data: str = _DATA, model: str = _MODEL,
              jobs: int = typer.Option(-1, help="joblib n_jobs (-1 = all cores)."),
              config: Optional[Path] = _CONFIG):
    """Stage 1: interpolate model winds onto each satellite file (skips existing)."""
    from .collocate import run_collocation
    cfg = _cfg.load_config(config)
    outdir = run_collocation(cfg, data, model, n_jobs=jobs)
    rprint(f"[green]collocated ->[/green] {outdir}")


@app.command()
def merge(data: str = _DATA, model: str = _MODEL,
          prune: bool = typer.Option(True, help="Remove stale merged*.nc (keep one file)."),
          dry_run: bool = typer.Option(False, "--dry-run", help="Report rebuild/skip years; write nothing."),
          config: Optional[Path] = _CONFIG):
    """Stage 2: incremental yearly-parts merge -> single canonical merged file."""
    from .merge import run_merge
    cfg = _cfg.load_config(config)
    res = run_merge(cfg, data, model, prune=prune, dry_run=dry_run)
    rprint(f"rebuilt years: {res['rebuilt'] or '(none)'}")
    rprint(f"skipped years: {res['skipped'] or '(none)'}")
    if res.get("merged"):
        rprint(f"[green]merged ->[/green] {res['merged']}")
        if res.get("pruned"):
            rprint(f"pruned stale: {res['pruned']}")


@app.command()
def run(data: str = _DATA, model: str = _MODEL,
        jobs: int = typer.Option(-1, help="joblib n_jobs for collocation."),
        prune: bool = typer.Option(True, help="Remove stale merged*.nc after merge."),
        config: Optional[Path] = _CONFIG):
    """Routine flow: collocate then merge."""
    from .collocate import run_collocation
    from .merge import run_merge
    cfg = _cfg.load_config(config)
    run_collocation(cfg, data, model, n_jobs=jobs)
    res = run_merge(cfg, data, model, prune=prune)
    rprint(f"[green]merged ->[/green] {res['merged']}")


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
