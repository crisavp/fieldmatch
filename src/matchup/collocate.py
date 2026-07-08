"""Stage 1: interpolate model winds onto each satellite file.

Ported from wave_models2/python/wind/collocation_satmod.py::process_file. One
output file per raw satellite file, written to
collocated/{prefix}_{model_label}/<name>_colloc.nc. Idempotent: skips files
whose _colloc.nc already exists (the fast-skip for routine re-runs).
"""
import os
import warnings

import numpy as np
import xarray as xr
from joblib import Parallel, delayed
from scipy.interpolate import RegularGridInterpolator
from tqdm import tqdm

from . import config as _cfg
from .registry import (
    kind_of, load_model_ds, check_region_grid_overlap, require_regions_match,
)

TVAR, LONVAR, LATVAR = "time", "lon", "lat"


def process_file(file, outdir, *, preprocess, obs_kwargs, region_bbox,
                 ds_mod, uvar, vvar):
    """Collocate one raw satellite file; return the output path or None."""
    outpath = os.path.join(outdir, os.path.basename(file).replace(".nc", "_colloc.nc"))
    if os.path.exists(outpath):
        return None

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ds_sat = preprocess(
            file,
            user_region=region_bbox,
            user_coords={"time": "time", "lon": "lon", "lat": "lat"},
            **obs_kwargs,
        )
    if ds_sat is None:
        return None

    time_sat = np.unique(ds_sat[TVAR].values)
    rows = []
    for itime in time_sat:
        try:
            mod_slice = ds_mod.sel({TVAR: itime}, method="nearest", tolerance="30min")
        except KeyError:
            print(f"No model data found for time {itime}, skipping this timestamp.")
            continue
        sat_slice = ds_sat.where(ds_sat[TVAR] == itime, drop=True)
        lon_mod, lat_mod = mod_slice[LONVAR].values, mod_slice[LATVAR].values
        lon_sat = sat_slice[LONVAR].isel({TVAR: 0}).values
        lat_sat = sat_slice[LATVAR].isel({TVAR: 0}).values
        u_interp = RegularGridInterpolator(
            (lat_mod, lon_mod), mod_slice[uvar].values,
            method="linear", bounds_error=False, fill_value=np.nan)
        v_interp = RegularGridInterpolator(
            (lat_mod, lon_mod), mod_slice[vvar].values,
            method="linear", bounds_error=False, fill_value=np.nan)
        pts = np.column_stack([lat_sat.ravel(), lon_sat.ravel()])  # order = (lat, lon)
        u_mod_on_sat = u_interp(pts).reshape(lat_sat.shape).astype(np.float32)
        v_mod_on_sat = v_interp(pts).reshape(lat_sat.shape).astype(np.float32)
        target_dims = sat_slice[LONVAR].dims
        sat_slice[uvar] = (target_dims, u_mod_on_sat[None, ...])
        sat_slice[vvar] = (target_dims, v_mod_on_sat[None, ...])
        rows.append(sat_slice)

    if not rows:
        return None
    ds_out = xr.concat(rows, dim="time")
    encoding = {v: {"zlib": True, "complevel": 4, "_FillValue": np.nan, "dtype": "float32"}
                for v in ds_out.data_vars}
    ds_out.to_netcdf(outpath, encoding=encoding)
    return outpath


def run_collocation(cfg, sat_name, model_name, n_jobs=-1):
    """Collocate every raw file of a sat source against a model. Returns outdir."""
    sat = _cfg.get_sat(cfg, sat_name)
    model = _cfg.get_model(cfg, model_name)
    require_regions_match(sat, model)

    region_bbox = _cfg.get_region(cfg, model["region"])
    outdir = str(_cfg.collocated_dir(cfg, sat, model))
    os.makedirs(outdir, exist_ok=True)

    ds_mod = load_model_ds(cfg, model)
    check_region_grid_overlap(ds_mod, region_bbox)

    preprocess = kind_of(sat)["preprocess"]
    obs_kwargs = sat.get("obs_kwargs") or {}
    files = _cfg.raw_sat_files(cfg, sat)

    Parallel(n_jobs=n_jobs)(
        delayed(process_file)(
            f, outdir,
            preprocess=preprocess, obs_kwargs=obs_kwargs, region_bbox=region_bbox,
            ds_mod=ds_mod, uvar=model["uvar"], vvar=model["vvar"],
        )
        for f in tqdm(files, desc=f"collocate {sat_name} x {model_name}")
    )
    return outdir
