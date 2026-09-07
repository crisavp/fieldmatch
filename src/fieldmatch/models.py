"""Model-field loading: GRIB (via cfgrib) or netCDF -> one standardized cube.

Standard form handed to collocation:
    dims:   time, lat, lon      (lat ascending, lon in [-180, 180])
    vars:   GRIB shortNames as-is (swh, mwd, mwp, u10, v10, ...) plus derived
            wind_speed / wind_dir when u10 & v10 are both present.

Layout quirks handled here:
- analysis/hindcast/ERA5: one variable per file, (time, lat, lon) -> merged.
- forecast:  (step, lat, lon) with a scalar init time -> valid_time becomes
  the time axis (one dataset per init; pass `init` to pick among files).
- AIFS:      (time, step, lat, lon), many inits -> `init` selects one.

Variables sampled at different cadences (hourly waves vs 6-hourly winds) are
outer-joined; missing steps are NaN and the collocation's per-variable time
tolerance deals with them.
"""
import glob as _glob
import os
import warnings

import numpy as np
import xarray as xr


def _open_one(path, engine):
    """Open one file -> list of Datasets (a GRIB mixing editions/levels yields
    several incompatible message groups; cfgrib.open_datasets splits them)."""
    if engine != "cfgrib":
        return [xr.open_dataset(path, engine=engine, decode_timedelta=True)]
    try:
        return [xr.open_dataset(path, engine="cfgrib", decode_timedelta=True,
                                backend_kwargs={"indexpath": ""})]
    except Exception:
        import cfgrib
        return cfgrib.open_datasets(path, backend_kwargs={"indexpath": ""})


def _hours(td):
    """timedelta64 array -> float hours."""
    return np.asarray(td) / np.timedelta64(1, "h")


def _combine_parts(parts, overlap):
    """Combine time partitions with no implicit regridding or conflict override."""
    reference = parts[0]
    for p in parts[1:]:
        for axis in ("lat", "lon"):
            if not np.array_equal(reference[axis].values, p[axis].values):
                raise ValueError(f"incompatible model {axis} grids; regrid explicitly")
    # Split by variable so parameter-per-file and multi-parameter files behave alike.
    groups = {}
    for part in parts:
        for name in part.data_vars:
            groups.setdefault(name, []).append(part[[name]])
    combined = []
    for name, group in groups.items():
        from .quantities import unit_name
        for other in group[1:]:
            for key in ("units", "quantity", "direction_convention"):
                if unit_name(group[0][name].attrs.get(key)) != unit_name(other[name].attrs.get(key)):
                    raise ValueError(f"conflicting {key} metadata for {name}")
        ds = xr.concat(group, dim="time", join="exact").sortby("time")
        if len(np.unique(ds.time.values)) == ds.sizes["time"]:
            combined.append(ds)
            continue
        pieces = []
        for time in np.unique(ds.time.values):
            ix = np.flatnonzero(ds.time.values == time)
            if len(ix) == 1:
                pieces.append(ds.isel(time=ix))
                continue
            sub = ds.isel(time=ix)
            distinct = len(np.unique(sub.init.values)) > 1
            if distinct:
                if overlap != "shortest_lead":
                    raise ValueError(f"conflicting forecast provenance for {name} at {time}; "
                                     "select an init/lead or set overlap: shortest_lead")
                sub = sub.isel(time=np.flatnonzero(sub.lead_hours.values == sub.lead_hours.min().item()))
                warnings.warn(f"{name} at {time}: explicitly selected shortest lead")
            # Duplicate deliveries may fill missing cells, but disagreeing finite cells fail.
            try:
                pieces.append(xr.merge([sub.isel(time=[i]) for i in range(sub.sizes["time"])],
                                       compat="no_conflicts", join="exact"))
            except xr.MergeError as exc:
                raise ValueError(f"conflicting model values/metadata for {name} at {time}") from exc
        combined.append(xr.concat(pieces, dim="time", join="exact"))
    # Provenance is shared only after agreement is checked, including wind components.
    try:
        return xr.merge(combined, join="outer", compat="no_conflicts")
    except xr.MergeError as exc:
        raise ValueError("conflicting model provenance across variables at the same valid time") from exc


def _tag(ds, init, lead):
    """Attach per-time-step provenance: which forecast, at what lead."""
    n = ds.sizes["time"]
    return ds.assign_coords(
        init=("time", np.broadcast_to(np.asarray(init, dtype="datetime64[ns]"), (n,)).copy()),
        lead_hours=("time", np.broadcast_to(np.asarray(lead, dtype="f8"), (n,)).copy()),
    )


