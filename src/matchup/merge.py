"""Stage 2: fold collocated files into a wfetch-ready merged product.

Durable artifacts are the per-year part files under
`_parts/{prefix}_{label}/{YYYY}.nc` plus a `ledger.json` recording which colloc
scenes are already folded in. The per-file `*_colloc.nc` are transient scratch:
once folded (and recorded), they can be dropped (`drop_colloc=True`).

Flow:
  1. Load the ledger. Group the per-file colloc present on disk by year.
  2. For each year, take only the colloc files NOT yet in the ledger and APPEND
     their obs to that year's part (read part + concat new + rewrite). Record them
     in the ledger. Years with no new scenes are untouched -- and need no colloc
     files on disk at all (fast-skip + resume-after-delete).
  3. Concat the year parts (each pre-sorted, year-ordered -> globally monotonic by
     construction) into the single canonical
     `{prefix}_{label.lower()}_merged_{Ystart}_{Yend}.nc`, streaming via dask so a
     100M-obs product never has to sit in memory at once. Prune stale merged files.
  4. Optionally delete the folded per-file colloc.
"""
import glob
import os

import xarray as xr

from . import config as _cfg
from . import ledger as _led
from . import validate
from .registry import kind_of, year_from_filename

REQUIRED = ["time", "lat", "lon", "wind_speed", "wind_dir"]


def _group_by_year(files):
    groups = {}
    for f in files:
        groups.setdefault(year_from_filename(os.path.basename(f)), []).append(f)
    return {y: sorted(fs) for y, fs in groups.items()}


def _stack_files(files, loader):
    """Stack a list of colloc files into one flat time-indexed dataset (or None)."""
    dsets = [loader(f) for f in files]
    dsets = [d for d in dsets if d is not None and d.sizes.get("obs", 0) > 0]
    if not dsets:
        return None
    merged = xr.concat(dsets, dim="obs")
    clean = merged.reset_index("obs").drop_vars(["NUMROWS", "NUMCELLS"], errors="ignore")
    return clean.set_index(obs="time").rename({"obs": "time"})


def _encoding(ds):
    return {v: {"zlib": True, "complevel": 4} for v in ds.data_vars}


def _fold_year(part_path, new_files, loader, label):
    """Append new colloc obs to a year part (build it if absent). Returns the count
    of obs written, or 0 if the new files yielded nothing."""
    new_ds = _stack_files(new_files, loader)
    if new_ds is None:
        return 0
    if os.path.exists(part_path):
        existing = xr.open_dataset(part_path)
        combined = xr.concat([existing, new_ds], dim="time")
    else:
        existing = None
        combined = new_ds
    combined = combined.sortby("time")

    validate.require_vars(combined, REQUIRED, label)
    validate.require_coords_sane(combined, label)

    tmp = part_path + ".tmp"
    combined.to_netcdf(tmp, encoding=_encoding(combined))
    n = int(combined.sizes["time"])
    combined.close()
    if existing is not None:
        existing.close()
    os.replace(tmp, part_path)
    return n


def _write_canonical(part_files, out, label):
    """Concat pre-sorted, year-ordered parts into one monotonic merged file,
    streaming via dask. Assumes parts do not overlap in time (true for year
    grouping) so no global sort is needed."""
    part_files = sorted(part_files, key=lambda p: int(os.path.basename(p)[:4]))
    # cheap boundary check: each part's max time <= next part's min time
    prev_max = None
    for p in part_files:
        with xr.open_dataset(p) as d:
            tmin = d["time"].values.min()
            tmax = d["time"].values.max()
        if prev_max is not None and tmin < prev_max:
            raise ValueError(
                f"{label}: parts overlap in time at {os.path.basename(p)} "
                f"(min {tmin} < previous max {prev_max}); canonical would be non-monotonic"
            )
        prev_max = tmax

    dss = [xr.open_dataset(p, chunks={"time": 2_000_000}) for p in part_files]
    ds_all = xr.concat(dss, dim="time")
    validate.require_vars(ds_all, REQUIRED, label)

    tmp = out + ".tmp"
    ds_all.to_netcdf(tmp, encoding=_encoding(ds_all))
    ds_all.close()
    for d in dss:
        d.close()
    os.replace(tmp, out)


def run_merge(cfg, sat_name, model_name, prune=True, drop_colloc=False, dry_run=False):
    """Fold collocated files into the merged product. Returns a summary dict."""
    sat = _cfg.get_sat(cfg, sat_name)
    model = _cfg.get_model(cfg, model_name)
    loader = kind_of(sat)["loader"]
    label = f"{sat_name} x {model_name}"

    colloc = str(_cfg.collocated_dir(cfg, sat, model))
    present = sorted(glob.glob(os.path.join(colloc, "*_colloc.nc")))

    pdir = str(_cfg.parts_dir(cfg, sat, model))
    os.makedirs(pdir, exist_ok=True)
    ledger = _led.load_ledger(cfg, sat, model)
    ingested = set(ledger["ingested"])

    groups = _group_by_year(present)
    folded, skipped, folded_files = [], [], []
    for year in sorted(groups):
        new = [f for f in groups[year] if os.path.basename(f) not in ingested]
        if not new:
            skipped.append(year)
            continue
        if dry_run:
            folded.append((year, len(new)))
            continue
        part = os.path.join(pdir, f"{year}.nc")
        n = _fold_year(part, new, loader, f"{label} {year}")
        if n:
            ingested.update(os.path.basename(f) for f in new)
            folded_files.extend(new)
            folded.append((year, len(new)))

    if dry_run:
        return {"folded": folded, "skipped": skipped, "merged": None}

    ledger["ingested"] = sorted(ingested)
    _led.save_ledger(cfg, sat, model, ledger)

    # Canonical merged file from all year parts (existing + just-updated).
    part_files = sorted(glob.glob(os.path.join(pdir, "*.nc")))
    if not part_files:
        raise FileNotFoundError(f"no year parts under {pdir}; nothing to merge")
    years = [int(os.path.basename(p)[:4]) for p in part_files]
    out = str(_cfg.merged_path(cfg, sat, model, (min(years), max(years))))
    _write_canonical(part_files, out, label)

    pruned = []
    if prune:
        stem = _cfg.merged_stem(sat, model)
        for f in glob.glob(os.path.join(str(_cfg.collocated_root(cfg)), f"{stem}*.nc")):
            if os.path.abspath(f) != os.path.abspath(out):
                os.remove(f)
                pruned.append(os.path.basename(f))

    dropped = 0
    if drop_colloc:
        # Only delete colloc files that are now recorded as ingested.
        for f in glob.glob(os.path.join(colloc, "*_colloc.nc")):
            if os.path.basename(f) in ingested:
                os.remove(f)
                dropped += 1

    return {"folded": folded, "skipped": skipped, "merged": out,
            "pruned": pruned, "dropped_colloc": dropped}
