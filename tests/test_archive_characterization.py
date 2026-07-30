"""Characterisation of the ARCHIVE pipeline (ASCAT x model -> wfetch product).

Written before consolidating preprocess.py onto readers.py (TODO item 10).
These tests do not assert that the behaviour is *right* -- they assert it is
UNCHANGED, so a refactor that alters the numbers fails loudly instead of
silently shifting a product that `wfetch` already consumes.

Everything is synthetic and hand-checkable: a 2x3 ASCAT granule and a 3x3
model grid whose interpolated values can be computed on paper. No external
data, no network, runs in milliseconds.

If a test here fails after a refactor, either the refactor is wrong, or the
behaviour changed deliberately -- in which case update the frozen value in the
same commit and say why.
"""
import numpy as np
import pandas as pd
import pytest
import xarray as xr

from matchup.collocate import process_file
from matchup.merge import REQUIRED, _stack_files
from matchup.preprocess import ASCAT_preprocess, load_and_stack_ascat

# Region used throughout: a box the synthetic granule sits inside.
BBOX = {"lonmin": -5.0, "lonmax": 5.0, "latmin": -5.0, "latmax": 5.0}


def _ascat_file(tmp_path, name="ascat_20260101_test.nc", lon360=True):
    """A 2-row x 3-cell ASCAT L2 granule in the raw on-disk layout.

    Longitudes are stored 0-360 (as the real product does) so the reader's
    conversion is exercised. Cell 2 of row 1 carries a bad quality flag.
    """
    lon = np.array([[0.0, 1.0, 2.0],
                    [0.0, 1.0, 359.0]])          # 359 -> -1 after conversion
    lat = np.array([[0.0, 0.0, 0.0],
                    [1.0, 1.0, 1.0]])
    t = pd.to_datetime(["2026-01-01T00:00", "2026-01-01T00:30"])
    time2d = np.repeat(t.values[:, None], 3, axis=1)
    ds = xr.Dataset(
        {
            "wind_speed": (("NUMROWS", "NUMCELLS"),
                           np.array([[10.0, 11.0, 12.0], [13.0, 14.0, 15.0]])),
            "wind_dir": (("NUMROWS", "NUMCELLS"),
                         np.array([[0.0, 90.0, 180.0], [270.0, 350.0, 10.0]])),
            "wvc_quality_flag": (("NUMROWS", "NUMCELLS"),
                                 np.array([[0.0, 0.0, 65536.0], [0.0, 0.0, 0.0]])),
            "lat": (("NUMROWS", "NUMCELLS"), lat),
            "lon": (("NUMROWS", "NUMCELLS"), lon if lon360 else (lon + 180) % 360 - 180),
            "time": (("NUMROWS", "NUMCELLS"), time2d),
        }
    )
    p = tmp_path / name
    ds.to_netcdf(p)
    return p


def _model(uval=3.0, vval=4.0):
    """Uniform model wind on a 3x3 grid: interpolation must return it exactly."""
    lat = np.array([-1.0, 0.0, 1.0])
    lon = np.array([-2.0, 0.0, 2.0])
    t = pd.to_datetime(["2026-01-01T00:00", "2026-01-01T00:30"])
    shape = (len(t), len(lat), len(lon))
    return xr.Dataset(
        {"u10": (("time", "lat", "lon"), np.full(shape, uval)),
         "v10": (("time", "lat", "lon"), np.full(shape, vval))},
        coords={"time": t, "lat": lat, "lon": lon},
    )


# ── stage 1: preprocess ─────────────────────────────────────────────────────
def test_preprocess_converts_longitude_and_swaps_time_onto_rows():
    """0-360 -> -180..180, and the per-row time becomes the row dimension."""
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        f = _ascat_file(Path(d))
        ds = ASCAT_preprocess(str(f), user_region=BBOX, obsLON360=True)
    assert "time" in ds.dims and ds.sizes["time"] == 2
    assert "NUMCELLS" in ds.dims and ds.sizes["NUMCELLS"] == 3
    assert float(ds["lon"].values.min()) == pytest.approx(-1.0)   # 359 -> -1
    assert float(ds["lon"].values.max()) == pytest.approx(2.0)


def test_preprocess_returns_none_when_nothing_is_in_region():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        f = _ascat_file(Path(d))
        out = ASCAT_preprocess(
            str(f), user_region={"lonmin": 100, "lonmax": 110,
                                 "latmin": 40, "latmax": 50}, obsLON360=True)
    assert out is None, "an empty region must skip the file, not raise"


