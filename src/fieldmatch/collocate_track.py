"""One physical quantity per pair table; nearest time, explicit spatial policy."""
import json
from pathlib import Path
from uuid import uuid4
import numpy as np
import xarray as xr
from .quantities import DIRECTION_VARS, definition, validate

DEFAULT_TOL = np.timedelta64(30, "m")


class NoMatchInTime(RuntimeError):
    """No usable observation is close enough to a model time."""


class NoUsableModelValues(RuntimeError):
    """No finite observation/model pair remains."""


def _nearest_step(obs_t, mod_t, tie="earlier"):
    if tie not in {"earlier", "later"}:
        raise ValueError("time_tie must be earlier or later")
    i = np.searchsorted(mod_t, obs_t)
    left, right = np.maximum(i-1, 0), np.minimum(i, len(mod_t)-1)
    dl, dr = abs(obs_t-mod_t[left]), abs(obs_t-mod_t[right])
    idx = np.where(dl <= dr if tie == "earlier" else dl < dr, left, right)
    return idx, abs(obs_t-mod_t[idx])


def _spatial(lat, lon, field, points, method):
    """No extrapolation. Missing values matter only at nonzero-weight corners."""
    y, x = points.T
    j = np.clip(np.searchsorted(lat, y)-1, 0, len(lat)-2)
    k = np.clip(np.searchsorted(lon, x)-1, 0, len(lon)-2)
    fy = (y-lat[j])/(lat[j+1]-lat[j]); fx = (x-lon[k])/(lon[k+1]-lon[k])
    if method == "nearest":
        out = field[j+(fy > .5), k+(fx > .5)].astype(float)
    else:
        out = np.zeros(len(points))
        for dj, dk, weight in ((0,0,(1-fy)*(1-fx)), (0,1,(1-fy)*fx),
                               (1,0,fy*(1-fx)), (1,1,fy*fx)):
            term = np.zeros(len(points))
            np.multiply(field[j+dj,k+dk], weight, out=term, where=weight != 0)
            out += term
    outside = (y<lat[0]) | (y>lat[-1]) | (x<lon[0]) | (x>lon[-1])
    return np.where(outside, np.nan, out)


def source_fields(variable, model_variable=None, available=()):
    """An explicit source wins. Atmospheric wind uses aligned u/v by default."""
    if model_variable is None and variable in {"wind_speed", "wind_dir"}:
        if {"u10", "v10"} <= set(available):
            return ["u10", "v10"]
    return [model_variable or variable]


