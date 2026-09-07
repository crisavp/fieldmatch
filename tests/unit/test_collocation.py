"""Vector / circular interpolation of directions (see TODO.md decision record)."""
import numpy as np
import pandas as pd
import pytest
import xarray as xr

from fieldmatch.collocate_track import collocate_track
from fieldmatch.pairstats import pair_stats


def _cube(**fields):
    """2x2 deg grid, single time step, one value per corner."""
    lat = np.array([0.0, 1.0])
    lon = np.array([0.0, 1.0])
    t = pd.to_datetime(["2026-01-01T00:00"])
    return xr.Dataset(
        {k: (("time", "lat", "lon"), np.asarray(v, dtype="f8")[None, ...])
         for k, v in fields.items()},
        coords={"time": t, "lat": lat, "lon": lon},
    )


def _obs(**vars_):
    """One observation at the centre of the cell."""
    return xr.Dataset(
        {k: ("obs", np.array([v], dtype="f8")) for k, v in vars_.items()},
        coords={"time": ("obs", pd.to_datetime(["2026-01-01T00:00"]).values),
                "lat": ("obs", [0.5]), "lon": ("obs", [0.5])},
    )


def test_direction_interpolation_wraps_around_north():
    """Corners at 350 and 10 deg must give 0, not the 180 a plain mean yields."""
    mwd = [[350.0, 10.0], [350.0, 10.0]]
    out = collocate_track(_obs(mwd=0.0), _cube(mwd=mwd), variables=["mwd"])
    got = float(out["model_mwd"].values[0])
    assert min(got, 360.0 - got) < 1e-6, f"expected ~0/360, got {got}"


def test_wind_uses_vector_interpolation():
    """Opposing winds across a cell cancel: speed at the centre is ~0, which
    scalar interpolation of pre-computed speeds could never produce."""
    u = [[5.0, -5.0], [5.0, -5.0]]
    v = [[0.0, 0.0], [0.0, 0.0]]
    out = collocate_track(_obs(wind_speed=0.0), _cube(u10=u, v10=v),
                          variables=["wind_speed"])
    assert float(out["model_wind_speed"].values[0]) == pytest.approx(0.0, abs=1e-9)


def test_wind_speed_and_direction_are_consistent():
    """speed/direction derived at the obs point agree with interpolated u/v."""
    u = [[3.0, 1.0], [2.0, 4.0]]
    v = [[4.0, 2.0], [1.0, 3.0]]
    cloud, model = _obs(wind_speed=0.0, wind_dir=0.0), _cube(u10=u, v10=v)
    out = collocate_track(cloud, model, variable="wind_speed")
    direction = collocate_track(cloud, model, variable="wind_dir")
    ui, vi = np.mean(u), np.mean(v)          # bilinear centre = mean of corners
    assert float(out["model_wind_speed"].values[0]) == pytest.approx(np.hypot(ui, vi))
    expect = (270.0 - np.degrees(np.arctan2(vi, ui))) % 360.0
    assert float(direction["model_wind_dir"].values[0]) == pytest.approx(expect)


def test_circular_stats_wrap_the_error():
    """350 deg observed vs 10 deg modelled is a +20 deg error, not +340."""
    s = pair_stats(np.array([350.0]), np.array([10.0]), circular=True)
    assert s["bias"] == pytest.approx(20.0)
    assert s["rmse"] == pytest.approx(20.0)


def test_scalar_stats_unchanged():
    s = pair_stats(np.array([1.0, 2.0, 3.0]), np.array([1.5, 2.5, 3.5]))
    assert s["bias"] == pytest.approx(0.5)
    assert s["rmse"] == pytest.approx(0.5)


# ── lead windows (see TODO.md: a window is the primitive, scalar is a case) ──

def test_parse_lead_scalar_and_window():
    from fieldmatch.models import parse_lead
    assert parse_lead(24) == (24.0, 24.0)
    assert parse_lead("24") == (24.0, 24.0)
    assert parse_lead("12-35") == (12.0, 35.0)
    assert parse_lead([12, 35]) == (12.0, 35.0)
    assert parse_lead(None) is None
    with pytest.raises(ValueError):
        parse_lead("35-12")