# ── stage 2: collocation ────────────────────────────────────────────────────
def test_process_file_writes_colloc_and_interpolates_model_onto_obs(tmp_path):
    raw = _ascat_file(tmp_path)
    outdir = tmp_path / "out"
    outdir.mkdir()
    base, status = process_file(
        str(raw), str(outdir), preprocess=ASCAT_preprocess,
        obs_kwargs={"obsLON360": True}, region_bbox=BBOX,
        ds_mod=_model(), uvar="u10", vvar="v10")
    assert status == "ok"

    out = xr.open_dataset(outdir / base.replace(".nc", "_colloc.nc"))
    # Uniform field -> every obs gets exactly that value, at both timestamps.
    assert np.allclose(out["u10"].values, 3.0, equal_nan=False)
    assert np.allclose(out["v10"].values, 4.0, equal_nan=False)
    # The observation columns survive untouched alongside the model ones.
    for v in ("wind_speed", "wind_dir", "wvc_quality_flag"):
        assert v in out.data_vars
    out.close()


def test_process_file_is_idempotent(tmp_path):
    """A second run must skip, not recompute -- the archive relies on this."""
    raw = _ascat_file(tmp_path)
    outdir = tmp_path / "out"
    outdir.mkdir()
    kw = dict(preprocess=ASCAT_preprocess, obs_kwargs={"obsLON360": True},
              region_bbox=BBOX, ds_mod=_model(), uvar="u10", vvar="v10")
    assert process_file(str(raw), str(outdir), **kw)[1] == "ok"
    assert process_file(str(raw), str(outdir), **kw)[1] == "skip"


def test_process_file_reports_nomodel_without_writing(tmp_path):
    """Obs present but no model within tolerance: retryable, nothing written."""
    raw = _ascat_file(tmp_path)
    outdir = tmp_path / "out"
    outdir.mkdir()
    far = _model()
    far = far.assign_coords(time=pd.to_datetime(["2027-01-01T00:00",
                                                 "2027-01-01T00:30"]))
    base, status = process_file(
        str(raw), str(outdir), preprocess=ASCAT_preprocess,
        obs_kwargs={"obsLON360": True}, region_bbox=BBOX,
        ds_mod=far, uvar="u10", vvar="v10")
    assert status == "nomodel"
    assert not (outdir / base.replace(".nc", "_colloc.nc")).exists()


# ── stage 3: merge-time loader ──────────────────────────────────────────────
def test_load_and_stack_ascat_drops_flagged_and_rotates_direction(tmp_path):
    """wvc_quality_flag >= 65536 is dropped and wind_dir gains 180 deg.

    Both are long-standing archive conventions; the direction rotation lives
    in the LOADER, not the preprocessor, and is easy to double-apply during a
    refactor -- hence pinned here.
    """
    raw = _ascat_file(tmp_path)
    outdir = tmp_path / "out"
    outdir.mkdir()
    base, _ = process_file(
        str(raw), str(outdir), preprocess=ASCAT_preprocess,
        obs_kwargs={"obsLON360": True}, region_bbox=BBOX,
        ds_mod=_model(), uvar="u10", vvar="v10")
    ds = load_and_stack_ascat(str(outdir / base.replace(".nc", "_colloc.nc")))

    assert ds.sizes["obs"] == 5, "the one flagged cell must be dropped (6 - 1)"
    assert 65536.0 not in set(np.unique(ds["wvc_quality_flag"].values))
    # 0 -> 180, 90 -> 270, 270 -> 90, 350 -> 170, 10 -> 190 (flagged 180 gone)
    assert sorted(np.round(ds["wind_dir"].values).tolist()) == [90.0, 170.0, 180.0,
                                                               190.0, 270.0]


# ── stage 4: the wfetch consumer contract ───────────────────────────────────
def test_merged_product_contract(tmp_path):
    """The merged product must stay a flat, monotonic, time-indexed cloud with
    the variables `wfetch` requires. Breaking this breaks a downstream tool."""
    raw = _ascat_file(tmp_path)
    outdir = tmp_path / "out"
    outdir.mkdir()
    base, _ = process_file(
        str(raw), str(outdir), preprocess=ASCAT_preprocess,
        obs_kwargs={"obsLON360": True}, region_bbox=BBOX,
        ds_mod=_model(), uvar="u10", vvar="v10")
    stacked = _stack_files([str(outdir / base.replace(".nc", "_colloc.nc"))],
                           load_and_stack_ascat)

    assert list(stacked.dims) == ["time"], "must be flat, one obs per time entry"
    for name in REQUIRED:
        assert name in stacked.variables, f"wfetch requires {name!r}"
    t = stacked["time"].values
    assert (np.diff(t) >= np.timedelta64(0)).all(), "time must be non-decreasing"
