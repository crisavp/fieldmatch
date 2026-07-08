"""Per-file satellite cleaners + merge-stage loaders.

Vendored from wave_models2/python/utils/sat_preprocess.py so matchup depends on
nothing from that repo and stays portable. Behaviour is unchanged.

- ASCAT_preprocess / SENTINEL1_preprocess: clean one raw L2 file, crop to a
  region bbox, return a standardized Dataset (or None to skip the file).
- load_and_stack_ascat / load_and_stack_sentinel: reopen a collocated file and
  stack its spatial dims into a 1-D `obs` index, applying quality filters, for
  the merge stage.
"""
import os
import warnings

import numpy as np
import xarray as xr


def ASCAT_preprocess(file, user_region=None, user_coords=None, obsLON360=True):
    """Preprocess one ASCAT L2 file: fix longitude, normalize time, crop to region.

    Args:
        file: path to the NetCDF file.
        user_region: {'lonmin','lonmax','latmin','latmax'} overriding defaults.
        user_coords: map standard names {'time','lon','lat'} to dataset names.
        obsLON360: True if source longitude is 0-360 (converted to -180..180).

    Returns:
        xarray.Dataset, or None if the file is skipped (inconsistent time across
        cells, or no data in the region).
    """
    coords = {'time': 'time', 'lon': 'lon', 'lat': 'lat'}
    if user_coords:
        coords.update(user_coords)

    region = {
        'lonmin': 0 if obsLON360 else -180,
        'lonmax': 360 if obsLON360 else 180,
        'latmin': -90, 'latmax': 90,
    }
    if user_region:
        region.update(user_region)

    lon_var, lat_var, time_var = coords['lon'], coords['lat'], coords['time']

    ds_sat = xr.open_dataset(file)

    if obsLON360:
        ds_sat[lon_var] = (ds_sat[lon_var] + 180) % 360 - 180

    # Time must be identical across all cells of a row; otherwise skip the file.
    same_time = np.all(
        ds_sat[time_var].values == ds_sat[time_var].isel(NUMCELLS=0).values[:, None]
    )
    if not same_time:
        warnings.warn(f"Time values are not the same for all cells in {file}.")
        return None
    time_row = ds_sat[time_var].isel(NUMCELLS=0)
    ds_sat = ds_sat.drop_vars(time_var).assign_coords(time=('NUMROWS', time_row.values))
    ds_sat = ds_sat.sortby(time_var).swap_dims({'NUMROWS': time_var})

    mask = ((ds_sat[lon_var] >= region['lonmin']) & (ds_sat[lon_var] <= region['lonmax']) &
            (ds_sat[lat_var] >= region['latmin']) & (ds_sat[lat_var] <= region['latmax']))
    if not mask.any():
        warnings.warn(f"No data in the specified region for file {file}.")
        return None
    ds_sat = ds_sat.where(mask, drop=True)

    return ds_sat


def SENTINEL1_preprocess(file, user_varmap=None, user_dimsmap=None,
                         user_region=None, user_coords=None, obsLON360=False):
    """Preprocess one Sentinel-1 OCN file: rename owi* vars/dims, crop to region."""
    variable_map = {
        'owiLon': 'lon', 'owiLat': 'lat',
        'owiWindSpeed': 'wind_speed', 'owiWindDirection': 'wind_dir',
        'owiWindQuality': 'wind_quality',
        'owiEcmwfWindSpeed': 'ecmwf_wind_speed',
        'owiEcmwfWindDirection': 'ecmwf_wind_dir',
    }
    if user_varmap:
        variable_map.update(user_varmap)

    dimension_map = {'owiAzSize': 'NUMROWS', 'owiRaSize': 'NUMCELLS'}
    if user_dimsmap:
        dimension_map.update(user_dimsmap)

    region = {
        'lonmin': 0 if obsLON360 else -180,
        'lonmax': 360 if obsLON360 else 180,
        'latmin': -90, 'latmax': 90,
    }
    if user_region:
        region.update(user_region)

    coords = {'time': 'time', 'lon': 'lon', 'lat': 'lat'}
    if user_coords:
        coords.update(user_coords)
    lon_var, lat_var, time_var = coords['lon'], coords['lat'], coords['time']

    ds_sat = xr.open_dataset(file)
    ds_sat = ds_sat[list(variable_map.keys())].rename(variable_map)
    ds_sat = ds_sat.rename_dims(dimension_map)
    if obsLON360:
        ds_sat['lon'] = (ds_sat['lon'] + 180) % 360 - 180
    timestamp = np.datetime64(ds_sat.attrs['firstMeasurementTime'])
    ds_sat = ds_sat.expand_dims({time_var: [timestamp]})
    ds_sat = ds_sat.set_coords(['lon', 'lat'])
    mask = ((ds_sat[lon_var] >= region['lonmin']) & (ds_sat[lon_var] <= region['lonmax']) &
            (ds_sat[lat_var] >= region['latmin']) & (ds_sat[lat_var] <= region['latmax']))
    if not mask.any():
        warnings.warn(f"No data in the specified region for file {file}.")
        return None
    ds_sat = ds_sat.where(mask, drop=True)

    return ds_sat


def load_and_stack_ascat(filepath):
    """Open one collocated ASCAT file and stack its spatial dims into `obs`."""
    try:
        with xr.open_dataset(filepath) as ds:
            if 'time' in ds.dims and 'NUMROWS' in ds.dims and 'NUMCELLS' in ds.dims:
                ds = ds.stack(obs=('time', 'NUMROWS', 'NUMCELLS'))
                ds = ds.where(ds['wvc_quality_flag'] < 65536, drop=True)
                ds['wind_dir'] = (ds['wind_dir'] + 180) % 360  # met convention
                ds = ds.dropna(dim='obs', subset=['wind_speed'])
                return ds
            elif 'time' in ds.dims and 'NUMCELLS' in ds.dims:
                ds = ds.stack(obs=('time', 'NUMCELLS'))
                ds = ds.where(ds['wvc_quality_flag'] < 65536, drop=True)
                ds['wind_dir'] = (ds['wind_dir'] + 180) % 360  # met convention
                ds = ds.dropna(dim='obs', subset=['wind_speed'])
                return ds
            else:
                return ds
    except Exception as e:
        print(f"Warning: Could not process {os.path.basename(filepath)}. Error: {e}")
        return None


def load_and_stack_sentinel(filepath):
    """Open one collocated Sentinel-1 file and stack its spatial dims into `obs`."""
    try:
        with xr.open_dataset(filepath) as ds:
            if 'time' in ds.dims and 'NUMROWS' in ds.dims and 'NUMCELLS' in ds.dims:
                ds = ds.stack(obs=('time', 'NUMROWS', 'NUMCELLS'))
                ds = ds.where((ds['wind_quality'] == 0) & (ds['wind_speed'].notnull()), drop=True)
                return ds
            elif 'time' in ds.dims and 'NUMCELLS' in ds.dims:
                ds = ds.stack(obs=('time', 'NUMCELLS'))
                ds = ds.where((ds['wind_quality'] == 0) & (ds['wind_speed'].notnull()), drop=True)
                return ds
            else:
                return ds
    except Exception as e:
        print(f"Warning: Could not process {os.path.basename(filepath)}. Error: {e}")
        return None
