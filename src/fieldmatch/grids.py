"""Explicit rectilinear model comparisons on the first model's grid.

Exact common valid times only. No temporal interpolation or spatial extrapolation.
The caller chooses which dataset defines the grid and the forecast comparison basis.
"""
import json
import numpy as np
import xarray as xr
from .quantities import validate, definition, unit_name, DIRECTION_VARS
from .collocate_track import source_fields
from .spatial import sample_quantity

TIME_BASES = {'valid_time', 'same_init', 'same_lead'}


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


def compare_grids(reference, candidate, variable, *, space_method, time_basis,
                  reference_name='reference', candidate_name='candidate',
                  direction_resultant_min=1e-10, wind_direction_min_speed=1e-10):
    """Return masked reference/candidate fields, candidate-minus-reference and counts.

    ``time_basis`` is required: valid_time permits different initializations;
    same_init/same_lead additionally require equal finite forecast coordinates.
    These restrictions filter exact common valid times, never move them.
    Finite masks are independent at each time. Source metadata are kept in JSON.
    """
    if space_method not in {'bilinear', 'nearest'} or time_basis not in TIME_BASES:
        raise ValueError('select space_method bilinear/nearest and time_basis valid_time/same_init/same_lead')
    for v in (direction_resultant_min, wind_direction_min_speed):
        if not np.isfinite(v) or v < 0:
            raise ValueError('direction thresholds must be finite and nonnegative')
    if direction_resultant_min > 1:
        raise ValueError('direction_resultant_min cannot exceed 1')
    rf, cf = _fields(reference, variable), _fields(candidate, variable)
    # Unknown quantities still require explicit, compatible units on both sides.
    def units(fields):
        return ('degrees' if variable == 'wind_dir' else 'm s-1') if set(fields) == {'u10','v10'} else unit_name(next(iter(fields.values())).attrs.get('units'))
    if not units(rf) or units(rf) != units(cf):
        raise ValueError('reference and candidate require compatible declared units')
    times = np.intersect1d(reference.time.values, candidate.time.values)
    n_common_times = len(times)
    if time_basis != 'valid_time':
        coordinate = 'init' if time_basis == 'same_init' else 'lead_hours'
        values = []
        for ds in (reference, candidate):
            if coordinate not in ds.coords or ds[coordinate].dims != ('time',):
                raise ValueError(f'{time_basis} requires a {coordinate} coordinate on time')
            values.append(ds[coordinate].sel(time=times).values)
        a, b = values
        finite = (~np.isnat(a) & ~np.isnat(b)) if coordinate == 'init' else (np.isfinite(a) & np.isfinite(b))
        times = times[finite & (a == b)]
    if not len(times):
        raise ValueError('no exact common valid times satisfy the selected time basis')
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
    for name, value in [('reference',a),('candidate',b),('difference',difference)]:
        ds[name] = (('time','lat','lon'), np.where(valid,value,np.nan), dict(attrs))
    ds.difference.attrs.pop('direction_convention', None)
    ds.difference.attrs['long_name'] = f'{candidate_name} minus {reference_name}'
    ds['valid'] = (('time','lat','lon'),valid.astype('uint8'), {'long_name':'common finite mask; 1 accepted, 0 missing'})
    for name,mask in [('reference',np.isfinite(a)),('candidate',np.isfinite(b)),('common',valid)]:
        ds[f'n_{name}'] = ('time',mask.sum(axis=(1,2)))
    provenance = {}
    for label, source, fields in [('reference',reference,rf),('candidate',candidate,cf)]:
        provenance[label] = {s:dict(f.attrs) for s,f in fields.items()}
        for key in ('init','lead_hours'):
            if key in source.coords:
                if source[key].dims != ('time',):
                    raise ValueError(f'{key} must be normalized on time before comparing')
                ds[f'{label}_{key}'] = ('time',source[key].sel(time=times).values)
    ds.attrs.update(comparison_kind='grid', variable=variable, quantity=definition(variable),
        reference_name=reference_name, candidate_name=candidate_name,
        target_grid=reference_name, difference_sign='candidate minus reference',
        time_method='exact', time_basis=time_basis, space_method=space_method,
        mask_policy='common_finite_per_time', extrapolation='none',
        missing_corners='reject_nonzero_weight', direction_resultant_min=float(direction_resultant_min),
        wind_direction_min_speed=float(wind_direction_min_speed),
        n_reference_times=reference.sizes['time'], n_candidate_times=candidate.sizes['time'],
        n_common_times_before_basis=n_common_times, n_selected_times=len(times),
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
    valid_weights = weights.where(ds.valid == 1)
    total = valid_weights.sum(('lat','lon'))
    out = xr.Dataset({
        'mean_difference':(ds.difference*valid_weights).sum(('lat','lon'))/total,
        'rms_difference':np.sqrt((ds.difference**2*valid_weights).sum(('lat','lon'))/total),
        'valid_area_fraction':total/weights.sum(), 'n_common':ds.n_common})
    for key in ('mean_difference','rms_difference'):
        out[key].attrs['units'] = ds.difference.attrs['units']
    for key in ('reference_init','candidate_init','reference_lead_hours','candidate_lead_hours'):
        if key in ds: out[key] = ds[key]
    out.attrs.update(ds.attrs, spatial_weighting='spherical midpoint cells')
    return out
