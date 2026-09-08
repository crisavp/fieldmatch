import numpy as np
import pytest
import xarray as xr
from fieldmatch.models import open_model


def cube(t, value):
    return xr.Dataset({'hs': (('time','lat','lon'), np.full((1,2,2), value, dtype=float))},
                      coords={'time': [np.datetime64(t,'ns')], 'lat':[0.,1.], 'lon':[0.,1.]})


def test_time_partitions_and_complementary_values(tmp_path):
    a=cube('2026-01-01T00',1); b=cube('2026-01-01T01',2)
    a.to_netcdf(tmp_path/'a.nc'); b.to_netcdf(tmp_path/'b.nc')
    out=open_model(str(tmp_path/'*.nc'), engine='netcdf4')
    np.testing.assert_equal(out.hs[:,0,0].values, [1,2])
    b=cube('2026-01-01T00',1); b.hs.values[0,0,0]=np.nan
    b.to_netcdf(tmp_path/'b.nc')
    assert np.isfinite(open_model(str(tmp_path/'*.nc'),engine='netcdf4').hs).all()


def test_conflicting_overlap_is_an_error(tmp_path):
    for n,v in [('a',1),('b',2)]: cube('2026-01-01',v).to_netcdf(tmp_path/f'{n}.nc')
    with pytest.raises(ValueError,match='conflict'):
        open_model(str(tmp_path/'*.nc'),engine='netcdf4')


def test_scalar_step_uses_valid_time_and_lead(tmp_path):
    ds=cube('2026-01-01T00',1).assign_coords(step=np.timedelta64(6,'h'),
        valid_time=('time',np.array(['2026-01-01T06'],dtype='datetime64[ns]')))
    ds.to_netcdf(tmp_path/'scalar.nc')
    out=open_model(tmp_path/'scalar.nc',engine='netcdf4')
    assert out.time.values[0]==np.datetime64('2026-01-01T06')
    assert out.init.values[0]==np.datetime64('2026-01-01T00')
    assert out.lead_hours.values[0]==6


def test_zero_step_time_series_is_an_analysis_not_a_forecast(tmp_path):
    ds=xr.concat([cube('2026-01-01T00',1),cube('2026-01-01T06',2)],dim='time')
    ds=ds.assign_coords(step=np.timedelta64(0,'h'),valid_time=ds.time)
    path=tmp_path/'analysis.nc';ds.to_netcdf(path)
    out=open_model(path,engine='netcdf4')
    assert out.attrs['fieldmatch_time_kind']=='valid_time_only'


def test_inconsistent_valid_time_is_refused(tmp_path):
    ds=cube('2026-01-01T00',1).assign_coords(step=np.timedelta64(6,'h'),
        valid_time=('time',np.array(['2026-01-01T07'],dtype='datetime64[ns]')))
    ds.to_netcdf(tmp_path/'bad.nc')
    with pytest.raises(ValueError,match='valid_time'):
        open_model(tmp_path/'bad.nc',engine='netcdf4')


def test_conflicting_component_provenance_is_refused(tmp_path):
    for n,init,lead in [('u10','2026-01-01T00',6),('v10','2026-01-01T06',0)]:
        ds=cube('2026-01-01T06',1).rename(hs=n).assign_coords(
            init=('time',[np.datetime64(init,'ns')]),lead_hours=('time',[lead]))
        ds.to_netcdf(tmp_path/f'{n}.nc')
    with pytest.raises(ValueError,match='provenance'):
        open_model(str(tmp_path/'*.nc'),engine='netcdf4')


def test_incompatible_grids_are_refused(tmp_path):
    cube('2026-01-01',1).to_netcdf(tmp_path/'a.nc')
    cube('2026-01-02',2).assign_coords(lon=[0,2]).to_netcdf(tmp_path/'b.nc')
    with pytest.raises(ValueError,match='grid'):
        open_model(str(tmp_path/'*.nc'),engine='netcdf4')


