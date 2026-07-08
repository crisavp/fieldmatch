"""Unit tests for matchup (no large data needed)."""
import numpy as np
import pandas as pd
import xarray as xr

from matchup import config as cfg
from matchup import ledger as led
from matchup.merge import run_merge
from matchup.registry import year_from_filename
from matchup.subset import subset


def test_year_from_filename_ascat_and_sentinel():
    assert year_from_filename("ascat_20160101_181800_metopb_17064_ovw.l2_colloc.nc") == 2016
    assert year_from_filename("s1a-iw-ocn-vv-20220703t151926-20220703t151955-001_colloc.nc") == 2022


def test_config_loads_and_names_are_consistent():
    c = cfg.load_config()
    sat = cfg.get_sat(c, "ASCAT_med")
    model = cfg.get_model(c, "IFS_HRES_neutral_med")
    assert cfg.collocated_dir(c, sat, model).name == "ASCAT_IFS_HRES_neutral_med"
    assert cfg.merged_path(c, sat, model, (2016, 2024)).name == \
        "ASCAT_ifs_hres_neutral_med_merged_2016_2024.nc"


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
    assert set(np.round(out["lon"].values).astype(int)) <= {10, 5, 8}
    assert out.sizes["time"] >= 1
    assert float(out["lat"].min()) >= 36 and float(out["lat"].max()) <= 44


# ── merge lifecycle: ledger, append, resume-after-delete ───────────────────
def _write_colloc(path, date):
    """Write a synthetic ASCAT-shaped collocated file (dims time, NUMCELLS)."""
    t = pd.to_datetime([date + pd.Timedelta(minutes=5 * i) for i in range(3)])
    shape = (3, 4)
    ds = xr.Dataset(
        {
            "wind_speed": (("time", "NUMCELLS"), np.full(shape, 7.0)),
            "wind_dir": (("time", "NUMCELLS"), np.full(shape, 90.0)),
            "wvc_quality_flag": (("time", "NUMCELLS"), np.zeros(shape, dtype="int32")),
            "u10n": (("time", "NUMCELLS"), np.full(shape, 1.0)),
            "v10n": (("time", "NUMCELLS"), np.full(shape, 2.0)),
        },
        coords={
            "time": t,
            "lat": (("time", "NUMCELLS"), np.full(shape, 35.0)),
            "lon": (("time", "NUMCELLS"), np.full(shape, 15.0)),
        },
    )
    ds.to_netcdf(path)


def _toy_cfg(tmp_path):
    return {
        "roots": {"data_root": str(tmp_path), "collocated_subdir": "collocated"},
        "regions": {"x": {"lonmin": 0, "lonmax": 40, "latmin": 30, "latmax": 45}},
        "models": {"M": {"label": "M", "region": "x", "uvar": "u10n", "vvar": "v10n",
                         "glob": "none", "rename": {}, "chunks_dim": "time"}},
        "sat_sources": {"S": {"kind": "ascat", "region": "x", "raw_glob": "none",
                              "outdir_prefix": "ASCAT", "merged_prefix": "ASCAT"}},
    }


def test_merge_ledger_append_and_resume_after_delete(tmp_path):
    c = _toy_cfg(tmp_path)
    sat, model = c["sat_sources"]["S"], c["models"]["M"]
    cdir = cfg.collocated_dir(c, sat, model)
    cdir.mkdir(parents=True)
    # two years of colloc scenes
    _write_colloc(cdir / "ascat_20160601_000000_metopa_colloc.nc", pd.Timestamp("2016-06-01"))
    _write_colloc(cdir / "ascat_20170601_000000_metopa_colloc.nc", pd.Timestamp("2017-06-01"))

    res = run_merge(c, "S", "M")
    assert [y for y, _ in res["folded"]] == [2016, 2017]
    merged = xr.open_dataset(res["merged"])
    assert merged.sizes["time"] == 24  # 2 files x 3 times x 4 cells
    led_now = led.load_ledger(c, sat, model)
    assert len(led_now["ingested"]) == 2

    # DELETE the per-file colloc, then re-merge: nothing to fold, no crash, and the
    # canonical merged file is still rebuilt intact from the durable parts.
    for f in cdir.glob("*_colloc.nc"):
        f.unlink()
    res2 = run_merge(c, "S", "M")
    assert res2["folded"] == []
    assert xr.open_dataset(res2["merged"]).sizes["time"] == 24

    # APPEND a new year with no old colloc present: only the new year folds.
    _write_colloc(cdir / "ascat_20180601_000000_metopa_colloc.nc", pd.Timestamp("2018-06-01"))
    res3 = run_merge(c, "S", "M", drop_colloc=True)
    assert [y for y, _ in res3["folded"]] == [2018]
    assert xr.open_dataset(res3["merged"]).sizes["time"] == 36
    # drop_colloc removed the folded file
    assert list(cdir.glob("*_colloc.nc")) == []
    assert res3["merged"].endswith("_2016_2018.nc")
