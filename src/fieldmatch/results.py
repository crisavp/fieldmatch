"""Read portable results with provenance checks before analysis or plotting."""
import json
import warnings
from pathlib import Path
import pandas as pd
import xarray as xr
from .campaign import validate_output_manifest, manifest_path, _file_sha256


def open_result(path):
    """Load NetCDF or observation-pair CSV; grid summary CSV is not a field cube."""
    path = Path(path)
    ok, reason, warning = validate_output_manifest(path)
    if not ok:
        raise ValueError(reason)
    if warning:
        warnings.warn(warning, stacklevel=2)
    sidecar=manifest_path(path.with_suffix(''))
    record=json.loads(sidecar.read_text()) if sidecar.exists() else {}
    if path.suffix.lower() in {'.nc','.netcdf'}:
        with xr.open_dataset(path) as source:
            ds=source.load()
    elif path.suffix.lower()=='.csv':
        if record.get('comparison_kind')=='grid':
            raise ValueError('grid CSV contains spatial summaries; open its NetCDF for field plots')
        frame=pd.read_csv(path)
        for name in ('time','init','model_time'):
            if name in frame:frame[name]=pd.to_datetime(frame[name],errors='raise')
        ds=xr.Dataset({c:('obs',frame[c].to_numpy()) for c in frame})
        ds.attrs.update(record.get('pair_attributes',{}))
        v=ds.attrs.get('variable')
        for name in (v,f'model_{v}'):
            if name in ds:ds[name].attrs.update(record.get('effective',{}).get('observation_attributes',{}))
        if 'effective' in record:
            ds.attrs['effective_comparison']=json.dumps(record['effective'],sort_keys=True)
    else:
        raise ValueError('result must be NetCDF or CSV')
    ds.attrs['result_source']=str(path.resolve())
    ds.attrs['result_sha256']=_file_sha256(path)
    return ds
