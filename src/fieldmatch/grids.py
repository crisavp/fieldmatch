"""Explicit rectilinear model comparisons on the first model's grid.

Exact common valid times only. No temporal interpolation or spatial extrapolation.
The caller chooses which dataset defines the grid and the forecast comparison basis.
"""
import json
import numpy as np
import xarray as xr
from .quantities import validate, definition, unit_name, DIRECTION_VARS
from .collocate_track import source_fields
from .forecast import forecast_view
from .spatial import sample_quantity

def _fields(ds, variable):
    for axis in ('time', 'lat', 'lon'):
        if axis not in ds.coords or ds[axis].dims != (axis,):
            raise ValueError(f'{axis} must be a one-dimensional coordinate')
        a = ds[axis].values
        if axis == 'time':
            if a.dtype.kind != 'M' or not len(a) or np.isnat(a).any() or (np.diff(a) <= np.timedelta64(0, 's')).any():
                raise ValueError('time must contain increasing unique valid timestamps')
        elif len(a) < 2 or not np.isfinite(a).all() or (np.diff(a) <= 0).any():
            raise ValueError(f'{axis} must be finite, increasing and contain at least two points')
    if (abs(ds.lat.values) > 90).any() or (abs(ds.lon.values) > 180).any():
        raise ValueError('use latitude [-90,90] and longitude [-180,180]; normalize before comparing')
    if float(ds.lon[-1]-ds.lon[0]) >= 360:
        raise ValueError('periodic longitude seams need explicit preprocessing')
    sources = source_fields(variable, available=ds.data_vars)
    if set(sources) - set(ds):
        raise ValueError(f'missing source fields {sources}; normalize variable names before comparing')
    fields = {s: validate(ds[s], s if sources == ['u10','v10'] else variable) for s in sources}
    if any(f.dims != ('time','lat','lon') for f in fields.values()):
        raise ValueError('fields must have dimensions time,lat,lon')
    return fields


def compare_grids(reference, candidate, variable, *, space_method,
                  reference_name='reference', candidate_name='candidate',
                  forecast_pairing=None,
                  direction_resultant_min=1e-10, wind_direction_min_speed=1e-10):
    """Return masked reference/candidate fields, candidate-minus-reference and counts.

    Dataset selectors define each forecast view. Comparison joins those views at
    exact common valid times. When both inputs are forecasts the caller must say
    whether initialization and lead must also agree (``same_forecast``) or only
    the verifying timestamp must agree (``same_valid_time``).
    Finite masks are independent at each time. Source metadata are kept in JSON.
    """
    if space_method not in {'bilinear', 'nearest'}:
        raise ValueError('select space_method bilinear or nearest')
    for v in (direction_resultant_min, wind_direction_min_speed):
        if not np.isfinite(v) or v < 0:
            raise ValueError('direction thresholds must be finite and nonnegative')
    if direction_resultant_min > 1:
        raise ValueError('direction_resultant_min cannot exceed 1')
    rf, cf = _fields(reference, variable), _fields(candidate, variable)
    reference_view, candidate_view = forecast_view(reference), forecast_view(candidate)
    both_forecasts = (reference_view['time_kind'] == 'forecast'
                      and candidate_view['time_kind'] == 'forecast')
    if both_forecasts:
        if forecast_pairing not in {'same_forecast', 'same_valid_time'}:
            raise ValueError("two forecasts require forecast_pairing='same_forecast' "
                             "or 'same_valid_time'")
    elif forecast_pairing is not None:
        raise ValueError('forecast_pairing applies only when both grids are forecasts')
    # Unknown quantities still require explicit, compatible units on both sides.
    def units(fields):
        return ('degrees' if variable == 'wind_dir' else 'm s-1') if set(fields) == {'u10','v10'} else unit_name(next(iter(fields.values())).attrs.get('units'))
    if not units(rf) or units(rf) != units(cf):
        raise ValueError('reference and candidate require compatible declared units')
    times = np.intersect1d(reference.time.values, candidate.time.values)
    if not len(times):
        raise ValueError('no exact common valid times')
    if both_forecasts and forecast_pairing == 'same_forecast':
        r_init = reference.init.sel(time=times).values.astype('datetime64[ns]')
        c_init = candidate.init.sel(time=times).values.astype('datetime64[ns]')
        r_lead = np.asarray(reference.lead_hours.sel(time=times), dtype=float)
        c_lead = np.asarray(candidate.lead_hours.sel(time=times), dtype=float)
        if not np.array_equal(r_init, c_init) or not np.array_equal(r_lead, c_lead):
            raise ValueError("forecast_pairing='same_forecast' requires equal "
                             "initialization and lead at every common valid time")
    y, x = np.meshgrid(reference.lat.values, reference.lon.values, indexing='ij')
    points = np.column_stack([y.ravel(), x.ravel()])
    shape = (len(times), *y.shape)
    arrays = []
    for ds, fields in ((reference, rf), (candidate, cf)):
        selected = {s: f.sel(time=times) for s, f in fields.items()}
        a = np.empty(shape)
        for i in range(len(times)):
            a[i] = sample_quantity({s:f.isel(time=i).values for s,f in selected.items()},
                variable, ds.lat.values, ds.lon.values, points, space_method,
                direction_resultant_min, wind_direction_min_speed).reshape(y.shape)
        arrays.append(a)
    a, b = arrays
    valid = np.isfinite(a) & np.isfinite(b)
    if not valid.any():
        raise ValueError('no common finite cells after spatial sampling')
    difference = b - a
    circular = definition(variable) in DIRECTION_VARS
    if circular:
        difference = (difference + 180.) % 360. - 180.
    attrs = dict(quantity=definition(variable), units='degrees' if circular else units(rf))
    if circular:
        attrs['direction_convention'] = 'from_north_clockwise'
    ds = xr.Dataset(coords={'time':times, 'lat':reference.lat.values, 'lon':reference.lon.values})
    # Preserve each sampled field's independent availability. Difference and
    # all comparison statistics use the common finite mask.
    for name, value in [('reference',a),('candidate',b)]:
        ds[name] = (('time','lat','lon'), value, dict(attrs))
    ds['difference'] = (('time','lat','lon'), np.where(valid,difference,np.nan), dict(attrs))
    ds.difference.attrs.pop('direction_convention', None)
    ds.difference.attrs['long_name'] = f'{candidate_name} minus {reference_name}'
    provenance = {}
    selected_views = {}
    for label, source, fields in [('reference',reference,rf),('candidate',candidate,cf)]:
        provenance[label] = {s:dict(f.attrs) for s,f in fields.items()}
        selected_views[label] = forecast_view(source.sel(time=times))
    ds.attrs.update(comparison_kind='grid', variable=variable, quantity=definition(variable),
        reference_name=reference_name, candidate_name=candidate_name,
        target_grid=reference_name, difference_sign='candidate minus reference',
        time_method='exact', space_method=space_method,
        forecast_pairing=(forecast_pairing if both_forecasts else 'not_applicable'),
        mask_policy='common_finite_per_time', extrapolation='none',
        missing_corners='reject_nonzero_weight', direction_resultant_min=float(direction_resultant_min),
        wind_direction_min_speed=float(wind_direction_min_speed),
        n_reference_times=reference.sizes['time'], n_candidate_times=candidate.sizes['time'],
        n_common_times=len(times), n_selected_times=len(times),
        forecast_views=json.dumps(selected_views,sort_keys=True),
        source_attributes=json.dumps(provenance,default=str,sort_keys=True))
    return ds


