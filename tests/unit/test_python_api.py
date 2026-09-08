import numpy as np
import pandas as pd
import pytest
import xarray as xr

from fieldmatch.forecast import forecast_table
from fieldmatch.stations import extract_station, match_times


def model():
    values = np.arange(12, dtype=float).reshape(3, 2, 2)
    return xr.Dataset(
        {'hs': (('time', 'lat', 'lon'), values, {'units': 'm'})},
        coords={
            'time': pd.date_range('2026-01-01', periods=3, freq='1h'),
            'lat': [0., 1.], 'lon': [0., 1.],
            'init': ('time', np.repeat(np.datetime64('2026-01-01', 'ns'), 3)),
            'lead_hours': ('time', [0., 1., 2.]),
        },
        attrs={'fieldmatch_time_kind': 'forecast', 'fieldmatch_dataset': 'forecast'},
    )


def observations():
    return xr.Dataset(
        {'hs': ('obs', [1.5, 5.5, 9.5], {'units': 'm'})},
        coords={
            'time': ('obs', pd.to_datetime([
                '2026-01-01T00:20', '2026-01-01T01:20', '2026-01-01T02:40'])),
            'lat': ('obs', [.5, .5, .5]), 'lon': ('obs', [.5, .5, .5]),
            'obs_id': ('obs', ['a', 'b', 'c']),
        },
        attrs={'reader': 'test'},
    )


def test_station_extraction_keeps_native_times_and_compact_forecast_provenance():
    station = extract_station(model(), observations=observations(), variables=['hs'])
    assert station.sizes['time'] == 3
    assert set(station.data_vars) == {'hs'}
    assert set(station.coords) == {'time'}
    table = forecast_table(station)
    assert table.lead_hours.tolist() == [0., 1., 2.]


def test_nearest_time_matching_is_a_separate_operation():
    observed = observations()
    station = extract_station(model(), observations=observed, variables='hs')
    pairs = match_times(observed, station, variable='hs', tolerance='30min')
    assert pairs.sizes['obs'] == 2
    np.testing.assert_equal(pairs.obs_id.values, ['a', 'b'])
    assert set(pairs.data_vars) == {'hs', 'model_hs'}
    assert forecast_table(pairs).lead_hours.tolist() == [0., 1., 2.]
    with pytest.raises(ValueError, match='no observations match'):
        match_times(observed, station, variable='hs', tolerance='1min')
