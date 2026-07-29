"""Along-track collocation: an obs cloud (readers.py canonical form) against a
model cube (models.py standard form).

Strategy -- built for dense per-point timestamps (altimeter tracks; also fine
for single-time SAR scenes and buoys):
  1. assign every obs to its nearest model time step (vectorized searchsorted);
  2. drop obs farther than `tol` from any step (default: half the median model
     timestep, so hourly fields tolerate 30 min, 6-hourly fields 3 h);
  3. per occupied step, one bilinear RegularGridInterpolator per source field.
Variables are matched on their OWN axis of non-empty steps, because merged
model cubes mix cadences (hourly waves, 6-hourly winds).

Interpolating a direction is NOT interpolating a number: 350 deg and 10 deg
average to 180, not 0. Everything angular therefore goes through components:

  - wind_speed / wind_dir  -> interpolate u10, v10; derive at the obs point
    (vector interpolation, matching the legacy pipeline and Luigi's Fortran)
  - any other direction (mwd, wave_dir, dwi) -> interpolate sin/cos, recombine

Output: the obs cloud plus `model_<var>` columns -- flat, one row per obs.
"""
import numpy as np
import xarray as xr
from scipy.interpolate import RegularGridInterpolator

class NoMatchInTime(RuntimeError):
    """No observation fell within the time tolerance of any model step."""


#: Default max |obs time - model step|. Deliberately strict and INDEPENDENT of
#: the model timestep: altimeter, scatterometer and SAR retrievals are
#: instantaneous snapshots, so a 6-hourly model does not earn a 3 h tolerance
#: just by being coarse -- it earns fewer matches. Widen explicitly
#: (`--tol-minutes`) when the comparison genuinely tolerates it.
DEFAULT_TOL = np.timedelta64(30, "m")

#: Angular variables with no vector components in the cube: interpolate sin/cos.
DIRECTION_VARS = {"wind_dir", "mwd", "wave_dir", "mdir", "dwi", "dwd"}

#: Wind speed/direction are derived from these components when both exist.
WIND_COMPONENTS = ("u10", "v10")


def _nearest_step(obs_t, mod_t):
    """Index of nearest model time per obs (mod_t sorted), and the offset."""
    i = np.searchsorted(mod_t, obs_t)
    i = np.clip(i, 1, len(mod_t) - 1)
    left, right = mod_t[i - 1], mod_t[i]
    use_left = (obs_t - left) <= (right - obs_t)
    idx = np.where(use_left, i - 1, i)
    off = np.abs(obs_t - mod_t[idx])
    return idx, off


def _plan(variables, model):
    """Group requested outputs into interpolation jobs.

    Each job is (outputs, source_fields, combine) where `source_fields` are
    real (or synthetic sin/cos) fields to interpolate linearly and `combine`
    turns the interpolated values into the requested outputs. Angular
    quantities never reach the interpolator directly.
    """
    jobs, done = [], set()
    wind = [v for v in variables if v in ("wind_speed", "wind_dir")]
    if wind and all(c in model.data_vars for c in WIND_COMPONENTS):
        # Vector interpolation: interpolate u/v, derive speed/direction at the
        # observation point (matches the legacy pipeline and Luigi's Fortran).
        def _wind(vals, _out=tuple(wind)):
            u, v = vals["u10"], vals["v10"]
            res = {}
            if "wind_speed" in _out:
                res["wind_speed"] = np.hypot(u, v)
            if "wind_dir" in _out:
                res["wind_dir"] = (270.0 - np.degrees(np.arctan2(v, u))) % 360.0
            return res
        jobs.append((list(wind), {c: model[c] for c in WIND_COMPONENTS}, _wind))
        done.update(wind)

    for v in variables:
        if v in done:
            continue
        if v in DIRECTION_VARS:
            # No components available: interpolate sin/cos, recombine.
            rad = np.deg2rad(model[v])
            def _dir(vals, _v=v):
                return {_v: (np.degrees(np.arctan2(vals[f"{_v}__sin"],
                                                   vals[f"{_v}__cos"])) % 360.0)}
            jobs.append(([v], {f"{v}__sin": np.sin(rad), f"{v}__cos": np.cos(rad)}, _dir))
        else:
            jobs.append(([v], {v: model[v]}, lambda vals, _v=v: {_v: vals[_v]}))
    return jobs


