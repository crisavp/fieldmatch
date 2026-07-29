"""Sentinel-1 wind-quality flag: the IPF 003 -> 004 convention flip.

The value meaning 'good' changed from 0 to 4 at IPF 004.02, so a hardcoded
`== 0` keeps the no_data pixels on modern files. These tests pin both
conventions AND pin that legacy files are unaffected by the fix.
"""
import numpy as np
import pandas as pd
import pytest
import xarray as xr

from matchup.preprocess import load_and_stack_sentinel
from matchup.readers import s1_good_quality_values

IPF003 = {"flag_values": np.array([0, 1, 2, 3], dtype="int8"),
          "flag_meanings": "good medium low poor"}
IPF004 = {"flag_values": np.array([0, 1, 2, 3, 4], dtype="int8"),
          "flag_meanings": "no_data bad suspect acceptable good"}


def _flag(attrs):
    return xr.DataArray(np.zeros(3), attrs=attrs)


def test_legacy_convention_keeps_only_zero():
    assert s1_good_quality_values(_flag(IPF003)) == [0]


def test_modern_convention_keeps_four_and_three():
    assert sorted(s1_good_quality_values(_flag(IPF004))) == [3, 4]


def test_missing_metadata_falls_back_to_legacy():
    with pytest.warns(UserWarning, match="flag_meanings"):
        assert s1_good_quality_values(_flag({})) == [0]


def _collocated(tmp_path, quality, attrs):
    """Minimal stand-in for a collocated S1 file (time, NUMROWS, NUMCELLS)."""
    q = np.asarray(quality, dtype="f8").reshape(1, 1, -1)
    ds = xr.Dataset(
        {"wind_speed": (("time", "NUMROWS", "NUMCELLS"), np.full(q.shape, 10.0)),
         "wind_quality": (("time", "NUMROWS", "NUMCELLS"), q)},
        coords={"time": pd.to_datetime(["2026-01-20T05:05"]),
                "lat": (("time", "NUMROWS", "NUMCELLS"), np.full(q.shape, 36.0)),
                "lon": (("time", "NUMROWS", "NUMCELLS"), np.full(q.shape, 14.0))},
    )
    ds["wind_quality"].attrs.update(attrs)
    p = tmp_path / "colloc.nc"
    ds.to_netcdf(p)
    return p


def test_legacy_file_unchanged_by_the_fix(tmp_path):
    """IPF 003: only quality 0 survives -- identical to the old hardcoded rule."""
    p = _collocated(tmp_path, [0, 0, 1, 2, 3], IPF003)
    out = load_and_stack_sentinel(p)
    assert out.sizes["obs"] == 2


def test_modern_file_keeps_the_good_pixels(tmp_path):
    """IPF 004: the old rule kept the single no_data pixel and dropped the
    three usable ones; now it is the other way round."""
    p = _collocated(tmp_path, [0, 4, 4, 3, 1], IPF004)
    out = load_and_stack_sentinel(p)
    assert out.sizes["obs"] == 3                      # two 'good' + one 'acceptable'
    assert set(np.unique(out["wind_quality"].values)) == {3.0, 4.0}


# ── coastal / open-sea masking (TODO item 4) ────────────────────────────────

def test_open_sea_mask_rejects_land_and_coastal_strip():
    """dist_coast is negative over land, so one threshold covers both."""
    from matchup.readers import _open_sea_mask
    src = xr.Dataset({
        "dist_coast_01": ("t", np.array([-5000.0, 1000.0, 29000.0, 45000.0])),
        "surf_type_01": ("t", np.array([3.0, 0.0, 0.0, 0.0])),
    })
    src["surf_type_01"].attrs.update(
        flag_values=np.array([0, 1, 2, 3]),
        flag_meanings="ocean_or_semi_enclosed_sea enclosed_sea_or_lake "
                      "continental_ice land")
    mask, desc = _open_sea_mask(src, "dist_coast_01", "surf_type_01", 30.0, True)
    assert list(mask) == [False, False, False, True]
    assert "30 km" in desc and "surf_type_01" in desc


def test_open_sea_mask_absent_variables_is_reported_not_silent():
    from matchup.readers import _open_sea_mask
    mask, desc = _open_sea_mask(xr.Dataset(), "dist_coast_01", "surf_type_01",
                                30.0, True)
    assert mask is None
    assert "none" in desc


# ── provenance (TODO item 7) ────────────────────────────────────────────────

def test_counts_are_summed_across_files_not_inherited():
    """xr.concat keeps only the first file's attrs -- counts must be summed."""
    from matchup.campaign import combine_provenance
    a = xr.Dataset(attrs={"n_rejected_coastal": 10, "n_read": 100,
                          "land_mask": "dist >= 30 km"})
    b = xr.Dataset(attrs={"n_rejected_coastal": 5, "n_read": 50,
                          "land_mask": "dist >= 30 km"})
    p = combine_provenance([a, b])
    assert p["n_rejected_coastal"] == 15
    assert p["n_read"] == 150
    assert p["land_mask"] == "dist >= 30 km"


def test_conflicting_provenance_is_surfaced_not_hidden():
    """A delivery mixing two processor versions must not look uniform."""
    from matchup.campaign import combine_provenance
    a = xr.Dataset(attrs={"wind_speed_filter": "owiWindQuality in [0]"})
    b = xr.Dataset(attrs={"wind_speed_filter": "owiWindQuality in [3, 4]"})
    p = combine_provenance([a, b])
    assert p["wind_speed_filter"].startswith("MIXED:")
    assert "[0]" in p["wind_speed_filter"] and "[3, 4]" in p["wind_speed_filter"]


def test_missing_quality_flag_is_recorded_as_unfiltered():
    from matchup.readers import _qc_by_flag
    src = xr.Dataset({"present_qual": ("t", np.array([0.0, 1.0]))})
    vals = {"a": np.array([1.0, 2.0]), "b": np.array([3.0, 4.0])}
    vals, prov, n = _qc_by_flag(src, vals, (("a", "present_qual"),
                                            ("b", "absent_qual")))
    assert prov["a_filter"] == "present_qual == 0"
    assert prov["b_filter"].startswith("none (absent_qual not present")
    assert n == 1 and np.isnan(vals["a"][1])