def collocate_track(obs, model, variables=None, tol=None, *, variable=None,
                    obs_variable=None, model_variable=None, time_tie="earlier",
                    space_method="bilinear", direction_resultant_min=1e-10,
                    wind_direction_min_speed=1e-10):
    """Return one quantity and one unambiguous model time per accepted record.

    ``variables=[name]`` remains a single-variable API spelling. Multiple
    quantities must call this primitive separately (the campaign runner does
    that for a batch). No fallback to fields absent from the observations.
    """
    if variable is not None and variables is not None:
        raise ValueError("specify variable, not both variable and variables")
    if variables is not None:
        if isinstance(variables, str) or len(variables) != 1:
            raise ValueError("one variable per result; call separately for each quantity")
        variable = variables[0]
    if variable is None:
        available = set(model.data_vars)
        if {"u10", "v10"} <= available:
            available |= {"wind_speed", "wind_dir"}
        shared = [v for v in obs.data_vars if v in available and not v.startswith("x_")]
        if len(shared) != 1:
            raise ValueError("select one variable explicitly; no unique shared quantity")
        variable = shared[0]
    if space_method not in {"bilinear", "nearest"}:
        raise ValueError("space_method must be bilinear or nearest")
    for value in (direction_resultant_min, wind_direction_min_speed):
        if not np.isfinite(value) or value < 0:
            raise ValueError("direction thresholds must be finite and nonnegative")
    if direction_resultant_min > 1:
        raise ValueError("direction_resultant_min cannot exceed 1")
    tol = DEFAULT_TOL if tol is None else tol
    if np.isnat(tol) or tol < np.timedelta64(0, "s"):
        raise ValueError("time tolerance must be nonnegative")
    oname = obs_variable or variable
    if oname not in obs:
        raise ValueError(f"observation variable {oname!r} is absent")
    observed = validate(obs[oname], variable)
    sources = source_fields(variable, model_variable, model.data_vars)
    missing = set(sources)-set(model.data_vars)
    if missing:
        raise ValueError(f"model variable(s) absent: {sorted(missing)}; select source explicitly")
    vector = sources == ["u10", "v10"]
    fields = {s: validate(model[s], s if vector else variable) for s in sources}
    times = model.time.values.astype("datetime64[ns]")
    if not len(times) or np.isnat(times).any() or (np.diff(times) <= np.timedelta64(0, "ns")).any():
        raise ValueError("model time must be nonempty, finite, unique and increasing")
    for axis in ("lat", "lon"):
        a = model[axis].values
        if len(a)<2 or not np.isfinite(a).all() or (np.diff(a)<=0).any():
            raise ValueError(f"model {axis} must be finite, unique and increasing")
    for s in sources:
        if fields[s].dims != ("time", "lat", "lon"):
            raise ValueError(f"{s} must have dimensions time,lat,lon")
    finite = np.flatnonzero(np.logical_and.reduce([
        np.isfinite(f.values).any(axis=(1,2)) for f in fields.values()]))
    if not finite.size:
        raise NoUsableModelValues("requested model fields contain no finite values on any common step")
    tv = times[finite]; ot = obs.time.values.astype("datetime64[ns]")
    position = np.column_stack([obs.lat.values, obs.lon.values])
    valid_location = (~np.isnat(ot) & np.isfinite(position).all(axis=1)
                      & (abs(position[:,0]) <= 90) & (abs(position[:,1]) <= 180))
    observed_ok = valid_location & np.isfinite(observed.values)
    idx, off = _nearest_step(np.where(valid_location, ot, tv[0]), tv, time_tie)
    temporal = observed_ok & (off <= tol)
    if not temporal.any():
        if not observed_ok.any():
            raise NoUsableModelValues("no finite observations with valid time/position")
        outside = (ot[observed_ok]+tol < tv[0]) | (ot[observed_ok]-tol > tv[-1])
        reason = "observations outside model temporal coverage" if outside.all() else "model time gaps exceed tolerance"
        raise NoMatchInTime(f"{reason}: tolerance {tol / np.timedelta64(1,'m'):g} min; "
                            f"available {tv[0]} .. {tv[-1]}")
    out = np.full(len(ot), np.nan)
    circular = definition(variable) in DIRECTION_VARS
    for i in np.unique(idx[temporal]):
        sel = np.flatnonzero(temporal & (idx == i))
        def sample(a):
            return _spatial(model.lat.values, model.lon.values, a, position[sel], space_method)
        if vector:
            u, v = (sample(fields[s].isel(time=int(finite[i])).values) for s in sources)
            speed = np.hypot(u, v)
            values = speed if variable == "wind_speed" else np.where(
                speed > wind_direction_min_speed, (270.-np.degrees(np.arctan2(v,u))) % 360., np.nan)
        elif circular:
            angle = np.deg2rad(fields[sources[0]].isel(time=int(finite[i])).values)
            sn, cs = sample(np.sin(angle)), sample(np.cos(angle))
            values = np.where(np.hypot(sn,cs)>direction_resultant_min,
                              np.degrees(np.arctan2(sn,cs)) % 360., np.nan)
        else:
            values = sample(fields[sources[0]].isel(time=int(finite[i])).values)
        out[sel] = values
    usable = temporal & np.isfinite(out)
    if not usable.any():
        raise NoUsableModelValues("time matched but model values were missing, outside the grid, or direction undefined")
    keep = np.flatnonzero(usable); step = finite[idx[keep]]
    extras = [v for v in obs.data_vars if v.startswith("x_") or v in {"obs_id", "source_file", "record_index"}]
    result = obs[[oname, *extras]].isel(obs=keep).copy()
    result[variable] = observed.isel(obs=keep)
    if oname != variable:
        result = result.drop_vars(oname)
    result[f"model_{variable}"] = ("obs", out[keep])
    result[f"model_{variable}"].attrs = dict(observed.attrs)
    result["model_time"] = ("obs", times[step])
    result["dt"] = ("obs", (ot[keep]-times[step])/np.timedelta64(1,"s"))
    result.dt.attrs["long_name"] = "observation time minus model valid time, seconds"
    for name in ("init", "lead_hours"):
        if name in model.coords:
            result[name] = ("obs", model[name].values[step])
    result.attrs.update(
        quantity=definition(variable), variable=variable, obs_variable=oname,
        model_sources=", ".join(sources), time_method="nearest", time_tie=time_tie,
        time_tolerance_minutes=float(tol/np.timedelta64(1,"m")), space_method=space_method,
        missing_corners="reject_nonzero_weight", extrapolation="none",
        direction_resultant_min=float(direction_resultant_min),
        wind_direction_min_speed=float(wind_direction_min_speed),
        model_cadence_hours=json.dumps(np.unique(np.diff(tv)/np.timedelta64(1,"h")).tolist()),
        n_input=len(ot), n_accepted=len(keep),
        n_rejected_invalid_position_time=int((~valid_location).sum()),
        n_rejected_observation_value=int((valid_location & ~observed_ok).sum()),
        n_rejected_time=int((observed_ok & ~temporal).sum()),
        n_rejected_space_or_value=int((temporal & ~usable).sum()))
    return result


def to_frame(ds):
    """Flat pandas DataFrame (time, lat, lon, obs + model columns) for CSV."""
    df = ds.to_dataframe().reset_index(drop=True)
    front = [c for c in ("time", "lat", "lon") if c in df.columns]
    return df[front + [c for c in df.columns if c not in front]]


def write_pairs(ds, stem, formats=("csv",)):
    """Atomically write a collocated table in one or both supported formats.

    ``stem`` has no suffix. CSV is deliberately the library default; explicit
    ``NaN`` values make missing numeric data unambiguous to non-Python readers.
    """
    formats = tuple(dict.fromkeys(formats))
    unknown = set(formats) - {"csv", "netcdf"}
    if not formats or unknown:
        raise ValueError(f"formats must contain csv and/or netcdf, got {formats!r}")

    stem = Path(stem)
    stem.parent.mkdir(parents=True, exist_ok=True)
    token = uuid4().hex
    targets = {"csv": Path(f"{stem}.csv"),
               "netcdf": Path(f"{stem}.nc")}
    temps = {name: path.with_name(f".{path.name}.{token}.tmp")
             for name, path in targets.items() if name in formats}
    written = {}
    try:
        if "csv" in formats:
            to_frame(ds).to_csv(temps["csv"], index=False, float_format="%.17g",
                                na_rep="NaN")
        if "netcdf" in formats:
            enc = {v: {"zlib": True, "complevel": 4} for v in ds.data_vars if ds[v].dtype.kind not in "OUS"}
            ds.to_netcdf(temps["netcdf"], encoding=enc)
        for name in formats:
            temps[name].replace(targets[name])
            written[name] = targets[name]
    finally:
        for tmp in temps.values():
            if tmp.exists():
                tmp.unlink()
    return written
