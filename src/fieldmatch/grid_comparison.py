"""Campaign adapter for the grid comparison core; shares output manifests."""
import json
from pathlib import Path
import numpy as np
from .grids import compare_grids, grid_stats, TIME_BASES
from .models import open_model
from .campaign import MODEL_KINDS, _file_sha256, execution_digest, write_run_manifest, json_default
from .quantities import definition

GRID_OPTIONS = {'space_method','missing_corners','direction_resultant_min','wind_direction_min_speed'}


def resolve_grid_comparison(camp, name, variable):
    from .comparison import MATCHING_DEFAULTS, MODEL_DEFAULTS, validate_matching
    declared = camp.comparisons[name]
    rules = {k:v for k,v in {**MATCHING_DEFAULTS, **camp.matching_defaults}.items() if k in GRID_OPTIONS}
    rules.update(declared['variables'][variable])
    validate_matching(rules)
    for key in ('direction_resultant_min','wind_direction_min_speed'):
        rules[key] = float(rules[key])
    options = {}
    for label,key in [('reference','reference'),('candidate','model')]:
        options[label] = {**MODEL_DEFAULTS, **camp.get(declared[key]).options}
        if options[label]['lead'] is not None:
            options[label]['init'] = None
    return dict(schema_version=3, kind='grid', campaign=camp.name, comparison=name,
        variable=variable, quantity=definition(variable), reference_dataset=declared['reference'],
        model_dataset=declared['model'], target_grid=declared['reference'],
        time_basis=declared['time_basis'], time_method='exact', matching=rules,
        model_options=options, mask_policy='common_finite_per_time',
        difference_sign='candidate minus reference', region=camp.bbox,
        period=[str(t) for t in camp.period])


def run_grid_comparison(camp, spec, *, formats, cache, identities, emit):
    """NetCDF holds fields and mask; CSV holds per-time area-weighted differences."""
    from . import __version__
    if not formats or set(formats)-{'csv','netcdf'}:
        raise ValueError('formats must contain csv and/or netcdf')
    variable=spec['variable'];ref=spec['reference_dataset'];model=spec['model_dataset']
    stem=camp.outdir/f'{camp.name}_{ref}_x_{model}_{variable}_{spec["comparison"]}'
    effective={**spec, 'fieldmatch_version':__version__,
        'implementation_sha256':{p.name:_file_sha256(p) for p in Path(__file__).parent.glob('*.py')}}
    write_run_manifest(stem,camp,ref,model,'running',effective=effective,comparison_kind='grid')
    emit(f'{model} minus {ref}: {variable}; grid={ref}; exact times; basis={spec["time_basis"]}')
    emit(f'matching: {json.dumps(spec["matching"], sort_keys=True)}')
    try:
        datasets=[];effective['inputs']={};effective['source_grids']={}
        sources=['u10','v10'] if variable in {'wind_speed','wind_dir'} else [variable]
        for label,name in [('reference',ref),('candidate',model)]:
            d=camp.get(name);files=d.files();records=[]
            for filename in files:
                if filename not in identities:
                    p=Path(filename);identities[filename]=dict(path=str(p.resolve()),size=p.stat().st_size,sha256=_file_sha256(p))
                records.append(identities[filename])
            effective['inputs'][label]=records
            opts={k:v for k,v in spec['model_options'][label].items() if v is not None}
            key=execution_digest(dict(kind='grid',files=files,sources=sources,options=opts))
            if key not in cache:
                cache[key]=open_model(files,engine=MODEL_KINDS[d.kind],variables=sources,
                    bbox=camp.bbox,period=camp.period,time_pad=np.timedelta64(0,'s'),**opts).load()
            ds=cache[key];datasets.append(ds)
            effective['source_grids'][label]={a:ds[a].values.tolist() for a in ['lat','lon']}
        rules=spec['matching']
        pair=compare_grids(*datasets,variable,space_method=rules['space_method'],
            time_basis=spec['time_basis'],reference_name=ref,candidate_name=model,
            direction_resultant_min=rules['direction_resultant_min'],
            wind_direction_min_speed=rules['wind_direction_min_speed'])
        effective['source_attributes']=json.loads(pair.attrs['source_attributes'])
        pair.attrs['effective_comparison']=json.dumps(effective,sort_keys=True,default=json_default)
        outputs={}
        # Atomic files; a failed manifest prevents older files being consumed as new results.
        for fmt,ext in [('netcdf','.nc'),('csv','.csv')]:
            target=Path(f'{stem}{ext}')
            if fmt not in formats:
                target.unlink(missing_ok=True);continue
            temp=target.with_name('.'+target.name+'.tmp')
            try:
                if fmt=='netcdf':
                    pair.to_netcdf(temp,encoding={v:dict(zlib=True,complevel=4) for v in ('reference','candidate','difference','valid')})
                else:
                    grid_stats(pair).to_dataframe().to_csv(temp,float_format='%.17g')
                temp.replace(target)
            finally:
                temp.unlink(missing_ok=True)
            outputs[fmt]=target
        write_run_manifest(stem,camp,ref,model,'complete',effective=effective,comparison_kind='grid',
            reference_dataset=ref,times=pair.sizes['time'],common_cells=int(pair.valid.sum()),
            outputs={k:str(p) for k,p in outputs.items()},output_sha256={k:_file_sha256(p) for k,p in outputs.items()})
        emit(f'{variable}: {pair.sizes["time"]} times; {int(pair.valid.sum())} common time/cell pairs -> {outputs}')
        return dict(variable=variable,outputs=outputs,times=pair.sizes['time']),None
    except Exception as exc:
        write_run_manifest(stem,camp,ref,model,'failed',effective=effective,comparison_kind='grid',reason=str(exc))
        emit(f'{variable}: FAILED: {exc}')
        return None,dict(variable=variable,error=str(exc))
