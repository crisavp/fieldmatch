"""Regression tests for campaign workflow correctness and provenance."""
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from fieldmatch.campaign import (Dataset, load_campaign, validate_run_manifest,
                              write_run_manifest)
from fieldmatch.collocate_track import NoUsableModelValues, collocate_track, write_pairs
from fieldmatch.models import open_model
from fieldmatch.pairstats import pair_stats
from fieldmatch.readers import _cloud, _collect_extras, read_ascat, read_buoy_ispra
from fieldmatch.scan import (_add_quality_inventory, format_report,
                             model_time_inventory, scan_model, var_cadences)


def _campaign_yaml(tmp_path, *, period="[2026-01-01, 2026-01-02]", option=""):
    obs = tmp_path / "obs.nc"
    model = tmp_path / "model.nc"
    path = tmp_path / "campaign.yaml"
    path.write_text(
        "campaign: test\n"
        "region: {lonmin: 0, lonmax: 2, latmin: 0, latmax: 2}\n"
        f"period: {period}\n"
        "datasets:\n"
        f"  obs: {{kind: altimeter_cmems, path: {obs}{option}}}\n"
        f"  model: {{kind: netcdf, path: {model}}}\n"
    )
    return path, obs, model


def test_date_only_end_includes_whole_final_day(tmp_path):
    path, _, _ = _campaign_yaml(tmp_path)
    camp = load_campaign(path)
    assert camp.period[1] == np.datetime64("2026-01-02T23:59:59.999999999")


def test_unknown_reader_option_is_rejected(tmp_path):
    path, _, _ = _campaign_yaml(tmp_path, option=", typo: true")
    with pytest.raises(ValueError, match="unsupported option.*typo"):
        load_campaign(path)


def test_file_dedup_hashes_only_suspected_collisions(tmp_path):
    paths = []
    for folder, payload in (("a", b"same"), ("b", b"same"), ("c", b"else")):
        directory = tmp_path / folder
        directory.mkdir()
        file = directory / "delivery.nc"
        file.write_bytes(payload)
        paths.append(str(file))
    dset = Dataset("obs", "altimeter_cmems", paths)
    with pytest.warns(UserWarning, match="keeping distinct files"):
        files = dset.files()
    assert files == [paths[0], paths[2]]


def test_generic_netcdf_coordinates_and_dimension_order(tmp_path):
    path = tmp_path / "model.nc"
    ds = xr.Dataset(
        {"wave": (("longitude", "latitude", "time"), np.ones((4, 3, 2)))},
        coords={"longitude": [-1.0, 0.0, 1.0, 2.0],
                "latitude": [-1.0, 0.0, 1.0],
                "time": pd.to_datetime(["2026-01-01", "2026-01-02"])},
    )
    ds.to_netcdf(path)
    out = open_model(str(path), engine="netcdf4")
    assert out["wave"].dims == ("time", "lat", "lon")
    assert out.sizes == {"time": 2, "lat": 3, "lon": 4}


def test_explicit_coordinate_map_can_replace_generic_xy_dimensions(tmp_path):
    path = tmp_path / "unusual.nc"
    xr.Dataset(
        {"wave": (("valid", "y", "x"), np.ones((1, 2, 2)))},
        coords={"valid": pd.to_datetime(["2026-01-01"]),
                "nav_lat": ("y", [0.0, 1.0]), "nav_lon": ("x", [0.0, 1.0])},
    ).to_netcdf(path)
    out = open_model(path, engine="netcdf4",
                     coords={"valid": "time", "nav_lat": "lat", "nav_lon": "lon"})
    assert out["wave"].dims == ("time", "lat", "lon")


def test_model_subset_keeps_grid_points_bracketing_a_narrow_box(tmp_path):
    path = tmp_path / "coarse.nc"
    xr.Dataset(
        {"wave": (("time", "lat", "lon"), np.ones((1, 2, 2)))},
        coords={"time": pd.to_datetime(["2026-01-01"]),
                "lat": [0.0, 1.0], "lon": [0.0, 1.0]},
    ).to_netcdf(path)
    out = open_model(path, engine="netcdf4",
                     bbox={"latmin": 0.4, "latmax": 0.6,
                           "lonmin": 0.4, "lonmax": 0.6})
    assert out.sizes["lat"] == 2 and out.sizes["lon"] == 2


