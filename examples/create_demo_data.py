"""Create the tiny input files used by ``minimal_campaign.yaml``.

The values are synthetic and intentionally simple enough to inspect by hand.
Running this script only writes inside ``examples/data``.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr


HERE = Path(__file__).resolve().parent
DATA = HERE / "data"


def main():
    DATA.mkdir(exist_ok=True)
    times = pd.to_datetime([
        "2026-01-01T00:00:00",
        "2026-01-01T01:00:00",
        "2026-01-01T02:00:00",
    ])

    observations = xr.Dataset(
        {
            "VAVH": ("time", [1.2, 1.8, 2.4]),
            "VAVH_UNFILTERED": ("time", [1.2, 1.8, 2.4]),
            "WIND_SPEED": ("time", [5.0, 6.0, 7.0]),
        },
        coords={
            "time": times,
            "latitude": ("time", [0.25, 0.50, 0.75]),
            "longitude": ("time", [0.25, 0.50, 0.75]),
        },
        attrs={"title": "Synthetic CMEMS-like altimeter track"},
    )
    observations.to_netcdf(DATA / "altimeter.nc")

    lat = np.array([0.0, 1.0])
    lon = np.array([0.0, 1.0])
    shape = (times.size, lat.size, lon.size)
    model = xr.Dataset(
        {
            "hs": (("time", "lat", "lon"),
                   np.broadcast_to(np.array([1.0, 2.0, 3.0])[:, None, None], shape)),
            "u10": (("time", "lat", "lon"), np.full(shape, 3.0)),
            "v10": (("time", "lat", "lon"), np.full(shape, 4.0)),
        },
        coords={"time": times, "lat": lat, "lon": lon},
        attrs={"title": "Synthetic rectilinear model"},
    )
    model.to_netcdf(DATA / "model.nc")
    print(f"Wrote {DATA / 'altimeter.nc'}")
    print(f"Wrote {DATA / 'model.nc'}")


if __name__ == "__main__":
    main()