def grid_stats(ds):
    """Per-time area-weighted signed difference and RMS difference, not truth scores.

    Weights are spherical cell areas with edges halfway between grid coordinates,
    extrapolated by half a spacing at boundaries and clipped at the poles.
    Direction differences are wrapped; bias is the arithmetic mean signed error,
    consistent with pair_stats (inspect the distribution near +/-180 degrees).
    """
    if ds.attrs.get('comparison_kind') != 'grid':
        raise ValueError('grid_stats requires compare_grids output')
    def edges(a):
        return np.r_[a[0]-(a[1]-a[0])/2, (a[:-1]+a[1:])/2, a[-1]+(a[-1]-a[-2])/2]
    lat = np.deg2rad(np.clip(edges(ds.lat.values),-90,90))
    lon = np.deg2rad(edges(ds.lon.values))
    weights = xr.DataArray(np.diff(np.sin(lat))[:,None]*np.diff(lon)[None,:],
                           dims=('lat','lon'),coords={'lat':ds.lat,'lon':ds.lon})
    valid = np.isfinite(ds.reference) & np.isfinite(ds.candidate)
    valid_weights = weights.where(valid)
    total = valid_weights.sum(('lat','lon'))
    out = xr.Dataset({
        'mean_difference':(ds.difference*valid_weights).sum(('lat','lon'))/total,
        'rms_difference':np.sqrt((ds.difference**2*valid_weights).sum(('lat','lon'))/total),
        'valid_area_fraction':total/weights.sum(),
        'n_common':valid.sum(('lat','lon')).astype('int64')})
    # Arithmetic on a DataArray carries all auxiliary coordinates. They belong
    # in the detailed grid result, not in this deliberately compact table.
    auxiliary = [name for name in out.coords if name != 'time']
    if auxiliary:
        out = out.drop_vars(auxiliary)
    for key in ('mean_difference','rms_difference'):
        out[key].attrs['units'] = ds.difference.attrs['units']
    out.attrs.update(ds.attrs, spatial_weighting='spherical midpoint cells')
    return out


def grid_point_stats(ds):
    """Bias, RMS difference and common count at each saved grid point."""
    if ds.attrs.get('comparison_kind') != 'grid':
        raise ValueError('grid_point_stats requires compare_grids output')
    valid = np.isfinite(ds.reference) & np.isfinite(ds.candidate)
    difference = ds.difference.where(valid)
    out = xr.Dataset({
        'mean_difference': difference.mean('time', skipna=True),
        'rms_difference': np.sqrt((difference ** 2).mean('time', skipna=True)),
        'n_common': valid.sum('time').astype('int64'),
    })
    for name in ('mean_difference', 'rms_difference'):
        out[name].attrs['units'] = ds.difference.attrs['units']
    out.attrs.update(ds.attrs, statistics_dimension='time')
    return out
