"""Code-side dispatch + guards -- the part of the old registry.py that cannot
live in YAML (callables and logic).

- KINDS: maps a satellite `kind` string to its preprocess/loader pair.
- load_model_ds: open + standardize a model dataset from its spec.
- check_region_grid_overlap / require_regions_match: the safety guards that
  prevented an all-NaN product from a region/domain mismatch.
- year_from_filename: parse the year for grouping collocated files in the merge.
"""
import re

import xarray as xr

from .config import get_region, model_files
from .preprocess import (
    ASCAT_preprocess, SENTINEL1_preprocess,
    load_and_stack_ascat, load_and_stack_sentinel,
)

# kind -> (per-file cleaner, merge-stage loader)
KINDS = {
    "ascat": {"preprocess": ASCAT_preprocess, "loader": load_and_stack_ascat},
    "sentinel1": {"preprocess": SENTINEL1_preprocess, "loader": load_and_stack_sentinel},
}

_YEAR_RE = re.compile(r"(20\d{2})(0[1-9]|1[0-2])([0-2]\d|3[01])")


def kind_of(sat):
    kind = sat["kind"]
    if kind not in KINDS:
        raise ValueError(f"unknown sat kind {kind!r}; known: {sorted(KINDS)}")
    return KINDS[kind]


def year_from_filename(name):
    """Parse a 4-digit year from the first YYYYMMDD date in a filename.

    Works for ASCAT (`ascat_20160101_...`) and Sentinel-1
    (`s1a-...-20220703t151926-...`) collocated filenames alike.
    """
    m = _YEAR_RE.search(name)
    if not m:
        raise ValueError(f"cannot parse a year from filename: {name}")
    return int(m.group(1))


def require_regions_match(sat, model):
    """The sat source and model must target the same basin (else obs get cropped
    to one region and interpolated onto a grid covering another)."""
    if sat["region"] != model["region"]:
        raise ValueError(
            f"Region mismatch: sat targets '{sat['region']}' but model "
            f"'{model['label']}' targets '{model['region']}'. Pick a matching pair."
        )


def load_model_ds(cfg, model):
    """Open + standardize a model dataset described by a model spec."""
    files = model_files(cfg, model)
    ds = xr.open_mfdataset(
        files, combine="by_coords", parallel=True,
        chunks={model["chunks_dim"]: 24},
    )
    rename = {k: v for k, v in (model.get("rename") or {}).items() if v and k != v}
    if rename:
        ds = ds.rename(rename)
    return ds


def check_region_grid_overlap(ds_mod, region_bbox, lonvar="lon", latvar="lat"):
    """Raise if the model grid does not actually cover the region crop box.

    The obs are cropped to region_bbox; if that box falls outside the model grid
    the interpolation returns all-NaN. Catch it up front. Touching-only counts as
    no overlap.
    """
    lon = ds_mod[lonvar].values
    lat = ds_mod[latvar].values
    grid = {
        "lonmin": float(lon.min()), "lonmax": float(lon.max()),
        "latmin": float(lat.min()), "latmax": float(lat.max()),
    }
    lon_overlap = min(grid["lonmax"], region_bbox["lonmax"]) - max(grid["lonmin"], region_bbox["lonmin"])
    lat_overlap = min(grid["latmax"], region_bbox["latmax"]) - max(grid["latmin"], region_bbox["latmin"])
    if lon_overlap <= 0 or lat_overlap <= 0:
        raise ValueError(
            "Model grid does not overlap the region crop box -- collocation would be "
            "all-NaN.\n"
            f"  region box : lon [{region_bbox['lonmin']}, {region_bbox['lonmax']}], "
            f"lat [{region_bbox['latmin']}, {region_bbox['latmax']}]\n"
            f"  model grid : lon [{grid['lonmin']:.2f}, {grid['lonmax']:.2f}], "
            f"lat [{grid['latmin']:.2f}, {grid['latmax']:.2f}]"
        )
