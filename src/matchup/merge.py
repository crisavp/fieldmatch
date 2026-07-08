"""Stage 2: incremental merge of collocated files into one wfetch-ready product.

Strategy (yearly parts + concat):
  1. Group the per-file *_colloc.nc by year.
  2. Stack each year into collocated/_parts/{prefix}_{label}/{YYYY}.nc; rebuild a
     year ONLY if its source set changed (count / newest mtime vs a {YYYY}.json
     manifest). Unchanged years are skipped -- the fast path for routine appends.
  3. Concat all year parts into the single canonical
     collocated/{prefix}_{label.lower()}_merged_{Ystart}_{Yend}.nc, sorted by
     time, then validate it against the consumer contract.
  4. Prune any other {stem}_merged*.nc so the wfetch glob resolves to one file.
"""
import glob
import json
import os

import xarray as xr

from . import config as _cfg
from . import validate
from .registry import kind_of, year_from_filename

REQUIRED = ["time", "lat", "lon", "wind_speed", "wind_dir"]


def _group_by_year(files):
    groups = {}
    for f in files:
        groups.setdefault(year_from_filename(os.path.basename(f)), []).append(f)
    return {y: sorted(fs) for y, fs in groups.items()}


def _state(files):
    """Cheap fingerprint of a year's source set: file count + newest mtime."""
    return {"count": len(files),
            "newest_mtime": max(os.path.getmtime(f) for f in files)}


def _build_year_part(files, loader):
    """Stack one year's collocated files into a flat time-indexed dataset."""
    dsets = [loader(f) for f in files]
    dsets = [d for d in dsets if d is not None and d.sizes.get("obs", 0) > 0]
    if not dsets:
        return None
    merged = xr.concat(dsets, dim="obs")
    clean = merged.reset_index("obs").drop_vars(["NUMROWS", "NUMCELLS"], errors="ignore")
    # index the obs dim by its time coord, then relabel the dim to 'time' (doing it
    # in this order avoids xarray's "rename does not create an index" warning).
    clean = clean.set_index(obs="time").rename({"obs": "time"})
    return clean


def _encoding(ds):
    return {v: {"zlib": True, "complevel": 4} for v in ds.data_vars}


def run_merge(cfg, sat_name, model_name, prune=True, dry_run=False):
    """Build/refresh the merged product. Returns a summary dict."""
    sat = _cfg.get_sat(cfg, sat_name)
    model = _cfg.get_model(cfg, model_name)
    loader = kind_of(sat)["loader"]

    colloc = str(_cfg.collocated_dir(cfg, sat, model))
    files = sorted(glob.glob(os.path.join(colloc, "*_colloc.nc")))
    if not files:
        raise FileNotFoundError(f"no collocated files in {colloc}; run collocate first")

    pdir = str(_cfg.parts_dir(cfg, sat, model))
    os.makedirs(pdir, exist_ok=True)
    groups = _group_by_year(files)

    rebuilt, skipped = [], []
    for year in sorted(groups):
        part = os.path.join(pdir, f"{year}.nc")
        man = os.path.join(pdir, f"{year}.json")
        state = _state(groups[year])
        if os.path.exists(part) and os.path.exists(man):
            with open(man) as fh:
                old = json.load(fh)
            if old.get("count") == state["count"] and old.get("newest_mtime") == state["newest_mtime"]:
                skipped.append(year)
                continue
        if dry_run:
            rebuilt.append(year)
            continue
        ds = _build_year_part(groups[year], loader)
        if ds is None:
            continue
        tmp = part + ".tmp"
        ds.to_netcdf(tmp, encoding=_encoding(ds))
        os.replace(tmp, part)
        with open(man, "w") as fh:
            json.dump(state, fh)
        rebuilt.append(year)

    if dry_run:
        return {"rebuilt": rebuilt, "skipped": skipped, "merged": None}

    # Concat all year parts -> single canonical file.
    part_files = sorted(glob.glob(os.path.join(pdir, "*.nc")))
    years = [int(os.path.basename(p)[:4]) for p in part_files]
    ds_all = xr.concat([xr.open_dataset(p) for p in part_files], dim="time").sortby("time")

    label = f"{sat_name} x {model_name}"
    validate.require_vars(ds_all, REQUIRED, label)
    validate.require_coords_sane(ds_all, label)
    validate.require_var_not_all_nan(ds_all, model["uvar"], label)

    out = str(_cfg.merged_path(cfg, sat, model, (min(years), max(years))))
    tmp = out + ".tmp"
    ds_all.to_netcdf(tmp, encoding=_encoding(ds_all))
    ds_all.close()
    os.replace(tmp, out)

    pruned = []
    if prune:
        stem = _cfg.merged_stem(sat, model)
        for f in glob.glob(os.path.join(str(_cfg.collocated_root(cfg)), f"{stem}*.nc")):
            if os.path.abspath(f) != os.path.abspath(out):
                os.remove(f)
                pruned.append(os.path.basename(f))

    return {"rebuilt": rebuilt, "skipped": skipped, "merged": out, "pruned": pruned}
