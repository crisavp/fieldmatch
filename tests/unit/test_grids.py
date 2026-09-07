import numpy as np
import pandas as pd
import pytest
import xarray as xr
from fieldmatch.grids import compare_grids,grid_stats


def cube(lat=(0.,1.),lon=(0.,1.),times=('2026-01-01','2026-01-01T06'),name='hs',units='m'):
    y,x=np.meshgrid(lat,lon,indexing='ij')
    return xr.Dataset({name:(('time','lat','lon'),np.broadcast_to(2*y+3*x,(len(times),len(lat),len(lon))).copy(),{'units':units})},
                      coords=dict(time=pd.to_datetime(list(times),format='mixed'),lat=list(lat),lon=list(lon)))


def compare(a,b,v='hs',**kw):
    return compare_grids(a,b,v,space_method=kw.pop('space_method','bilinear'),time_basis=kw.pop('time_basis','valid_time'),**kw)


def test_planar_field_exact_regridding_and_difference_sign():
    a=cube(lat=(.25,.75),lon=(.25,.75));b=cube();b.hs.values+=2
    result=compare(a,b)
    np.testing.assert_allclose(result.difference,2)
    np.testing.assert_allclose(result.reference,a.hs)
    assert result.n_common.values.tolist()==[4,4]
    stats=grid_stats(result)
    np.testing.assert_allclose(stats.mean_difference,2);np.testing.assert_allclose(stats.rms_difference,2)
    assert result.attrs['time_method']=='exact'


def test_no_temporal_nearest_fallback_and_forecast_basis():
    a=cube();b=cube(times=('2026-01-01T00:01','2026-01-01T06'))
    a=a.assign_coords(init=('time',pd.to_datetime(['2025-12-31','2025-12-31'])),lead_hours=('time',[24.,30.]))
    b=b.assign_coords(init=('time',pd.to_datetime(['2026-01-01','2026-01-01'])),lead_hours=('time',[1/60,6.]))
    ds=compare(a,b)
    assert ds.sizes['time']==1 and ds.candidate_lead_hours.item()==6
    for basis in ['same_init','same_lead']:
        with pytest.raises(ValueError,match='no exact common'):compare(a,b,time_basis=basis)
    b=b.assign_coords(init=('time',pd.to_datetime(['2025-12-31','2025-12-31'])),lead_hours=('time',[24+1/60,30.]))
    for basis in ['same_init','same_lead']:assert compare(a,b,time_basis=basis).sizes['time']==1
    with pytest.raises(ValueError,match='requires a init'):compare(cube(),b,time_basis='same_init')


def test_masks_exact_wet_nodes_extrapolation_and_zero_common_time():
    a=cube(lat=(0.,.5,1.,1.5),lon=(0.,.5,1.,1.5));b=cube()
    b.hs.values[:,1,1]=np.nan
    b.hs.values[1]=np.nan
    ds=compare(a,b)
    assert ds.valid.sel(time=ds.time[0],lat=0,lon=0).item()==1
    assert ds.valid.sel(time=ds.time[0],lat=.5,lon=.5).item()==0
    assert not ds.valid.sel(lat=1.5).any()
    assert ds.n_common[1]==0 and np.isnan(grid_stats(ds).rms_difference[1])
    np.testing.assert_array_equal(np.isfinite(ds.difference),ds.valid==1)


def test_circular_seam_cancellation_units_and_wind_components():
    a=cube(lat=(.5,1.),lon=(.5,1.),name='wave_dir',units='degrees');a.wave_dir.values[:]=350
    b=cube(name='mwd',units='Degree true');b.mwd.values[:]=10
    b=b.rename(mwd='wave_dir')
    ds=compare(a,b,'wave_dir');np.testing.assert_allclose(ds.difference,20,atol=1e-12)
    b.wave_dir.values[:]=[[90,270],[90,270]]
    ds=compare(a,b,'wave_dir');assert ds.valid.sel(lat=.5,lon=.5).sum()==0
    b.wave_dir.attrs['units']='radians'
    with pytest.raises(ValueError,match='units'):compare(a,b,'wave_dir')
    # Wind interpolates components before speed; cancellation does not become strong wind.
    a=cube(lat=(.5,1.),lon=(.5,1.)).rename(hs='u10');a.u10.attrs['units']='m s-1';a['v10']=xr.zeros_like(a.u10);a.v10.attrs['units']='m s-1'
    b=cube().rename(hs='u10');b.u10.attrs['units']='m s-1';b.u10.values[:]=[[-1,1],[-1,1]]
    b['v10']=xr.zeros_like(b.u10);b.v10.attrs['units']='m s-1'
    speed=compare(a,b,'wind_speed');assert speed.candidate.sel(lat=.5,lon=.5).max()==0
    direction=compare(a,b,'wind_dir');assert not direction.valid.sel(lat=.5,lon=.5).any()


def test_nearest_and_bilinear_are_explicit_distinct_choices():
    a=cube(lat=(.25,.75),lon=(.25,.75));b=cube()
    bilinear=compare(a,b);nearest=compare(a,b,space_method='nearest')
    assert float(abs(bilinear.difference).max())==0
    assert float(abs(nearest.difference).max())>0
    with pytest.raises(ValueError):compare(a,b,space_method='spline')


def test_unknown_units_and_bad_axes_rejected():
    a=cube(name='custom',units='K');b=cube(name='custom',units='C')
    with pytest.raises(ValueError,match='units'):compare(a,b,'custom')
    b=cube().isel(time=[1,0])
    with pytest.raises(ValueError,match='time'):compare(cube(),b)
    b=cube().assign_coords(lon=[0,0])
    with pytest.raises(ValueError,match='lon'):compare(cube(),b)


def test_area_weighting_uses_cell_area_and_common_mask():
    a=cube(lat=(0.,60.));b=a.copy(deep=True);b.hs.values[:]=a.hs.values+np.array([[0,0],[3,3]])
    ds=compare(a,b);stats=grid_stats(ds)
    # midpoint cells: latitude edges [-30,30,90] -> relative areas 1 and .5
    np.testing.assert_allclose(stats.mean_difference,1)
    np.testing.assert_allclose(stats.rms_difference,np.sqrt(3))