def _cube_for_validity():
    times = pd.to_datetime(["2026-01-01T00", "2026-01-01T01"])
    shape = (2, 2, 2)
    hs = np.full(shape, np.nan)
    hs[0] = 2.0
    u = np.full(shape, np.nan)
    v = np.full(shape, np.nan)
    u[1], v[1] = 3.0, 4.0
    return xr.Dataset(
        {"hs": (("time", "lat", "lon"), hs),
         "u10": (("time", "lat", "lon"), u),
         "v10": (("time", "lat", "lon"), v)},
        coords={"time": times, "lat": [0.0, 1.0], "lon": [0.0, 1.0]},
    )


def _obs_at(time="2026-01-01T00:30"):
    return xr.Dataset(
        {"hs": ("obs", [2.0]), "wind_speed": ("obs", [5.0])},
        coords={"time": ("obs", pd.to_datetime([time])),
                "lat": ("obs", [0.5]), "lon": ("obs", [0.5])},
    )


def test_quantities_keep_independent_model_times():
    hs = collocate_track(_obs_at(), _cube_for_validity(), variable="hs")
    wind = collocate_track(_obs_at(), _cube_for_validity(), variable="wind_speed")
    assert hs.sizes["obs"] == wind.sizes["obs"] == 1
    assert set(hs.data_vars) == {"hs", "model_hs"}
    assert {"time", "lat", "lon", "model_time", "time_offset_seconds"} <= set(hs.coords)
    assert hs.time_offset_seconds.item() == 1800 and wind.time_offset_seconds.item() == -1800
    with pytest.raises(ValueError, match="one variable per result"):
        collocate_track(_obs_at(), _cube_for_validity(), variables=["hs", "wind_speed"])


def test_all_nan_spatial_interpolation_is_not_success():
    model = _cube_for_validity().isel(time=[0]).copy()
    model["hs"][:] = np.nan
    with pytest.raises(NoUsableModelValues, match="no finite values"):
        collocate_track(_obs_at("2026-01-01T00"), model, variables=["hs"])


def test_extra_variable_dtype_and_metadata_survive_cloud():
    src = xr.Dataset({"flag": ("record", np.array([1, 2], dtype="int16"),
                                      {"flag_meanings": "bad good"})})
    out, _ = _collect_extras(src, ["flag"], "record", {}, {})
    cloud = _cloud(pd.to_datetime(["2026-01-01", "2026-01-02"]),
                   [0.0, 0.0], [0.0, 0.0], out)
    assert cloud["x_flag"].dtype == np.dtype("int16")
    assert cloud["x_flag"].attrs["flag_meanings"] == "bad good"


def test_ascat_rejects_rows_with_multiple_times(tmp_path):
    path = tmp_path / "ascat.nc"
    shape = (1, 2)
    xr.Dataset(
        {"wind_speed": (("NUMROWS", "NUMCELLS"), np.ones(shape)),
         "wind_dir": (("NUMROWS", "NUMCELLS"), np.zeros(shape)),
         "wvc_quality_flag": (("NUMROWS", "NUMCELLS"), np.zeros(shape)),
         "lat": (("NUMROWS", "NUMCELLS"), np.zeros(shape)),
         "lon": (("NUMROWS", "NUMCELLS"), np.zeros(shape)),
         "time": (("NUMROWS", "NUMCELLS"),
                  np.array([["2026-01-01T00", "2026-01-01T00:01"]],
                           dtype="datetime64[m]"))},
    ).to_netcdf(path)
    with pytest.raises(ValueError, match="multiple timestamps"):
        read_ascat(path)


def test_ascat_can_retain_canonical_quality_flag(tmp_path):
    path = tmp_path / "ascat.nc"
    shape = (1, 2)
    xr.Dataset(
        {"wind_speed": (("NUMROWS", "NUMCELLS"), np.ones(shape)),
         "wind_dir": (("NUMROWS", "NUMCELLS"), np.zeros(shape)),
         "wvc_quality_flag": (("NUMROWS", "NUMCELLS"), np.array([[0, 1]], dtype="int16")),
         "lat": (("NUMROWS", "NUMCELLS"), np.zeros(shape)),
         "lon": (("NUMROWS", "NUMCELLS"), np.zeros(shape)),
         "time": ("NUMROWS", np.array(["2026-01-01T00"], dtype="datetime64[m]"))},
    ).to_netcdf(path)
    out = read_ascat(path, retain_qc=True)
    assert "x_wind_quality" in out
    assert out.x_wind_quality.dtype == np.dtype("int16")


