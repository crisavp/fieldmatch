"""Compact forecast provenance for prepared station and grid results."""
import json

import numpy as np
import pandas as pd


def forecast_view(dataset):
    """Return a compact, serializable description of actual forecast samples.

    Forecast initialization and lead remain essential provenance, but they do
    not need to appear as scientific data variables.  Samples are grouped by
    initialization; valid time is reconstructed as initialization plus lead.
    """
    time_kind = dataset.attrs.get("fieldmatch_time_kind")
    is_forecast = (time_kind == "forecast" or
                   (time_kind is None and {"init", "lead_hours"} <= set(dataset.coords)))
    if not is_forecast:
        return {"time_kind": "valid_time_only"}
    if "init" not in dataset.coords or "lead_hours" not in dataset.coords:
        raise ValueError("forecast data require init and lead_hours coordinates")
    records = []
    init = dataset.init.values.astype("datetime64[ns]")
    lead = np.asarray(dataset.lead_hours.values, dtype=float)
    for value in np.unique(init):
        selected = lead[init == value]
        records.append({
            "init": np.datetime_as_string(value, unit="ns"),
            "lead_hours": selected.tolist(),
        })
    return {"time_kind": "forecast", "runs": records}


def encode_forecast_view(dataset):
    return json.dumps(forecast_view(dataset), sort_keys=True, separators=(",", ":"))


def _rows(view, side):
    if view.get("time_kind") != "forecast":
        return []
    rows = []
    for run in view["runs"]:
        initialization = np.datetime64(run["init"], "ns")
        for lead in run["lead_hours"]:
            valid = initialization + np.timedelta64(round(float(lead) * 3_600_000_000_000), "ns")
            rows.append({"side": side, "time": valid, "init": initialization,
                         "lead_hours": float(lead)})
    return rows


def forecast_table(result):
    """Expand a prepared result's compact forecast provenance on request."""
    if "forecast_views" in result.attrs:
        views = json.loads(result.attrs["forecast_views"])
    elif "forecast_view" in result.attrs:
        views = {result.attrs.get("fieldmatch_dataset", "model"):
                 json.loads(result.attrs["forecast_view"])}
    elif "model_forecast_view" in result.attrs:
        views = {result.attrs.get("model_name", "model"):
                 json.loads(result.attrs["model_forecast_view"])}
    elif "time" in result.coords:
        views = {result.attrs.get("fieldmatch_dataset", "model"): forecast_view(result)}
    else:
        return pd.DataFrame(columns=["side", "time", "init", "lead_hours"])
    rows = []
    for side, view in views.items():
        rows.extend(_rows(view, side))
    frame = pd.DataFrame(rows, columns=["side", "time", "init", "lead_hours"])
    return frame.sort_values(["side", "time"], ignore_index=True) if len(frame) else frame