def parse_lead(spec):
    """'24' | 24 | '12-35' | (12, 35) -> (lo, hi) in hours.

    A lead WINDOW is the general primitive; a single lead is the degenerate
    window (L, L). The operational construct is a window: 'forecast day 1' is
    +12..+35 h from daily 00 UTC runs, which tiles the timeline exactly -- one
    init covers each valid time, no gaps, no double counting.
    """
    if spec is None:
        return None
    if isinstance(spec, (list, tuple)):
        lo, hi = float(spec[0]), float(spec[-1])
    else:
        s = str(spec).strip()
        if "-" in s:                           # lead times are never negative
            a, b = s.split("-", 1)
            lo, hi = float(a), float(b)
        else:
            lo = hi = float(s)
    if not np.isfinite([lo, hi]).all() or lo < 0 or hi < lo:
        raise ValueError(f"lead window {lo}-{hi} h is empty (max < min)")
    return lo, hi


def _select_lead(ds, window, tol_hours):
    """Take every step whose lead falls inside `window`, re-indexed by valid
    time, for every init in `ds`. Stays lazy: one 2-D field per (init, step)
    kept, never the whole cube.

    A window narrower than the step spacing (i.e. a single requested lead)
    falls back to the nearest step within `tol_hours`, so `--lead 24` still
    works when 24 h is not an exact step.
    """
    lo, hi = window
    steps = _hours(ds["step"].values)
    idx = np.flatnonzero((steps >= lo) & (steps <= hi))
    if idx.size == 0:                          # scalar lead / gap: nearest step
        j = int(np.argmin(np.maximum(lo - steps, np.maximum(steps - hi, 0))))
        if max(lo - steps[j], steps[j] - hi, 0) > tol_hours:
            raise _EmptySelection(
                f"no forecast step in lead window {lo}-{hi} h "
                f"(nor within {tol_hours} h of it); "
                f"available leads: {np.unique(steps)[:12].tolist()}...")
        idx = np.array([j])

    if "time" in ds.dims:                      # many inits: one piece per step
        pieces = []
        for j in idx:
            p = ds.isel(step=int(j))
            valid = p["valid_time"].values
            p = (p.assign_coords(time=valid)
                  .drop_vars(["valid_time", "step"], errors="ignore"))
            pieces.append(_tag(p, valid - np.timedelta64(int(steps[j] * 3600), "s"),
                               float(steps[j])))
        return xr.concat(pieces, dim="time") if len(pieces) > 1 else pieces[0]

    # single init: the selected steps become the time axis directly
    init_t = np.datetime64(ds["time"].values)
    sel = ds.isel(step=idx)
    out = (sel.assign_coords(step=sel["valid_time"].values)
              .drop_vars(["time", "valid_time"], errors="ignore")
              .rename({"step": "time"}))
    return _tag(out, init_t, steps[idx])


def _coordinate_names(ds, coords=None):
    """Return a raw->canonical coordinate map for rectilinear model grids."""
    mapping = dict(coords or {})
    if any(v not in {"time", "lat", "lon"} for v in mapping.values()):
        raise ValueError("model coords values must be canonical names: time, lat, lon")
    aliases = {
        "time": ("time", "valid_time"),
        "lat": ("lat", "latitude"),
        "lon": ("lon", "longitude"),
    }
    chosen = set(mapping.values())
    for canonical, names in aliases.items():
        if canonical in chosen:
            continue
        found = next((name for name in names if name in ds.coords or name in ds.dims), None)
        if found is not None and found != canonical:
            mapping[found] = canonical
    return {raw: canonical for raw, canonical in mapping.items() if raw != canonical}


def _rectilinear(ds):
    for coord in ("time", "lat", "lon"):
        if coord not in ds.coords:
            raise ValueError(
                f"model has no {coord!r} coordinate after normalization; "
                "set dataset option coords: {raw_name: canonical_name}")
    if ds["lat"].ndim != 1 or ds["lon"].ndim != 1:
        raise ValueError("campaign interpolation currently requires 1-D rectilinear lat/lon")
    if ds["lat"].size < 2 or ds["lon"].size < 2:
        raise ValueError("campaign bilinear interpolation requires at least 2 lat and 2 lon points")
    for coord in ("time", "lat", "lon"):
        if ds[coord].ndim == 1 and ds[coord].dims != (coord,):
            old_dim = ds[coord].dims[0]
            ds = ds.swap_dims({old_dim: coord})
    for name in list(ds.data_vars):
        dims = ds[name].dims
        if not all(d in dims for d in ("time", "lat", "lon")):
            warnings.warn(f"skipping non-gridded model variable {name!r} on dimensions {dims}")
            ds = ds.drop_vars(name)
            continue
        extra = set(dims) - {"time", "lat", "lon"}
        if extra:
            raise ValueError(f"model variable {name!r} has unsupported dimensions {sorted(extra)}")
        ds[name] = ds[name].transpose("time", "lat", "lon")
    return ds