def test_buoy_zero_direction_is_valid_north(tmp_path):
    path = tmp_path / "buoy.csv"
    path.write_text("time;la1WindSpd;la1WindDir\n2026-01-01 00:00:00;5;0\n")
    out = read_buoy_ispra(path, lat=1, lon=1)
    assert float(out["wind_dir"].values[0]) == 0.0


def test_origin_ols_is_named_accurately():
    stats = pair_stats(np.array([1.0, 2.0]), np.array([2.0, 4.0]))
    assert stats["ols_origin_slope"] == pytest.approx(2.0)
    assert "symmetric_slope" not in stats


def test_scan_reports_fixed_default_tolerance():
    ds = _cube_for_validity()
    assert var_cadences(ds)["hs"][1] == np.timedelta64(30, "m")


def test_scan_inventories_quality_meanings_and_counts():
    ds = xr.Dataset({
        "x_wind_quality": ("obs", np.array([3, 4, 4], dtype="int8"), {
            "flag_values": np.array([3, 4], dtype="int8"),
            "flag_meanings": "acceptable good",
        })
    })
    inventory = {}
    _add_quality_inventory(
        inventory, ds, {"x_wind_quality": "owiWindQuality"})
    entry = inventory["x_wind_quality"]
    assert entry["meanings"]["acceptable"]["count"] == 1
    assert entry["meanings"]["good"]["count"] == 2
    assert entry["source"] == "owiWindQuality"

    mask = xr.Dataset({
        "x_surface_mask": ("obs", np.array([0, 1, 4, 5], dtype="int8"), {
            "flag_values": np.array([0, 1, 4], dtype="int8"),
            "flag_meanings": "valid land no_data",
            "fieldmatch_flag_mode": "bitmask",
        })
    })
    _add_quality_inventory(inventory, mask, {"x_surface_mask": "owiMask"})
    surface = inventory["x_surface_mask"]
    assert surface["meanings"]["land"]["count"] == 2
    assert surface["meanings"]["no_data"]["count"] == 2
    assert not surface["unrecognized"]


def test_scan_distinguishes_forecast_metadata_from_valid_time_only(tmp_path):
    forecast_path = tmp_path / "forecast.nc"
    xr.Dataset(
        {"hs": (("time", "step", "lat", "lon"), np.ones((2, 2, 2, 2)))},
        coords={"time": np.array(["2026-01-01T00", "2026-01-01T12"], dtype="datetime64[ns]"),
                "step": np.array([12, 24], dtype="timedelta64[h]"),
                "lat": [0., 1.], "lon": [0., 1.]},
    ).to_netcdf(forecast_path)
    forecast = Dataset("forecast", "netcdf", [str(forecast_path)],
                       {"init_cycle": "00:00", "lead": 24})
    report = scan_model(forecast)
    assert report["time_kind"] == "forecast"
    assert report["raw_cycles"] == ["00:00", "12:00"]
    assert report["raw_lead_count"] == 2
    assert report["selection"] == {"init_cycle": "00:00", "lead": 24}

    valid_path = tmp_path / "valid.nc"
    xr.Dataset(
        {"hs": (("time", "lat", "lon"), np.ones((2, 2, 2)))},
        coords={"time": np.array(["2026-01-01T00", "2026-01-01T06"], dtype="datetime64[ns]"),
                "lat": [0., 1.], "lon": [0., 1.]},
    ).to_netcdf(valid_path)
    valid = Dataset("analysis", "netcdf", [str(valid_path)])
    valid_report = scan_model(valid)
    assert model_time_inventory(valid)["time_kind"] == "valid_time_only"

    camp = SimpleNamespace(name="test", bbox=dict(lonmin=0, lonmax=1, latmin=0, latmax=1),
                           period=(np.datetime64("2026-01-01"), np.datetime64("2026-01-02")))
    text = format_report(camp, {"forecast": report, "analysis": valid_report})
    assert "forecast (initialization + lead)" in text
    assert "cycles   : 00:00, 12:00 UTC" in text
    assert "selection: init_cycle=00:00, lead=24" in text
    assert "valid-time only" in text
    assert "selection: not applicable (no initialization/lead metadata)" in text

    with pytest.raises(ValueError, match="valid times only"):
        open_model(valid_path, engine="netcdf4", init_cycle="00:00", lead=24)


def test_manifest_rejects_changed_inputs(tmp_path):
    config, obs, model = _campaign_yaml(tmp_path)
    obs.write_bytes(b"obs")
    model.write_bytes(b"model")
    camp = load_campaign(config)
    stem = tmp_path / "pair"
    write_run_manifest(stem, camp, "obs", "model", "complete")
    assert validate_run_manifest(stem, camp, "obs", "model")[0]
    obs.write_bytes(b"changed")
    ok, reason = validate_run_manifest(stem, camp, "obs", "model")
    assert not ok and "changed" in reason