def collocate_track(obs, model, variables=None, tol=None):
    """Collocate one obs cloud with a model cube.

    Args:
        obs: canonical obs Dataset (dim `obs`; time/lat/lon coords).
        model: standardized model Dataset (time, lat, lon).
        variables: model vars to sample (default: every var also present in
            the obs cloud, e.g. hs/wind_speed/wind_dir -- else all model vars).
        tol: max |obs time - model step| as np.timedelta64. Default
            DEFAULT_TOL (30 min) regardless of the model's own timestep --
            observations are instantaneous, so a coarse model gets fewer
            matches rather than a looser standard.

    Returns:
        obs Dataset with added `model_<var>` columns and a `dt` (seconds to
        the sampled model step), obs outside `tol` dropped. None if no match.
        `n_rejected_time` in `.attrs` records how many obs the tolerance cost.
    """
    mod_t = model["time"].values
    if variables is None:
        # Everything the obs measure that the model can supply -- including
        # wind_speed/wind_dir whenever u10/v10 are present, even if the cube
        # carries no pre-computed speed field.
        available = set(model.data_vars)
        if all(c in available for c in WIND_COMPONENTS):
            available |= {"wind_speed", "wind_dir"}
        variables = [v for v in obs.data_vars if v in available] or list(model.data_vars)

    lat_m, lon_m = model["lat"].values, model["lon"].values
    obs_t = obs["time"].values
    n = obs.sizes["obs"]
    pts = np.column_stack([obs["lat"].values, obs["lon"].values])

    # Outer-joined cubes mix cadences (hourly waves, 6-hourly winds): match
    # every job on its OWN axis of non-empty steps, with its own default
    # tolerance (half its own median timestep).
    out = {v: np.full(n, np.nan) for v in variables}
    dt = np.full(n, np.nan)
    step_of = np.zeros(n, dtype=int)   # model step index behind `dt` (provenance)
    matched = np.zeros(n, dtype=bool)
    per_var = {}                       # var -> (n matched, model step in hours)
    for outputs, sources, combine in _plan(variables, model):
        finite_mask = np.ones(len(mod_t), dtype=bool)
        for arr in sources.values():
            finite_mask &= np.isfinite(arr.values).any(axis=(1, 2))
        finite = np.flatnonzero(finite_mask)
        if finite.size == 0:
            continue
        tv = mod_t[finite]
        tol_v = DEFAULT_TOL if tol is None else tol
        idx, off = _nearest_step(obs_t, tv)
        ok = off <= tol_v
        matched |= ok
        step_h = (float(np.median(np.diff(tv)) / np.timedelta64(1, "h"))
                  if tv.size > 1 else float("nan"))
        for name in outputs:
            per_var[name] = (int(ok.sum()), step_h)
        for step_i in np.unique(idx[ok]):
            sel = ok & (idx == step_i)
            vals = {
                name: RegularGridInterpolator(
                    (lat_m, lon_m), arr.isel(time=int(finite[step_i])).values,
                    method="linear", bounds_error=False, fill_value=np.nan)(pts[sel])
                for name, arr in sources.items()
            }
            for name, res in combine(vals).items():
                out[name][sel] = res
            d = (obs_t[sel] - tv[step_i]) / np.timedelta64(1, "s")
            # Keep the closest match across jobs, and remember which model step
            # it came from so init/lead can be attached to the row.
            closer = ~np.isfinite(dt[sel]) | (np.abs(d) < np.abs(dt[sel]))
            idx_sel = np.flatnonzero(sel)
            dt[idx_sel[closer]] = d[closer]
            step_of[idx_sel[closer]] = int(finite[step_i])

    if not matched.any():
        tol_m = (DEFAULT_TOL if tol is None else tol) / np.timedelta64(1, "m")
        steps = ", ".join(f"{v} every {h:.0f}h" for v, (_, h) in per_var.items())
        raise NoMatchInTime(
            f"no observation is within {tol_m:.0f} min of a model step "
            f"({steps or 'no usable model steps'}). The model's output is too "
            f"coarse for this tolerance: widen it (--tol-minutes) and accept "
            f"that values are compared across that gap, or use observations "
            f"that sample the model's output times (e.g. buoys).")
    keep = np.flatnonzero(matched)
    n_rejected = int(n - keep.size)
    obs = obs.isel(obs=keep)
    obs.attrs["time_tolerance_minutes"] = float(
        (DEFAULT_TOL if tol is None else tol) / np.timedelta64(1, "m"))
    obs.attrs["n_rejected_time"] = n_rejected
    # Per-variable: how many obs the tolerance admitted, and that variable's
    # own model cadence. A variable at 0 is a cadence mismatch, not missing data.
    obs.attrs["matched_per_variable"] = "; ".join(
        f"{v}: {k}/{n} within tol (model every {h:.0f}h)"
        for v, (k, h) in sorted(per_var.items()))
    for v in variables:
        obs[f"model_{v}"] = ("obs", out[v][keep])
    obs["dt"] = ("obs", dt[keep])
    obs["dt"].attrs["long_name"] = "obs time minus nearest sampled model step [s]"

    # Forecast provenance: which init produced this value, at what lead. Without
    # these columns a forecast collocation cannot be split by lead afterwards.
    # NB: no `units: hours` attribute -- that makes xarray decode the column
    # back as a timedelta64 on read, which breaks arithmetic on it.
    for name, attrs in (("init", {"long_name": "forecast initialisation time"}),
                        ("lead_hours", {"long_name": "forecast lead time in hours"})):
        if name in model.coords:
            src = model[name].values
            obs[name] = ("obs", src[step_of[keep]])
            obs[name].attrs.update(attrs)
    return obs


def to_frame(ds):
    """Flat pandas DataFrame (time, lat, lon, obs + model columns) for CSV."""
    df = ds.to_dataframe().reset_index(drop=True)
    front = [c for c in ("time", "lat", "lon") if c in df.columns]
    return df[front + [c for c in df.columns if c not in front]]


def write_pair(ds, out_nc, out_csv=None):
    enc = {v: {"zlib": True, "complevel": 4} for v in ds.data_vars}
    ds.to_netcdf(out_nc, encoding=enc)
    if out_csv:
        to_frame(ds).to_csv(out_csv, index=False, float_format="%.4f")
