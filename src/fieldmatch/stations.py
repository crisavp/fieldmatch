"""Native station extraction followed by an optional explicit time match."""
import numpy as np
import xarray as xr

from .campaign import execution_digest
from .collocate_track import _nearest_step, source_fields
from .forecast import encode_forecast_view
from .quantities import definition, validate
from .spatial import sample_quantity


def station_location(observations):
    """Return the fixed latitude/longitude of a stationary observation set."""
    lat = np.unique(observations.lat.values[np.isfinite(observations.lat.values)])
    lon = np.unique(observations.lon.values[np.isfinite(observations.lon.values)])
    if len(lat) != 1 or len(lon) != 1:
        raise ValueError("station extraction requires one fixed observation location")
    return float(lat[0]), float(lon[0])


def extract_station(model, *, observations=None, lat=None, lon=None, variables,
                    space_method="bilinear", direction_resultant_min=1e-10,
                    wind_direction_min_speed=1e-10):
    """Sample every native model time at one fixed point, without time matching."""
    variables = [variables] if isinstance(variables, str) else list(variables)
    if not variables:
        raise ValueError("select at least one station variable")
    if observations is not None:
        if lat is not None or lon is not None:
            raise ValueError("use observations or explicit lat/lon, not both")
        lat, lon = station_location(observations)
    if lat is None or lon is None:
        raise ValueError("provide observations or both lat and lon")
    if not (-90 <= float(lat) <= 90 and -180 <= float(lon) <= 180):
        raise ValueError("station latitude/longitude are outside valid bounds")
    if space_method not in {"bilinear", "nearest"}:
        raise ValueError("space_method must be bilinear or nearest")

    point = np.array([[float(lat), float(lon)]])
    data = {}
    for variable in variables:
        sources = source_fields(variable, available=model.data_vars)
        missing = set(sources) - set(model.data_vars)
        if missing:
            raise ValueError(f"model variable(s) absent for {variable}: {sorted(missing)}")
        vector = sources == ["u10", "v10"]
        fields = {name: validate(model[name], name if vector else variable)
                  for name in sources}
        if any(field.dims != ("time", "lat", "lon") for field in fields.values()):
            raise ValueError("station model fields must have dimensions time,lat,lon")
        values = np.full(model.sizes["time"], np.nan)
        for i in range(model.sizes["time"]):
            values[i] = sample_quantity(
                {name: field.isel(time=i).values for name, field in fields.items()},
                variable, model.lat.values, model.lon.values, point, space_method,
                direction_resultant_min, wind_direction_min_speed,
            )[0]
        attrs = dict(model[variable].attrs if variable in model
                     else next(iter(fields.values())).attrs)
        attrs["quantity"] = definition(variable)
        data[variable] = ("time", values, attrs)

    result = xr.Dataset(data, coords={"time": model.time.values})
    result.attrs.update(
        comparison_kind="station_extraction",
        fieldmatch_dataset=model.attrs.get("fieldmatch_dataset", "model"),
        fieldmatch_campaign=model.attrs.get("fieldmatch_campaign", ""),
        station_latitude=float(lat), station_longitude=float(lon),
        space_method=space_method, extrapolation="none",
        missing_corners="reject_nonzero_weight",
        forecast_view=encode_forecast_view(model),
    )
    return result


def _tolerance(value):
    if isinstance(value, str):
        import pandas as pd
        value = pd.Timedelta(value).to_timedelta64()
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        value = np.timedelta64(round(float(value) * 60 * 1_000_000_000), "ns")
    value = np.asarray(value).astype("timedelta64[ns]")[()]
    if np.isnat(value) or value < np.timedelta64(0, "ns"):
        raise ValueError("tolerance must be a finite nonnegative duration")
    return value


def match_times(observations, station, *, variable, tolerance="30min",
                time_tie="earlier"):
    """Match observations to a native station series using nearest time only."""
    if variable not in observations or variable not in station:
        raise ValueError(f"{variable!r} must exist in observations and station series")
    if station[variable].dims != ("time",):
        raise ValueError("station variable must use the time dimension")
    observed = validate(observations[variable], variable)
    modeled = validate(station[variable], variable)
    times = station.time.values.astype("datetime64[ns]")
    if not len(times) or np.isnat(times).any() or (np.diff(times) <= np.timedelta64(0, "ns")).any():
        raise ValueError("station time must be finite, unique and increasing")
    finite_model = np.flatnonzero(np.isfinite(modeled.values))
    if not len(finite_model):
        raise ValueError(f"station {variable!r} contains no finite values")
    available_times = times[finite_model]
    observation_times = observations.time.values.astype("datetime64[ns]")
    valid_observations = ~np.isnat(observation_times) & np.isfinite(observed.values)
    selected, offset = _nearest_step(
        np.where(valid_observations, observation_times, available_times[0]),
        available_times, time_tie,
    )
    tolerance = _tolerance(tolerance)
    accepted = valid_observations & (offset <= tolerance)
    if not accepted.any():
        raise ValueError("no observations match a finite station value within the tolerance")
    keep = np.flatnonzero(accepted)
    model_step = finite_model[selected[keep]]
    extras = [name for name in observations.data_vars
              if name.startswith("x_") or name in {"obs_id", "source_file", "record_index"}]
    result = observations[[variable, *extras]].isel(obs=keep).copy()
    result[f"model_{variable}"] = ("obs", modeled.values[model_step], dict(modeled.attrs))
    identities = [name for name in ("obs_id", "source_file", "record_index") if name in result]
    if identities:
        result = result.set_coords(identities)
    result = result.assign_coords(
        model_time=("obs", times[model_step]),
        time_offset_seconds=("obs", (observation_times[keep] - times[model_step])
                             / np.timedelta64(1, "s")),
    )
    result.attrs.update(
        comparison_kind="observation_model",
        variable=variable, quantity=definition(variable),
        model_name=station.attrs.get("fieldmatch_dataset", "model"),
        time_method="nearest", time_tie=time_tie,
        time_tolerance_minutes=float(tolerance / np.timedelta64(1, "m")),
        model_forecast_view=station.attrs.get("forecast_view", "{}"),
        observation_contract=execution_digest({
            "reader": observations.attrs.get("reader"),
            "source": observations.attrs.get(f"{variable}_source", variable),
            "quantity": observed.attrs.get("quantity", definition(variable)),
            "units": observed.attrs.get("units"),
        }),
        n_input=observations.sizes["obs"], n_accepted=len(keep),
        n_rejected_observation=int((~valid_observations).sum()),
        n_rejected_time=int((valid_observations & ~accepted).sum()),
    )
    return result
