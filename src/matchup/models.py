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
import warnings

import numpy as np
import xarray as xr


def _open_one(path, engine):
    """Open one file -> list of Datasets (a GRIB mixing editions/levels yields
    several incompatible message groups; cfgrib.open_datasets splits them)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
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


def _restore_provenance(ds, prov):
    """Rebuild init / lead_hours over the merged time axis.

    Each source part covers only its own valid times; the merged axis is their
    union. Fill from whichever part supplied each time (parts that overlap come
    from the same forecast, so they agree).
    """
    if not prov:
        return ds
    t = ds["time"].values
    init = np.full(t.shape, np.datetime64("NaT", "ns"))
    lead = np.full(t.shape, np.nan)
    order = {v: i for i, v in enumerate(t)}
    for times, p_init, p_lead in prov:
        for k, tt in enumerate(times):
            i = order.get(tt)
            if i is not None and np.isnat(init[i]):
                init[i] = p_init[k]
                lead[i] = p_lead[k]
    return ds.assign_coords(init=("time", init), lead_hours=("time", lead))


def _group_by_vars(parts):
    """Group datasets by their variable set (one-param-per-file dumps give one
    group per parameter), preserving order."""
    groups, order = {}, []
    for p in parts:
        key = tuple(sorted(p.data_vars))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(p)
    return [groups[k] for k in order]


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
    if hi < lo:
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
        j = int(np.argmin(np.abs(steps - lo)))
        if abs(steps[j] - lo) > tol_hours:
            raise ValueError(
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


def _dedupe_by_shortest_lead(ds, warn=True):
    """One field per valid time, preferring the shortest lead.

    A window wider than the init spacing lets several forecasts cover the same
    valid time (e.g. +12..+35 h from 12-hourly inits). Keeping all of them
    would double-count observations, so keep the freshest forecast and say so:
    the sample is then no longer a clean tiling.
    """
    t = ds["time"].values
    if len(np.unique(t)) == len(t):
        return ds
    lead = ds["lead_hours"].values
    order = np.lexsort((lead, t))              # by time, then by lead
    keep, seen = [], set()
    for i in order:
        if t[i] in seen:
            continue
        seen.add(t[i])
        keep.append(i)
    if warn:
        warnings.warn(
            f"lead window overlaps: {len(t) - len(keep)} of {len(t)} fields "
            "share a valid time with a shorter-lead forecast and were dropped. "
            "The window is wider than the init spacing, so this sample is not "
            "a clean tiling of the timeline.")
    return ds.isel(time=np.sort(np.array(keep)))


def _standardize(ds, init=None, lead=None, lead_tol=6.0):
    """Any cfgrib layout -> (time, lat, lon) with `init` / `lead_hours` coords.

    `time` is always the VALID time. The init time and lead are kept as
    coordinates so the collocated output can record which forecast produced
    each value -- discarding them made lead-time analysis impossible.
    """
    multi_init = "time" in ds.dims and "step" in ds.dims

    if lead is not None and "step" in ds.coords:
        ds_sel = _select_lead(ds, parse_lead(lead), lead_tol)
    elif multi_init:
        if init is None:
            avail = np.datetime_as_string(ds["time"].values[:4], "h").tolist()
            raise ValueError(
                "dataset holds several forecast inits AND lead steps. Pass "
                f"init=<one of {avail}...> to follow one forecast, or "
                "lead=<hours or 'lo-hi'> to slice a lead window across all "
                "inits (e.g. lead='12-35' = forecast day 1 from daily runs).")
        ds_sel = ds.sel(time=np.datetime64(init))
        steps = _hours(ds_sel["step"].values)
        ds_sel = (ds_sel.assign_coords(step=ds_sel["valid_time"].values)
                        .drop_vars(["time", "valid_time"], errors="ignore")
                        .rename({"step": "time"}))
        ds_sel = _tag(ds_sel, np.datetime64(init), steps)
    elif "step" in ds.dims:                       # single init, many leads
        init_t = np.datetime64(ds["time"].values)
        steps = _hours(ds["step"].values)
        ds_sel = (ds.assign_coords(step=ds["valid_time"].values)
                    .drop_vars(["time", "valid_time"], errors="ignore")
                    .rename({"step": "time"}))
        ds_sel = _tag(ds_sel, init_t, steps)
    else:                                         # analysis / reanalysis
        ds_sel = _tag(ds, ds["time"].values, 0.0)

    drop = [c for c in ("step", "valid_time", "number", "surface",
                        "heightAboveGround", "meanSea") if c in ds_sel.coords]
    ds_sel = ds_sel.drop_vars(drop)
    ds_sel = ds_sel.rename({"latitude": "lat", "longitude": "lon"})
    ds_sel = ds_sel.assign_coords(lon=(ds_sel["lon"] + 180.0) % 360.0 - 180.0)
    return ds_sel.sortby("lat").sortby("lon")


def open_model(paths, engine="cfgrib", init=None, lead=None, lead_tol=6.0,
               rename=None):
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
    if isinstance(paths, (str,)):
        paths = [paths]
    files = sorted(set(sum((_glob.glob(str(p)) for p in paths), [])))
    if not files:
        raise FileNotFoundError(f"no model files match: {paths}")
    parts = [_standardize(part, init=init, lead=lead, lead_tol=lead_tol)
             for f in files for part in _open_one(f, engine)]
    if lead is not None:
        # Lead window: each file/init contributes its own valid times; group by
        # variable set first so one-param-per-file dumps still merge cleanly,
        # then resolve inits that cover the same valid time. This must run even
        # for a SINGLE part -- one multi-init file (AIFS) produces overlapping
        # valid times on its own, and duplicate/unsorted times silently break
        # the searchsorted time matching in collocate_track.
        parts = [_dedupe_by_shortest_lead(
                     (xr.concat(g, dim="time") if len(g) > 1 else g[0]).sortby("time"),
                     warn=(i == 0))          # one warning, not one per variable
                 for i, g in enumerate(_group_by_vars(parts))]

    # An outer-join merge cannot keep per-part non-dim coords (parts have
    # different time axes), so carry init/lead aside and rebuild after.
    prov = [(p["time"].values, p["init"].values, p["lead_hours"].values)
            for p in parts if "init" in p.coords]
    parts = [p.drop_vars(["init", "lead_hours"], errors="ignore") for p in parts]

    ds = parts[0] if len(parts) == 1 else xr.merge(parts, join="outer", compat="override")
    ds = _restore_provenance(ds, prov)
    # GRIB shortName -> the obs-side canonical name (readers.py), then user map.
    ds = ds.rename({k: v for k, v in {"swh": "hs"}.items() if k in ds})
    if rename:
        ds = ds.rename({k: v for k, v in rename.items() if k in ds})
    if "u10" in ds and "v10" in ds:
        u, v = ds["u10"], ds["v10"]
        ds["wind_speed"] = np.hypot(u, v)
        ds["wind_dir"] = (270.0 - np.degrees(np.arctan2(v, u))) % 360.0  # met 'from'
        # xarray propagates u10's attributes through the arithmetic, so the
        # derived fields would otherwise describe themselves as the U
        # component. Say what they actually are.
        ds["wind_speed"].attrs = {"units": "m s**-1",
                                  "long_name": "10 metre wind speed (from u10, v10)"}
        ds["wind_dir"].attrs = {"units": "degrees",
                                "long_name": "10 metre wind direction, "
                                             "meteorological 'from' (from u10, v10)"}
    return ds.sortby("time")