def test_forecast_overlap_is_always_refused(tmp_path):
    t=np.array(['2026-01-01T00','2026-01-01T06'],dtype='datetime64[ns]')
    step=np.array([0,6],dtype='timedelta64[h]')
    a=np.broadcast_to(np.array([[1,2],[3,4]])[:,:,None,None],(2,2,2,2)).copy()
    ds=xr.Dataset({'hs':(('time','step','lat','lon'),a)},
                  coords={'time':t,'step':step,'lat':[0.,1.],'lon':[0.,1.]})
    p=tmp_path/'forecast.nc';ds.to_netcdf(p)
    with pytest.raises(ValueError,match='duplicate valid time'):
        open_model(p,engine='netcdf4',lead='0-6')
    with pytest.raises(ValueError,match='no selected'):
        open_model(p,engine='netcdf4',lead=3)
    out=open_model(p,engine='netcdf4',lead=3,lead_tol=3)
    np.testing.assert_equal(out.lead_hours.values,[0,0])


def test_init_and_lead_are_independent_and_cycles_select_recurring_runs(tmp_path):
    inits=np.array(['2026-01-01T00','2026-01-01T12','2026-01-02T00','2026-01-02T12'],
                   dtype='datetime64[ns]')
    steps=np.array([12,24,36],dtype='timedelta64[h]')
    values=np.arange(12,dtype=float).reshape(4,3,1,1)
    ds=xr.Dataset({'hs':(('time','step','lat','lon'),np.broadcast_to(values,(4,3,2,2)).copy(),{'units':'m'})},
                  coords={'time':inits,'step':steps,'lat':[0.,1.],'lon':[0.,1.]})
    p=tmp_path/'forecast.nc';ds.to_netcdf(p)

    one=open_model(p,engine='netcdf4',init='2026-01-02T00',lead='12-24')
    np.testing.assert_equal(one.init.values, np.repeat(np.datetime64('2026-01-02T00','ns'),2))
    np.testing.assert_equal(one.lead_hours.values,[12,24])

    midnight_24=open_model(p,engine='netcdf4',init_cycle='00:00',lead=24)
    noon_12=open_model(p,engine='netcdf4',init_cycle='12:00',lead=12)
    np.testing.assert_equal(midnight_24.time.values,noon_12.time.values)
    np.testing.assert_equal(midnight_24.lead_hours.values,[24,24])
    np.testing.assert_equal(noon_12.lead_hours.values,[12,12])
    from fieldmatch.grids import compare_grids
    with pytest.raises(ValueError,match='forecast_pairing'):
        compare_grids(midnight_24,noon_12,'hs',space_method='bilinear')
    with pytest.raises(ValueError,match='equal initialization and lead'):
        compare_grids(midnight_24,noon_12,'hs',space_method='bilinear',
                      forecast_pairing='same_forecast')
    compared=compare_grids(midnight_24,noon_12,'hs',space_method='bilinear',
                           forecast_pairing='same_valid_time')
    assert set(compared.coords)=={'time','lat','lon'}

    with pytest.raises(ValueError,match='duplicate valid time'):
        open_model(p,engine='netcdf4',init_cycle='00:00',lead='12-36')
    with pytest.raises(ValueError,match='no selected'):
        open_model(p,engine='netcdf4',init='2026-01-03T00',lead=24)
    with pytest.raises(ValueError,match='init_cycle'):
        open_model(p,engine='netcdf4',init_cycle='24:00',lead=24)
    with pytest.raises(ValueError,match='either init or init_cycle'):
        open_model(p,engine='netcdf4',init='2026-01-01T00',init_cycle='00:00',lead=24)


def test_renaming_does_not_erase_incompatible_period_identity(tmp_path):
    ds=cube('2026-01-01',6).rename(hs='mwp');p=tmp_path/'period.nc';ds.to_netcdf(p)
    out=open_model(p,engine='netcdf4',rename={'mwp':'tm01'})
    assert out.tm01.attrs['quantity']=='energy_period'


def test_same_quantity_files_cannot_mix_units(tmp_path):
    a=cube('2026-01-01',1);b=cube('2026-01-02',100)
    a.hs.attrs['units']='m';b.hs.attrs['units']='cm'
    a.to_netcdf(tmp_path/'a.nc');b.to_netcdf(tmp_path/'b.nc')
    with pytest.raises(ValueError,match='units'):
        open_model(str(tmp_path/'*.nc'),engine='netcdf4')
