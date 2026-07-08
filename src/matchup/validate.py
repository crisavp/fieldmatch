"""Fail-loud validation for read/write boundaries (mirrors wfetch/validate.py).

A wrong grid, an all-NaN collocated column, or a non-monotonic time axis must
raise here rather than propagate silently into the merged product that wfetch
consumes.
"""
import numpy as np
import pandas as pd


def require_vars(ds, names, label):
    """Assert each name is a variable or coordinate of ds."""
    present = set(ds.data_vars) | set(ds.coords)
    missing = [n for n in names if n not in present]
    if missing:
        raise ValueError(
            f"dataset '{label}' missing required variables {missing}; "
            f"present: {sorted(ds.data_vars)}"
        )


def require_coords_sane(ds, label, lat="lat", lon="lon", time="time"):
    """Latitude in [-90,90], longitude finite & plausible, time monotonic."""
    la = np.asarray(ds[lat].values, dtype="float64")
    lo = np.asarray(ds[lon].values, dtype="float64")
    if not np.all(np.isfinite(la)) or la.min() < -90.0 or la.max() > 90.0:
        raise ValueError(
            f"dataset '{label}': latitude out of range "
            f"[{np.nanmin(la)}, {np.nanmax(la)}] (expected within [-90, 90])"
        )
    if not np.all(np.isfinite(lo)) or lo.min() < -360.0 or lo.max() > 360.0:
        raise ValueError(
            f"dataset '{label}': longitude out of range [{np.nanmin(lo)}, {np.nanmax(lo)}]"
        )
    if time in ds.coords or time in ds.dims:
        t = pd.to_datetime(np.asarray(ds[time].values))
        if not t.is_monotonic_increasing:
            raise ValueError(f"dataset '{label}': time axis is not monotonic increasing")


def require_var_not_all_nan(ds, var, label):
    """Assert a collocated variable is not entirely NaN (catches domain mismatch)."""
    if var not in ds:
        return
    vals = np.asarray(ds[var].values)
    if vals.size and np.isnan(vals).all():
        raise ValueError(
            f"dataset '{label}': collocated '{var}' is 100% NaN "
            "(region/domain mismatch -- obs do not fall on the model grid?)."
        )
