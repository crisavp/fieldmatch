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


def command(home,cwd,*args):
    env={**os.environ,'PYTHONPATH':str(ROOT/'src'),'MPLCONFIGDIR':str(cwd/'mpl')}
    return subprocess.run([sys.executable,str(home/'analyze.py'),*args],cwd=cwd,env=env,text=True,capture_output=True)


def test_whole_sequence_from_unrelated_directory_and_plot_never_reruns(tmp_path):
    pytest.importorskip('matplotlib')
    home=study(tmp_path)
    for action in ['inspect','run']:
        result=command(home,tmp_path,action);assert result.returncode==0,result.stderr+result.stdout
    snapshots={p.name:p.read_bytes() for p in (home/'output').glob('*') if p.is_file()}
    result=command(home,tmp_path,'plot');assert result.returncode==0,result.stderr+result.stdout
    assert (home/'output/figures/index.html').exists()
    assert len(list((home/'output/figures').glob('*.png')))==3
    assert not (tmp_path/'output').exists()
    assert snapshots=={p.name:p.read_bytes() for p in (home/'output').glob('*') if p.is_file()}
    result=command(home,tmp_path,'inspect','--config','harry.yaml');assert result.returncode==0,result.stderr
    result=command(home,tmp_path,'plot','--time','2026-01-20T18:01');assert result.returncode!=0 and 'not an exact' in result.stderr
    changed=yaml.safe_load((home/'harry.yaml').read_text());changed['matching_defaults']={'tolerance_minutes':0}
    (home/'other.yaml').write_text(yaml.safe_dump(changed))
    result=command(home,tmp_path,'plot','--config','other.yaml')
    assert result.returncode!=0 and 'configuration differs' in result.stderr


def test_interactive_path_is_explicit_without_file_or_working_directory(tmp_path):
    home=study(tmp_path)
    setup=(home/'analyze.py').read_text().split('# %% Inspect —')[0]
    # Simulate the first VS Code cell: __name__ is __main__, no __file__, kernel args irrelevant.
    namespace={'__name__':'__main__','get_ipython':lambda:object()}
    exec(compile(setup,'<interactive setup>','exec'),namespace)
    resolve=namespace['config_path']
    for value in [None,'harry.yaml']:
        with pytest.raises(ValueError,match='absolute path'):resolve(value,interactive=True)
    assert resolve(home/'harry.yaml',interactive=True)==home/'harry.yaml'


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