def test_pair_write_is_atomic_and_preserves_integer_extra(tmp_path):
    ds = xr.Dataset({"x_flag": ("obs", np.array([1, 2], dtype="int16"))},
                    coords={"time": ("obs", pd.to_datetime(["2026-01-01", "2026-01-02"])),
                            "lat": ("obs", [0.0, 0.0]), "lon": ("obs", [0.0, 0.0])})
    nc, csv = tmp_path / "pair.nc", tmp_path / "pair.csv"
    write_pairs(ds, tmp_path / "pair", ("csv", "netcdf"))
    assert xr.open_dataset(nc)["x_flag"].dtype == np.dtype("int16")
    assert "NaN" not in csv.read_text()
    assert not list(tmp_path.glob(".*.tmp"))


def test_campaign_cli_success_then_failed_run_blocks_old_output(tmp_path):
    from typer.testing import CliRunner
    from fieldmatch.cli import app

    config, obs_path, model_path = _campaign_yaml(tmp_path)
    times = pd.to_datetime(["2026-01-01T00", "2026-01-01T01"])
    xr.Dataset(
        {"VAVH": ("time", [1.0, 2.0]),
         "VAVH_UNFILTERED": ("time", [1.0, 2.0]),
         "WIND_SPEED": ("time", [5.0, 5.0])},
        coords={"time": times, "latitude": ("time", [0.5, 0.5]),
                "longitude": ("time", [0.5, 0.5])},
    ).to_netcdf(obs_path)
    shape = (2, 2, 2)
    model = xr.Dataset(
        {"hs": (("time", "latitude", "longitude"), np.ones(shape))},
        coords={"time": times, "latitude": [0.0, 1.0], "longitude": [0.0, 1.0]},
    )
    model.to_netcdf(model_path)

    runner = CliRunner()
    result = runner.invoke(app, ["collocate", str(config), "obs", "model", "--variable", "hs",
                                 "--format", "netcdf"])
    assert result.exit_code == 0, result.output
    nc = tmp_path / "fieldmatch_out" / "obs__model__hs.nc"
    original = nc.read_bytes()
    assert runner.invoke(app, ["stats", str(nc)]).exit_code == 0
    assert not list(nc.parent.glob("*_scatter.png"))

    model["hs"][:] = np.nan
    model.to_netcdf(model_path)
    failed = runner.invoke(app, ["collocate", str(config), "obs", "model", "--variable", "hs",
                                 "--format", "netcdf"])
    assert failed.exit_code == 1
    assert nc.read_bytes() == original
    stale = runner.invoke(app, ["stats", str(nc)])
    assert stale.exit_code == 1
    assert "refusing stale/incomplete output" in stale.output


def test_campaign_cli_defaults_to_csv_and_stats_accepts_it(tmp_path):
    from typer.testing import CliRunner
    from fieldmatch.cli import app

    config, obs_path, model_path = _campaign_yaml(tmp_path)
    times = pd.to_datetime(["2026-01-01T00", "2026-01-01T01"])
    xr.Dataset(
        {"VAVH": ("time", [1.0, 2.0]),
         "VAVH_UNFILTERED": ("time", [1.0, 2.0]),
         "WIND_SPEED": ("time", [5.0, 5.0])},
        coords={"time": times, "latitude": ("time", [0.5, 0.5]),
                "longitude": ("time", [0.5, 0.5])},
    ).to_netcdf(obs_path)
    xr.Dataset(
        {"hs": (("time", "latitude", "longitude"), np.ones((2, 2, 2)))},
        coords={"time": times, "latitude": [0.0, 1.0], "longitude": [0.0, 1.0]},
    ).to_netcdf(model_path)

    runner = CliRunner()
    result = runner.invoke(app, ["collocate", str(config), "obs", "model", "--variable", "hs"])
    assert result.exit_code == 0, result.output
    pairs = tmp_path / "fieldmatch_out" / "obs__model__hs.csv"
    assert pairs.exists() and not pairs.with_suffix(".nc").exists()
    report = tmp_path / "stats.csv"
    result = runner.invoke(app, ["stats", str(pairs), "--output", str(report)])
    assert result.exit_code == 0, result.output
    assert pd.read_csv(report).loc[0, "variable"] == "hs"
