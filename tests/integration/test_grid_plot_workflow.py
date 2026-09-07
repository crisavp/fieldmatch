import json
import numpy as np
import pandas as pd
import pytest
import xarray as xr
import yaml
from typer.testing import CliRunner
from fieldmatch.cli import app
from fieldmatch.results import open_result
from fieldmatch.campaign import validate_output_manifest,load_campaign
from fieldmatch.comparison import resolve_comparisons


def campaign(tmp_path):
    for name,bias in [('ref',0),('other',2)]:
        xr.Dataset({'hs':(('time','lat','lon'),np.arange(8).reshape(2,2,2)+bias,{'units':'m'})},
            coords={'time':pd.to_datetime(['2026-01-01','2026-01-01T06:00'],format='mixed'),'lat':[0.,1.],'lon':[0.,1.]}).to_netcdf(tmp_path/f'{name}.nc')
    c=dict(campaign='grid.test',region=dict(latmin=0,latmax=1,lonmin=0,lonmax=1),period=['2026-01-01','2026-01-01'],
           datasets={n:dict(kind='netcdf',path=f'{n}.nc') for n in ['ref','other']},
           matching_defaults=dict(tolerance_minutes=30),
           comparisons={'difference':dict(reference='ref',model='other',time_basis='valid_time',variables={'hs':{}})})
    p=tmp_path/'campaign.yaml';p.write_text(yaml.safe_dump(c));return p


def test_cli_grid_output_roundtrip_and_manifest(tmp_path):
    p=campaign(tmp_path);runner=CliRunner()
    r=runner.invoke(app,['compare',str(p),'difference','--describe']);assert r.exit_code==0,r.output
    assert 'exact' in r.output and 'tolerance minutes' not in r.output
    r=runner.invoke(app,['compare',str(p),'difference','--format','both']);assert r.exit_code==0,r.output
    path=tmp_path/'fieldmatch_out/grid.test_ref_x_other_hs_difference.nc'
    ds=open_result(path);np.testing.assert_allclose(ds.difference,2)
    assert validate_output_manifest(path)[0]
    info = runner.invoke(app, ['info', str(path)])
    assert info.exit_code == 0 and 'passed available checks' in info.output
    manifest=json.loads((path.parent/'.fieldmatch'/(path.stem+'.manifest.json')).read_text())
    assert manifest['reference_dataset']=='ref' and 'obs_dataset' not in manifest
    assert manifest['effective']['inputs']['reference'][0]['sha256']
    assert pd.read_csv(path.with_suffix('.csv')).rms_difference.tolist()==[2,2]
    with pytest.raises(ValueError,match='summaries'):open_result(path.with_suffix('.csv'))


def test_reject_grid_time_tolerance(tmp_path):
    p=campaign(tmp_path);c=yaml.safe_load(p.read_text());c['comparisons']['difference']['variables']['hs']['tolerance_minutes']=10
    p.write_text(yaml.safe_dump(c))
    with pytest.raises(ValueError,match='spatial settings only'):load_campaign(p)


def test_plotting_preserves_data_uses_exact_time_and_records_provenance(tmp_path):
    matplotlib = pytest.importorskip('matplotlib')
    matplotlib.use('Agg')
    from fieldmatch import plotting
    import matplotlib.pyplot as plt
    p=campaign(tmp_path);r=CliRunner().invoke(app,['compare',str(p),'difference']);assert r.exit_code==0,r.output
    ds=open_result(tmp_path/'fieldmatch_out/grid.test_ref_x_other_hs_difference.nc');before=ds.copy(deep=True)
    fig,axes=plotting.comparison_panels(ds,'2026-01-01',clim=(0,10),difference_limit=3)
    path=plotting.save_figure(fig,tmp_path/'panels.png')
    assert path.exists();rec=json.loads((tmp_path/'.fieldmatch/panels.png.figure.json').read_text())
    info = CliRunner().invoke(app, ['info', str(path)])
    assert info.exit_code == 0 and 'checksum matches' in info.output
    assert len(rec['plots'])==3 and rec['plots'][0]['comparison']['result_sha256']
    assert axes[0].collections[0].get_clim()==axes[1].collections[0].get_clim()
    assert axes[2].collections[0].get_clim()==(-3,3)
    xr.testing.assert_identical(ds,before);plt.close(fig)
    with pytest.raises(ValueError,match='exact comparison time'):plotting.field_map(ds,'2026-01-01T00:01')
    # Figure generation must not rematch or silently intersect different observation samples.
    pair=xr.Dataset({'hs':('obs',[1.,2.],{'units':'m'}),'model_hs':('obs',[1.2,1.8]),
        'obs_id':('obs',['a','b']),'time':('obs',pd.to_datetime(['2026-01-01','2026-01-02'])),
        'lat':('obs',[.5,.5]),'lon':('obs',[.5,.5])},attrs={'variable':'hs'})
    saved=pair.copy(deep=True)
    with pytest.raises(ValueError,match='common_sample'):plotting.time_series({'a':pair,'b':pair.isel(obs=[0])})
    fig,ax=plotting.time_series({'model':pair});assert ax.lines[0].get_linestyle()=='None';plt.close(fig)
    fig,ax=plotting.scatter(pair);plt.close(fig);xr.testing.assert_identical(pair,saved)


def test_grid_statistics_cli_and_stale_result_rejection(tmp_path):
    p=campaign(tmp_path);runner=CliRunner()
    r=runner.invoke(app,['compare',str(p),'difference','--format','both']);assert r.exit_code==0,r.output
    path=tmp_path/'fieldmatch_out/grid.test_ref_x_other_hs_difference.nc'
    r=runner.invoke(app,['stats',str(path)]);assert r.exit_code==0,r.output
    assert 'rms_difference' in r.output
    r=runner.invoke(app,['stats',str(path.with_suffix('.csv'))]);assert r.exit_code!=0
    with path.open('ab') as f:f.write(b'tampered')
    with pytest.raises(ValueError,match='checksum'):open_result(path)
