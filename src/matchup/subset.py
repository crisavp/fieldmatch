"""Subregion queries over a merged product.

A merged file is a flat time-indexed point cloud with lon(time)/lat(time), so a
subregion (e.g. a storm) is a cheap lon/lat box + time-slice filter -- no
re-collocation. Collocate once per basin; carve subregions here.
"""
from pathlib import Path

import xarray as xr


def subset(ds, bbox=None, time=None, lon="lon", lat="lat", tvar="time"):
    """Filter a merged dataset (or path) to a lon/lat box and/or time range.

    Args:
        ds: an xarray.Dataset or a path to a merged .nc file.
        bbox: (lonmin, lonmax, latmin, latmax), or None for no spatial filter.
        time: (t0, t1) date strings/timestamps, or None for no time filter.

    Returns:
        xarray.Dataset with only the observations inside the box/range.
    """
    if isinstance(ds, (str, Path)):
        ds = xr.open_dataset(ds)

    out = ds
    if time is not None:
        out = out.sortby(tvar).sel({tvar: slice(str(time[0]), str(time[1]))})
    if bbox is not None:
        lonmin, lonmax, latmin, latmax = bbox
        mask = ((out[lon] >= lonmin) & (out[lon] <= lonmax) &
                (out[lat] >= latmin) & (out[lat] <= latmax))
        out = out.where(mask, drop=True)
    return out
