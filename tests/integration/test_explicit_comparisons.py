import json
import numpy as np
import pandas as pd
import pytest
import xarray as xr
import yaml
from typer.testing import CliRunner
from fieldmatch.cli import app, _open_pairs
from fieldmatch.campaign import load_campaign, validate_output_manifest
from fieldmatch.comparison import resolve_comparison, run_comparisons
from fieldmatch.common import common_sample


def inputs(tmp_path):
    times=pd.to_datetime(['2026-01-01T00:00','2026-01-01T00:30','2026-01-01T01:00'])
    (tmp_path/'obs.csv').write_text('time;hm0;la1WindSpd;la1WindDir\n'
        '2026-01-01 00:00:00;1;5;90\n2026-01-01 00:30:00;8.88;5;90\n2026-01-01 01:00:00;2;5;90\n')
    xr.Dataset({'hs':(('time','lat','lon'),np.array([np.ones((2,2)),np.ones((2,2))*2]), {'valid_min':np.int16(0)}),
                'u10':(('time','lat','lon'),np.array([np.full((2,2),np.nan),np.ones((2,2))*-5])),
                'v10':(('time','lat','lon'),np.array([np.full((2,2),np.nan),np.zeros((2,2))]))},
               coords={'time':times[[0,2]],'lat':[0.,1.],'lon':[0.,1.]}).to_netcdf(tmp_path/'model.nc')
    config={'campaign':'test.v2','period':['2026-01-01','2026-01-01'],
            'region':dict(lonmin=0,lonmax=1,latmin=0,latmax=1),
            'datasets':{'buoy':dict(kind='buoy_ispra',path='obs.csv',lat=.5,lon=.5),
                        'model':dict(kind='netcdf',path='model.nc')},
            'matching_defaults':{'tolerance_minutes':60},
            'comparisons':{'exact':dict(obs='buoy',model='model',variables={'hs':{'tolerance_minutes':0}})}}
    p=tmp_path/'campaign.yaml';p.write_text(yaml.safe_dump(config));return p


def test_batch_does_not_change_single_quantity_and_saves_complete_manifest(tmp_path):
    config=inputs(tmp_path);camp=load_campaign(config)
    specs=[resolve_comparison(camp,'buoy','model',v) for v in ['hs','wind_speed']]
    results,failures=run_comparisons(camp,specs,formats=('csv','netcdf'),emit=lambda _:None)
    assert not failures
    hs=_open_pairs(results[0]['outputs']['csv']); assert hs.sizes['obs']==3
    assert float(hs.hs.max())==8.88
    assert 'wind_speed' not in hs
    saved=hs.copy(deep=True)
    again,errors=run_comparisons(camp,specs[:1],emit=lambda _:None)
    xr.testing.assert_equal(saved.hs,_open_pairs(again[0]['outputs']['csv']).hs)
    assert 'test.v2_buoy_x_model_hs.csv'==results[0]['outputs']['csv'].name
    manifest=json.loads((results[0]['outputs']['csv'].parent/'.fieldmatch'/(results[0]['outputs']['csv'].stem+'.manifest.json')).read_text())
    assert manifest['effective']['matching']['tolerance_minutes']==60
    assert manifest['effective']['reader_options']['lat']==.5
    assert manifest['effective']['observation_attributes']['units']=='m'
    assert manifest['execution_digest'] and manifest['output_sha256']['csv']
    assert manifest['effective']['model_attributes']['hs']['valid_min']==0
    assert validate_output_manifest(results[0]['outputs']['csv'])[0]


def test_named_comparison_and_cli_override_precedence(tmp_path):
    p=inputs(tmp_path);camp=load_campaign(p)
    assert resolve_comparison(camp,comparison='exact')['matching']['tolerance_minutes']==0
    assert resolve_comparison(camp,comparison='exact',matching={'tolerance_minutes':30})['matching']['tolerance_minutes']==30
    runner=CliRunner();r=runner.invoke(app,['compare',str(p),'exact'])
    assert r.exit_code==0,r.output
    result=tmp_path/'fieldmatch_out/test.v2_buoy_x_model_hs_exact.csv'
    assert len(pd.read_csv(result))==2
    r=runner.invoke(app,['compare',str(p),'exact','--describe'])
    assert r.exit_code==0,r.output
    assert 'tolerance minutes' in r.output and 'Preview only' in r.output


def test_explicit_cli_zero_and_missing_variable(tmp_path):
    p=inputs(tmp_path);runner=CliRunner()
    assert runner.invoke(app,['collocate',str(p),'buoy','model']).exit_code!=0
    r=runner.invoke(app,['collocate',str(p),'buoy','model','-v','hs','--tol-minutes','0'])
    assert r.exit_code==0,r.output
    assert len(pd.read_csv(tmp_path/'fieldmatch_out/test.v2_buoy_x_model_hs.csv'))==2


