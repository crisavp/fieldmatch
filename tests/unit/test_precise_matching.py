import numpy as np
import pytest
import xarray as xr
from fieldmatch.collocate_track import collocate_track


def cube(**fields):
    return xr.Dataset({k:(('time','lat','lon'),np.array(v,float)[None]) for k,v in fields.items()},
                      coords={'time':[np.datetime64('2026-01-01','ns')],'lat':[0.,1.],'lon':[0.,1.]})


def obs(**fields):
    return xr.Dataset({k:('obs',[v]) for k,v in fields.items()},coords={
        'time':('obs',[np.datetime64('2026-01-01','ns')]),'lat':('obs',[.5]),'lon':('obs',[.5])})


def test_exact_wet_node_ignores_zero_weight_nan():
    a=obs(hs=1).assign_coords(lat=('obs',[0.]),lon=('obs',[0.]))
    p=collocate_track(a,cube(hs=[[1,np.nan],[np.nan,np.nan]]),variable='hs')
    assert p.model_hs.item()==1


def test_opposing_directions_are_undefined():
    from fieldmatch.collocate_track import NoUsableModelValues
    with pytest.raises(NoUsableModelValues):
        collocate_track(obs(wave_dir=0),cube(mwd=[[0,180],[0,180]]),
                        variable='wave_dir',model_variable='mwd')


def test_cancelled_wind_still_has_a_speed_pair():
    m=cube(u10=[[1,-1],[1,-1]],v10=[[0,0],[0,0]])
    assert collocate_track(obs(wind_speed=0),m,variable='wind_speed').model_wind_speed.item()==0


def test_mwp_is_not_tm01_even_with_a_source_override():
    with pytest.raises(ValueError,match='incompatible quantities'):
        collocate_track(obs(tm01=5),cube(mwp=[[5,5],[5,5]]),variable='tm01',model_variable='mwp')


def test_no_fallback_to_unobserved_fields():
    with pytest.raises(ValueError,match='variable'):
        collocate_track(obs(hs=1),cube(tp=[[1,1],[1,1]]))


def test_explicit_zero_tolerance_and_tie():
    m=cube(hs=[[1,1],[1,1]])
    second=m.assign_coords(time=[np.datetime64('2026-01-01T01','ns')]);second['hs']=second.hs+1
    m=xr.concat([m,second],dim='time')
    a=obs(hs=1).assign_coords(time=('obs',[np.datetime64('2026-01-01T00:30','ns')]))
    assert collocate_track(a,m,variable='hs',time_tie='earlier').model_hs.item()==1
    assert collocate_track(a,m,variable='hs',time_tie='later').model_hs.item()==2


def test_one_quantity_has_no_unrelated_columns():
    p=collocate_track(obs(hs=1,wind_speed=10),cube(hs=[[1,1],[1,1]]),variable='hs')
    assert 'wind_speed' not in p


def test_units_are_checked():
    m=cube(hs=[[1,1],[1,1]]);m.hs.attrs['units']='cm'
    with pytest.raises(ValueError,match='units'):
        collocate_track(obs(hs=1),m,variable='hs')
