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


def open_campaign_results(campaign):
    """Load only this campaign's declared quantities; validate each saved result."""
    records = {}
    for file in campaign.outdir.glob('*.manifest.json'):
        record = json.loads(file.read_text())
        effective = record.get('effective', {})
        if effective.get('campaign') != campaign.name:
            continue
        key = (effective.get('comparison'), effective.get('variable'))
        if key in records:
            raise ValueError(f'Multiple result manifests for {key}; use a separate output folder per study.')
        records[key] = record
    loaded = {}
    for name, declaration in campaign.comparisons.items():
        for variable in declaration['variables']:
            record = records.get((name, variable))
            if record is None or record['status'] != 'complete':
                raise ValueError(f'No complete {name}/{variable} result. Run comparisons first.')
            # Validate against the currently selected campaign too, not just the
            # campaign path embedded in an output made with a different YAML.
            from fieldmatch.campaign import pair_digest
            first = declaration.get('obs', declaration.get('reference'))
            if record.get('pair_digest') != pair_digest(campaign, first, declaration['model']):
                raise ValueError(f'{name}/{variable}: current configuration differs; rerun comparisons.')
            output = record.get('outputs', {}).get('netcdf')
            if output is None:
                raise ValueError(f'{name}/{variable} needs NetCDF; run with both formats.')
            loaded[(name, variable)] = open_result(output)
    if not loaded:
        raise ValueError('No declared results to plot.')
    return loaded