def test_tampered_table_and_effective_spec_are_detected(tmp_path):
    p=inputs(tmp_path);camp=load_campaign(p)
    r,f=run_comparisons(camp,[resolve_comparison(camp,'buoy','model','hs')],emit=lambda _:None)
    path=r[0]['outputs']['csv'];path.write_text(path.read_text()+'\n')
    assert not validate_output_manifest(path)[0]
    assert 'checksum' in validate_output_manifest(path)[1]
    manifest=path.parent/'.fieldmatch'/(path.stem+'.manifest.json');rec=json.loads(manifest.read_text())
    rec['effective']['matching']['tolerance_minutes']=999;manifest.write_text(json.dumps(rec))
    assert 'specification' in validate_output_manifest(path)[1]


def test_common_sample_checks_values_contract_and_reports_counts(tmp_path):
    p=inputs(tmp_path);camp=load_campaign(p)
    r,f=run_comparisons(camp,[resolve_comparison(camp,'buoy','model','hs')],emit=lambda _:None)
    a=_open_pairs(r[0]['outputs']['csv']); b=a.isel(obs=[0,2]).copy(deep=True)
    aligned,counts=common_sample({'a':a,'b':b})
    assert counts['a']['removed']==1 and aligned['a'].sizes['obs']==2
    b.hs.values[0]=99
    with pytest.raises(ValueError,match='conflicting hs'):common_sample({'a':a,'b':b})
    b.attrs['observation_contract']='different'
    with pytest.raises(ValueError,match='contracts'):common_sample({'a':a,'b':b})


@pytest.mark.parametrize('value',[-1,float('nan'),float('inf')])
def test_bad_tolerance_rejected(tmp_path,value):
    with pytest.raises(ValueError,match='nonnegative'):
        resolve_comparison(load_campaign(inputs(tmp_path)),'buoy','model','hs',matching={'tolerance_minutes':value})


def test_grouped_variables_have_independent_rules_and_samples(tmp_path):
    from fieldmatch.comparison import resolve_comparisons
    p=inputs(tmp_path);raw=yaml.safe_load(p.read_text())
    raw['comparisons']['group']=dict(obs='buoy',model='model',variables={
        'hs':{},'wind_speed':{'tolerance_minutes':0,'space_method':'nearest'}})
    p.write_text(yaml.safe_dump(raw));camp=load_campaign(p)
    specs=resolve_comparisons(camp,'group')
    assert specs[0]['matching']['tolerance_minutes']==60
    assert specs[1]['matching']['tolerance_minutes']==0
    with pytest.raises(ValueError,match='select a declared variable'):
        resolve_comparison(camp,comparison='group')
    result=CliRunner().invoke(app,['compare',str(p),'group','--format','both'])
    assert result.exit_code==0,result.output
    hs=_open_pairs(tmp_path/'fieldmatch_out/test.v2_buoy_x_model_hs_group.nc')
    wind=_open_pairs(tmp_path/'fieldmatch_out/test.v2_buoy_x_model_wind_speed_group.nc')
    assert hs.sizes['obs']==3 and float(hs.hs.max())==8.88
    assert wind.sizes['obs']==1 and np.all(wind.dt==0)
    assert json.loads(wind.attrs['effective_comparison'])['matching']['space_method']=='nearest'


@pytest.mark.parametrize('variables',[[],{}, {'hs':None},{'hs':{'tolerence_minutes':0}}, {'hs':{'matching':{}}}])
def test_invalid_variable_configuration_rejected(tmp_path,variables):
    p=inputs(tmp_path);raw=yaml.safe_load(p.read_text())
    raw['comparisons']['exact']['variables']=variables
    p.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValueError):load_campaign(p)


def test_grib_true_degree_spelling_preserves_metadata_and_checks_convention():
    from fieldmatch.quantities import annotate,validate
    a=xr.DataArray([359.,1.],name='mwd',attrs={'units':'Degree true','GRIB_paramId':140230})
    mapped=annotate(a,'mwd').rename('wave_dir')
    validated=validate(mapped,'wave_dir')
    assert validated.attrs['units']=='Degree true'
    np.testing.assert_array_equal(validated,[359.,1.])
    mapped.attrs['direction_convention']='to_north_clockwise'
    with pytest.raises(ValueError,match='direction convention'):validate(mapped,'wave_dir')
    mapped.attrs.update(direction_convention='from_north_clockwise',units='radians')
    with pytest.raises(ValueError,match='incompatible units'):validate(mapped,'wave_dir')
