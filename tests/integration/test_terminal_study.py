"""The distributable example must work outside its directory, including cells."""
from pathlib import Path
import importlib.util
import os
import shutil
import subprocess
import sys
import json
import numpy as np
import pandas as pd
import pytest
import xarray as xr
import yaml

ROOT = Path(__file__).resolve().parents[2]


def study(tmp_path):
    home = tmp_path/'study';home.mkdir()
    shutil.copy2(ROOT/'examples/analyze.py',home/'analyze.py')
    times=pd.date_range('2026-01-20T18',periods=2,freq='h')
    (home/'buoy.csv').write_text('time;hm0\n2026-01-20 18:00:00;8.88\n2026-01-20 19:00:00;6\n')
    for name,offset in [('a',0),('b',1)]:
        xr.Dataset({'hs':(('time','lat','lon'),np.ones((2,2,2))*(6+offset),{'units':'m'})},
                   coords=dict(time=times,lat=[0.,1.],lon=[0.,1.])).to_netcdf(home/f'{name}.nc')
    config=dict(campaign='test',data_root='.',outdir='output',period=['2026-01-20','2026-01-20'],
        region=dict(latmin=0,latmax=1,lonmin=0,lonmax=1),
        datasets=dict(buoy=dict(kind='buoy_ispra',path='buoy.csv',lat=.5,lon=.5),
                      a=dict(kind='netcdf',path='a.nc'),b=dict(kind='netcdf',path='b.nc')),
        comparisons=dict(ba=dict(obs='buoy',model='a',variables=dict(hs={})),
                         bb=dict(obs='buoy',model='b',variables=dict(hs={})),
                         ab=dict(reference='a',model='b',time_basis='valid_time',variables=dict(hs={}))))
    (home/'harry.yaml').write_text(yaml.safe_dump(config));return home


def command(home, cwd, *args):
    env={**os.environ,'PYTHONPATH':str(ROOT/'src'),'MPLCONFIGDIR':str(cwd/'mpl')}
    return subprocess.run([sys.executable,'-m','fieldmatch.cli',*args],cwd=cwd,env=env,text=True,capture_output=True)


def test_whole_sequence_from_unrelated_directory_and_plot_never_reruns(tmp_path):
    pytest.importorskip('matplotlib')
    home=study(tmp_path)
    for args in [('scan',str(home/'harry.yaml')),('run',str(home/'harry.yaml'),'--describe')]:
        result=command(home,tmp_path,*args);assert result.returncode==0,result.stderr+result.stdout
    assert not list((home/'output').glob('*.nc'))
    result=command(home,tmp_path,'run',str(home/'harry.yaml'))
    assert result.returncode==0,result.stderr+result.stdout
    snapshots={p.name:p.read_bytes() for p in (home/'output').glob('*') if p.is_file()}
    script=home/'analyze.py'
    script.write_text(script.read_text().replace("/absolute/path/to/study/harry.yaml",str(home/'harry.yaml')).replace('SHOW = True','SHOW = False'))
    env={**os.environ,'PYTHONPATH':str(ROOT/'src'),'MPLCONFIGDIR':str(tmp_path/'mpl')}
    result=subprocess.run([sys.executable,str(script)],cwd=tmp_path,env=env,text=True,capture_output=True)
    assert result.returncode==0,result.stderr+result.stdout
    assert (home/'output/figures/index.html').exists()
    assert len(list((home/'output/figures').glob('*.png')))==3
    assert not (tmp_path/'output').exists()
    assert snapshots=={p.name:p.read_bytes() for p in (home/'output').glob('*') if p.is_file()}
    from fieldmatch.campaign import load_campaign
    from fieldmatch.results import open_campaign_results
    changed=yaml.safe_load((home/'harry.yaml').read_text());changed['matching_defaults']={'tolerance_minutes':0}
    (home/'other.yaml').write_text(yaml.safe_dump(changed))
    with pytest.raises(ValueError,match='configuration differs'):
        open_campaign_results(load_campaign(home/'other.yaml'))


def test_plain_cells_without_file_or_detection_and_show_without_writes(tmp_path,monkeypatch):
    pytest.importorskip('matplotlib')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    home=study(tmp_path)
    result=command(home,tmp_path,'run',str(home/'harry.yaml'))
    assert result.returncode==0,result.stderr
    script=(home/'analyze.py').read_text().replace('/absolute/path/to/study/harry.yaml',str(home/'harry.yaml')).replace('SAVE = True','SAVE = False')
    assert 'get_ipython' not in script and '__file__' not in script and 'argparse' not in script
    calls=[]
    monkeypatch.setattr(plt,'show',lambda:calls.append(True))
    namespace={'__name__':'__main__'}
    exec(compile(script,'<cells>','exec'),namespace)
    assert calls==[True]
    assert len(namespace['analysis']['figures'])==3
    assert not (home/'output/figures').exists()
    with pytest.raises(ValueError,match='not an exact'):
        namespace['plot'](namespace['campaign'],show=False,save=False,map_time='2026-01-20T18:01')
    plt.close('all')


def test_installer_existing_uses_active_python_and_new_never_updates(tmp_path):
    if os.name=='nt':pytest.skip('Bash helper is optional on Windows')
    fake=tmp_path/'bin';fake.mkdir();log=tmp_path/'calls'
    python=fake/'python';python.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$TEST_INSTALL_LOG"\n');python.chmod(0o755)
    conda=fake/'conda';conda.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$TEST_INSTALL_LOG"\nexit 17\n');conda.chmod(0o755)
    env={**os.environ,'PATH':str(fake)+os.pathsep+os.environ['PATH'],'TEST_INSTALL_LOG':str(log)}
    r=subprocess.run(['bash',str(ROOT/'install.sh'),'--existing'],env=env,cwd=tmp_path,capture_output=True,text=True)
    assert r.returncode==0,r.stderr
    calls=log.read_text();assert 'pip install' in calls and 'fieldmatch.cli doctor' in calls
    log.write_text('')
    r=subprocess.run(['bash',str(ROOT/'install.sh'),'--new','already_exists'],env=env,cwd=tmp_path,capture_output=True,text=True)
    assert r.returncode==17
    assert 'env create' in log.read_text() and 'update' not in log.read_text() and 'prune' not in log.read_text()


def test_help_explains_preview_and_stats_rejects_ignored_option(tmp_path):
    from typer.testing import CliRunner
    from fieldmatch.cli import app
    runner = CliRunner()
    help_text = runner.invoke(app, ['--help'])
    assert help_text.exit_code == 0
    assert '--describe' in help_text.output and 'without computing' in help_text.output
    source = tmp_path/'pairs.csv'
    source.write_text('time,hs,model_hs\n')
    result = runner.invoke(app, ['stats', str(source), '--scatter', '--by-lead'])
    assert result.exit_code != 0 and 'cannot be combined' in result.output