def _subset_axis(ds, name, lo, hi, pad=1):
    values = ds[name].values
    if values.size == 0 or hi < values[0] or lo > values[-1]:
        return ds.isel({name: slice(0, 0)})
    # Keep the grid points bracketing the box even when the box is narrower
    # than the grid spacing and contains no coordinate value itself.
    start = max(0, int(np.searchsorted(values, lo, side="left")) - pad)
    stop = min(values.size, int(np.searchsorted(values, hi, side="right")) + pad)
    return ds.isel({name: slice(start, stop)})


def _subset_campaign(ds, bbox=None, period=None, time_pad=None):
    """Subset lazily while retaining one spatial cell around the obs box."""
    if bbox is not None:
        ds = _subset_axis(ds, "lat", bbox["latmin"], bbox["latmax"])
        ds = _subset_axis(ds, "lon", bbox["lonmin"], bbox["lonmax"])
    if period is not None:
        pad = np.timedelta64(0, "s") if time_pad is None else time_pad
        ds = ds.sel(time=slice(period[0] - pad, period[1] + pad))
    return ds


class _EmptySelection(ValueError):
    """This file does not contain the explicitly requested initialization/lead."""


def _standardize(ds, init=None, lead=None, lead_tol=0.0, coords=None):
    """Normalize analysis, scalar-step and multi-step forecasts to valid time."""
    ds = ds.rename(_coordinate_names(ds, coords))
    if "step" in ds.coords:
        expected = ds["time"] + ds["step"]
        if "valid_time" in ds.coords and not bool((ds.valid_time == expected).all()):
            raise ValueError("valid_time disagrees with initialization + forecast step")
        ds = ds.assign_coords(valid_time=expected)
        if init is not None and lead is None:
            if not np.any(ds.time.values == np.datetime64(init)):
                raise _EmptySelection(f"initialization {init} is absent")
            if "time" in ds.dims:
                ds = ds.sel(time=np.datetime64(init))
        if "step" not in ds.dims:
            step = float(_hours(ds.step.values))
            if lead is not None:
                lo, hi = parse_lead(lead)
                if max(lo - step, step - hi, 0) > lead_tol:
                    raise _EmptySelection(f"scalar lead {step} h is outside requested window")
            inits = np.atleast_1d(ds.time.values)
            valid = np.atleast_1d(ds.valid_time.values)
            ds = ds.drop_vars(["step", "valid_time"])
            if "time" not in ds.dims:
                ds = ds.drop_vars("time").expand_dims(time=valid)
            else:
                ds = ds.assign_coords(time=valid)
            ds = _tag(ds, inits, step)
        elif lead is not None:
            ds = _select_lead(ds, parse_lead(lead), lead_tol)
        elif "time" in ds.dims:
            raise ValueError("dataset holds several forecast inits AND lead steps; "
                             "select init or lead explicitly")
        else:
            init_t = np.datetime64(ds.time.values)
            steps = _hours(ds.step.values)
            ds = (ds.assign_coords(step=ds.valid_time.values)
                    .drop_vars(["time", "valid_time"]).rename(step="time"))
            ds = _tag(ds, init_t, steps)
    else:
        if "time" not in ds.dims:
            ds = ds.expand_dims("time")
        if ("init" in ds.coords) != ("lead_hours" in ds.coords):
            raise ValueError("model provenance requires both init and lead_hours")
        if "init" not in ds.coords:
            ds = _tag(ds, ds.time.values, 0.)
        else:
            ds = _tag(ds, ds.init.values, ds.lead_hours.values)
        if init is not None and lead is None:
            ds = ds.isel(time=np.flatnonzero(ds.init.values == np.datetime64(init)))
        if lead is not None:
            lo, hi = parse_lead(lead)
            distance = np.maximum(lo-ds.lead_hours.values, np.maximum(ds.lead_hours.values-hi, 0))
            exact = distance == 0
            keep = exact if exact.any() else (distance == distance.min()) & (distance <= lead_tol)
            ds = ds.isel(time=np.flatnonzero(keep))
    if not ds.sizes.get("time", 0):
        raise _EmptySelection("no times in requested forecast view")
    leads = ds.lead_hours.values
    if not np.isfinite(leads).all() or (leads < 0).any() or np.isnat(ds.init.values).any():
        raise ValueError("invalid model initialization/lead provenance")
    expected = ds.init.values + np.rint(leads*3600*1e9).astype("timedelta64[ns]")
    if not np.array_equal(expected, ds.time.values.astype("datetime64[ns]")):
        raise ValueError("model provenance disagrees with valid time = init + lead")
    ds = ds.drop_vars([c for c in ("number", "surface", "heightAboveGround", "meanSea")
                       if c in ds.coords])
    ds = _rectilinear(ds)
    ds = ds.assign_coords(lon=(ds.lon + 180.) % 360. - 180.)
    for axis in ("lat", "lon"):
        if not np.isfinite(ds[axis]).all() or len(np.unique(ds[axis])) != ds.sizes[axis]:
            raise ValueError(f"model {axis} coordinate must be finite and unique")
    if np.isnat(ds.time.values).any():
        raise ValueError("model time contains NaT")
    return ds.sortby("lat").sortby("lon").sortby("time")


