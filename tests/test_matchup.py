"""Unit tests for matchup (no large data needed)."""
import numpy as np
import pandas as pd
import xarray as xr

from matchup import config as cfg
from matchup.registry import year_from_filename
from matchup.subset import subset


def test_year_from_filename_ascat_and_sentinel():
    assert year_from_filename("ascat_20160101_181800_metopb_17064_ovw.l2_colloc.nc") == 2016
    assert year_from_filename("s1a-iw-ocn-vv-20220703t151926-20220703t151955-001_colloc.nc") == 2022


def test_config_loads_and_names_are_consistent():
    c = cfg.load_config()
    sat = cfg.get_sat(c, "ASCAT_med")
    model = cfg.get_model(c, "IFS_HRES_neutral_med")
    # collocated dir matches the existing on-disk dir; merged matches wfetch glob.
    assert cfg.collocated_dir(c, sat, model).name == "ASCAT_IFS_HRES_neutral_med"
    assert cfg.merged_path(c, sat, model, (2016, 2024)).name == \
        "ASCAT_ifs_hres_neutral_med_merged_2016_2024.nc"
    assert cfg.years_tag((2016, 2016)) == "2016"


def _toy_merged():
    t = pd.date_range("2023-11-01", periods=6, freq="D")
    return xr.Dataset(
        {"wind_speed": ("time", np.arange(6.0))},
        coords={"time": t,
                "lon": ("time", [0, 10, 30, 5, 40, 8]),
                "lat": ("time", [0, 38, 20, 40, 10, 42])},
    )


def test_subset_bbox_and_time():
    ds = _toy_merged()
    out = subset(ds, bbox=(2, 20, 36, 44), time=("2023-11-01", "2023-11-10"))
    # keeps only points with lon in [2,20] and lat in [36,44]
    assert set(np.round(out["lon"].values).astype(int)) <= {10, 5, 8}
    assert out.sizes["time"] >= 1
    assert float(out["lat"].min()) >= 36 and float(out["lat"].max()) <= 44
