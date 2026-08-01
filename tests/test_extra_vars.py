"""`extra_vars` passthrough: reaching variables the readers do not standardise.

The readers keep a deliberately small standard map (S3 RED: 3 of 65
variables). `extra_vars` lets an advanced user carry any other variable
through verbatim -- but only where that is meaningful, and never in a way that
lets a raw variable acquire the semantics of a standard name.
"""
import numpy as np
import pandas as pd
import pytest
import xarray as xr

from matchup.readers import EXTRA_PREFIX, _collect_extras, _unqualified


def _src():
    """Two variables on the record axis, one on a different (20 Hz) axis."""
    return xr.Dataset({
        "dist_coast_01": ("time_01", np.array([1e3, 2e3, 3e3])),
        "rain_flag_01_ku": ("time_01", np.array([0.0, 1.0, 0.0])),
        "swh_ocean_20_ku": ("time_20_ku", np.arange(60.0)),
    })


def test_extra_vars_are_carried_verbatim_under_their_own_prefix():
    out, prov = _collect_extras(_src(), ["dist_coast_01"], "time_01", {}, {})
    assert list(out) == [f"{EXTRA_PREFIX}dist_coast_01"]
    assert np.allclose(out[f"{EXTRA_PREFIX}dist_coast_01"], [1e3, 2e3, 3e3])
    assert prov["extra_vars"] == "dist_coast_01"


def test_prefix_keeps_extras_out_of_the_standard_namespace():
    """A raw variable must never land on a standard name: `wind_dir` triggers
    circular interpolation and circular statistics, and a passthrough column
    must not be able to acquire that behaviour by being named so."""
    from matchup.collocate_track import DIRECTION_VARS
    src = xr.Dataset({"wind_dir": ("time_01", np.array([350.0, 10.0, 0.0]))})
    out, _ = _collect_extras(src, ["wind_dir"], "time_01", {}, {})
    (col,) = list(out)
    assert col == f"{EXTRA_PREFIX}wind_dir"
    assert col not in DIRECTION_VARS


def test_variable_on_another_axis_is_refused_with_the_axis_named():
    """A 20 Hz variable is a different axis, not a different preference."""
    with pytest.raises(ValueError, match=r"time_20_ku.*time_01"):
        _collect_extras(_src(), ["swh_ocean_20_ku"], "time_01", {}, {})


def test_missing_variable_warns_and_is_recorded():
    """Silently dropping a requested variable would recreate the very problem
    extra_vars exists to solve."""
    with pytest.warns(UserWarning, match="not present"):
        out, prov = _collect_extras(_src(), ["nope_01"], "time_01", {}, {})
    assert out == {}
    assert prov["extra_vars_missing"] == "nope_01"


def test_group_qualified_names_do_not_collide():
    """Sentinel-6 stores Ku and C with identical names; both must survive."""
    assert _unqualified(["ku:swh_ocean", "c:swh_ocean", "plain"], "ku") == ["swh_ocean"]
    assert _unqualified(["ku:swh_ocean", "c:swh_ocean", "plain"], "c") == ["swh_ocean"]
    assert _unqualified(["ku:swh_ocean", "plain"], None) == ["plain"]

    src = xr.Dataset({"swh_ocean": ("time", np.array([1.0, 2.0]))})
    out, prov = _collect_extras(src, ["swh_ocean"], "time", {}, {}, group_label="ku:")
    out, prov = _collect_extras(src, ["swh_ocean"], "time", out, prov, group_label="c:")
    assert sorted(out) == [f"{EXTRA_PREFIX}c_swh_ocean", f"{EXTRA_PREFIX}ku_swh_ocean"]
    assert prov["extra_vars"] == "c:swh_ocean, ku:swh_ocean"


def test_no_extra_vars_is_a_no_op():
    out, prov = _collect_extras(_src(), None, "time_01", {"hs": np.zeros(3)}, {})
    assert list(out) == ["hs"] and prov == {}


# ── enumerated overrides (retracker / band) ─────────────────────────────────

def test_choice_rejects_unknown_value_listing_the_alternatives():
    from matchup.readers import _choice
    with pytest.raises(ValueError, match=r"choose one of \['mle', 'nr'\]"):
        _choice("retracker", "bogus", {"mle": "", "nr": "_nr"})


def test_choice_returns_the_mapped_suffix():
    from matchup.readers import S3_RETRACKERS, _choice
    assert _choice("retracker", "sar", S3_RETRACKERS) == "_01_ku"
    assert _choice("retracker", "plrm", S3_RETRACKERS) == "_01_plrm_ku"