def open_model(paths, engine="cfgrib", init=None, lead=None, lead_tol=0.0,
               rename=None, coords=None, bbox=None, period=None, time_pad=None,
               overlap="error", variables=None):
    """Open + merge model files (glob patterns or explicit list) -> one cube.

    Files may each hold a different variable (ECMWF one-param-per-file dumps);
    they are outer-joined on time. Adds wind_speed / wind_dir (met 'from')
    whenever u10 & v10 are present.

    Forecast datasets carry two extra time coordinates, `init` and
    `lead_hours`, and are resolved one of two ways:

    - `init=<timestamp>`: follow ONE forecast across all its lead times.
    - `lead=<hours>`: constant-lead slice across ALL inits in the glob -- the
      standard forecast-verification view (`lead_tol` bounds the search when
      the exact step is absent).

    Mixing many inits without choosing is refused rather than silently
    averaging leads together.
    """
    if overlap not in {"error", "shortest_lead"}:
        raise ValueError("overlap must be error or shortest_lead")
    if not np.isfinite(lead_tol) or lead_tol < 0:
        raise ValueError("lead_tol must be finite and nonnegative")
    if isinstance(paths, (str, os.PathLike)):
        paths = [paths]
    files = sorted(set(sum((_glob.glob(str(p)) for p in paths), [])))
    if not files:
        raise FileNotFoundError(f"no model files match: {paths}")
    parts = []
    for f in files:
        for part in _open_one(f, engine):
            from .quantities import annotate
            for name in part.data_vars:
                part[name] = annotate(part[name], name)
            # Select fields before normalizing/combining unrelated grids and provenance.
            if variables is not None:
                selected = [v for v in part.data_vars
                            if (rename or {}).get({"swh": "hs"}.get(v, v),
                                                  {"swh": "hs"}.get(v, v)) in variables]
                if not selected:
                    continue
                part = part[selected]
            try:
                part = _subset_campaign(
                    _standardize(part, init=init, lead=lead, lead_tol=lead_tol, coords=coords),
                    bbox=bbox, period=period, time_pad=time_pad)
            except _EmptySelection:
                continue
            if all(part.sizes.get(d, 0) > 0 for d in ("time", "lat", "lon")):
                parts.append(part)
    if not parts:
        raise ValueError("model has no selected fields/times covering the campaign region and period")
    ds = _combine_parts(parts, overlap)
    # GRIB shortName -> the obs-side canonical name (readers.py), then user map.
    ds = ds.rename({k: v for k, v in {"swh": "hs"}.items() if k in ds})
    if rename:
        rename = {k: v for k, v in rename.items() if variables is None or v in variables}
        missing = sorted(set(rename) - set(ds.variables))
        if missing:
            raise ValueError(f"model rename source variable(s) not found: {missing}")
        ds = ds.rename(rename)
    from .quantities import annotate
    for name in ds.data_vars:
        ds[name] = annotate(ds[name], name)
    if "u10" in ds and "v10" in ds:
        u, v = ds["u10"], ds["v10"]
        ds["wind_speed"] = np.hypot(u, v)
        ds["wind_dir"] = ((270.0 - np.degrees(np.arctan2(v, u))) % 360.0).where(ds.wind_speed > 1e-10)  # met 'from'
        # xarray propagates u10's attributes through the arithmetic, so the
        # derived fields would otherwise describe themselves as the U
        # component. Say what they actually are.
        ds["wind_speed"].attrs = {"units": "m s**-1",
                                  "long_name": "10 metre wind speed (from u10, v10)"}
        ds["wind_dir"].attrs = {"units": "degrees",
                                "long_name": "10 metre wind direction, "
                                             "meteorological 'from' (from u10, v10)"}
    return ds.sortby("time")
