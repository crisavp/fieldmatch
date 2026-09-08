"""Resolve and execute comparisons once, shared by Python and the CLI."""
import inspect
import json
import re
from pathlib import Path
import numpy as np
import xarray as xr
from .readers import READERS, read_obs
from .models import open_model
from .collocate_track import collocate_track, write_pairs, NoUsableModelValues
from .quantities import definition

MATCHING_DEFAULTS = dict(time_method='nearest', tolerance_minutes=30., time_tie='earlier',
    space_method='bilinear', missing_corners='reject_nonzero_weight',
    direction_resultant_min=1e-10, wind_direction_min_speed=1e-10)
MODEL_DEFAULTS = dict(init=None, init_cycle=None, lead=None, lead_tol=0.)
SAFE_NAME = re.compile(r'[A-Za-z0-9_.-]+')


def validate_matching(options):
    if not isinstance(options, dict) or set(options)-set(MATCHING_DEFAULTS):
        raise ValueError(f'matching options must be drawn from {sorted(MATCHING_DEFAULTS)}')
    choices = dict(time_method={'nearest'}, time_tie={'earlier','later'},
                   space_method={'bilinear','nearest'}, missing_corners={'reject_nonzero_weight'})
    for key, value in options.items():
        if key in choices:
            if value not in choices[key]:
                raise ValueError(f'{key} must be one of {sorted(choices[key])}')
        elif isinstance(value, bool) or not np.isfinite(float(value)) or float(value)<0:
            raise ValueError(f'{key} must be finite and nonnegative')
    if float(options.get('direction_resultant_min', 0)) > 1:
        raise ValueError('direction_resultant_min cannot exceed 1')


def validate_comparisons(comparisons, datasets):
    if not isinstance(comparisons, dict):
        raise ValueError('comparisons must be a mapping')
    from .grid_comparison import GRID_OPTIONS
    for name, spec in comparisons.items():
        if not SAFE_NAME.fullmatch(str(name)) or not isinstance(spec, dict):
            raise ValueError(f'invalid comparison {name!r}')
        grid = 'reference' in spec
        required = {'reference','model','variables'} if grid else {'obs','model','variables'}
        optional = {'forecast_pairing'} if grid else set()
        if not required <= set(spec) or set(spec) - required - optional:
            raise ValueError(f'comparison {name}: requires {sorted(required)}'
                             + (" and optionally forecast_pairing" if grid else ""))
        if grid and spec.get('forecast_pairing') not in {None, 'same_forecast', 'same_valid_time'}:
            raise ValueError("forecast_pairing must be same_forecast or same_valid_time")
        for key in (['reference','model'] if grid else ['obs','model']):
            role = 'model' if grid else key
            if spec[key] not in datasets or datasets[spec[key]].role != role:
                raise ValueError(f'comparison {name}: {key} must name a {role} dataset')
        variables=spec['variables']
        if not isinstance(variables, dict) or not variables:
            raise ValueError(f'comparison {name}: variables must be a nonempty mapping')
        for variable, options in variables.items():
            if not isinstance(variable, str) or not SAFE_NAME.fullmatch(variable):
                raise ValueError(f'invalid variable in {name}')
            validate_matching(options)
            if grid and set(options)-GRID_OPTIONS:
                raise ValueError('grid variables accept spatial settings only; times are exact')


def resolve_comparisons(camp, comparison):
    """Expand a named group into independent, fully resolved quantity specifications."""
    if 'reference' in camp.comparisons[comparison]:
        from .grid_comparison import resolve_grid_comparison
        return [resolve_grid_comparison(camp, comparison, v)
                for v in camp.comparisons[comparison]['variables']]
    return [resolve_comparison(camp, variable=v, comparison=comparison)
            for v in camp.comparisons[comparison]['variables']]


def resolve_comparison(camp, obs=None, model=None, variable=None, *, comparison=None,
                       matching=None, model_options=None, obs_variable=None, model_variable=None):
    """Defaults < campaign < named comparison < explicit call/CLI overrides."""
    from .campaign import MODEL_KINDS
    named = camp.comparisons[comparison] if comparison else {}
    obs, model = obs or named.get('obs'), model or named.get('model')
    variables = named.get('variables', {})
    if variable is None and len(variables) == 1:
        variable = next(iter(variables))
    if comparison and variable not in variables:
        raise ValueError('select a declared variable, or use resolve_comparisons for the whole group')
    if not variable or not SAFE_NAME.fullmatch(variable):
        raise ValueError('select a variable with --variable or a named comparison')
    od, md = camp.get(obs), camp.get(model)
    if od.role != 'obs' or md.role != 'model':
        raise ValueError('comparison requires an observation and a model dataset')
    rules={**MATCHING_DEFAULTS, **camp.matching_defaults, **variables.get(variable,{}), **(matching or {})}
    validate_matching(rules)
    for key in ['tolerance_minutes','direction_resultant_min','wind_direction_min_speed']:
        rules[key]=float(rules[key])
    opts={**MODEL_DEFAULTS, **md.options, **(model_options or {})}
    if opts.get('init') is not None and opts.get('init_cycle') is not None:
        raise ValueError('select either init or init_cycle, not both')
    if not np.isfinite(opts['lead_tol']) or opts['lead_tol']<0:
        raise ValueError('lead_tol must be finite and nonnegative')
    reader_options={k:p.default for k,p in inspect.signature(READERS[od.kind].reader).parameters.items()
                    if k in READERS[od.kind].options and p.default is not inspect.Parameter.empty}
    reader_options.update(od.options)
    oname=obs_variable or variable
    mname=model_variable
    sources=['u10','v10'] if mname is None and variable in {'wind_speed','wind_dir'} else [mname or variable]
    return dict(schema_version=3, campaign=camp.name, comparison=comparison,
                obs_dataset=obs, model_dataset=model, variable=variable,
                quantity=definition(variable), obs_variable=oname, model_variable=mname,
                model_sources=sources, reader_kind=od.kind, reader_options=reader_options,
                model_engine=MODEL_KINDS[md.kind], model_options=opts, matching=rules,
                region=camp.bbox, period=[str(t) for t in camp.period])


def result_stem(camp, spec):
    """Return the stable, concise output stem for one resolved quantity.

    A named comparison already identifies both datasets, while a direct
    collocation has no such name and therefore spells out its two dataset keys.
    The manifest retains the campaign and complete scientific specification.
    """
    variable = spec["variable"]
    if spec.get("comparison"):
        name = f'{spec["comparison"]}__{variable}'
    else:
        name = f'{spec["obs_dataset"]}__{spec["model_dataset"]}__{variable}'
        if spec["model_options"].get("lead") is not None:
            from .models import parse_lead
            lo, hi = parse_lead(spec["model_options"]["lead"])
            name += f'__lead{lo:g}-{hi:g}h'
    return camp.outdir / name


def run_comparisons(campaign, specs, *, formats=('csv',), emit=print):
    """Run resolved specifications independently; return successes and explicit failures.

    The same loaded observations/source view is reused within this finite batch.
    A failed quantity invalidates its own manifest, not another quantity's table.
    """
    from .campaign import (load_campaign, crop_obs, combine_provenance, _file_sha256,
                           write_run_manifest, execution_digest, json_default,
                           manifest_path)
    from . import __version__
    camp=load_campaign(campaign) if isinstance(campaign,(str,Path)) else campaign
    specs = list(specs)
    planned = {}
    for spec in specs:
        stem = result_stem(camp, spec)
        identity = (camp.name, spec.get('comparison'), spec['variable'])
        if stem in planned:
            raise ValueError(f'output-name collision at {stem}: {planned[stem]} and {identity}')
        planned[stem] = identity
        existing = manifest_path(stem)
        if existing.exists():
            try:
                old = json.loads(existing.read_text())
                old_effective = old.get('effective', {})
                old_identity = (old.get('campaign'), old_effective.get('comparison'),
                                old_effective.get('variable'))
                if old_identity != identity:
                    raise ValueError(
                        f'{stem} already belongs to {old_identity}; use a separate '
                        'output folder or a different comparison name')
            except json.JSONDecodeError:
                pass
    implementation = {p.name:_file_sha256(p) for p in Path(__file__).parent.glob("*.py")}
    clouds, models, identities, results, failures = {}, {}, {}, [], []
    for spec in specs:
        if spec.get('kind') == 'grid':
            from .grid_comparison import run_grid_comparison
            result, failure = run_grid_comparison(camp,spec,formats=formats,cache=models,
                                                  identities=identities,emit=emit)
            if result: results.append(result)
            if failure: failures.append(failure)
            continue
        variable=spec['variable']; od=camp.get(spec['obs_dataset']); md=camp.get(spec['model_dataset'])
        stem=result_stem(camp, spec)
        effective={**spec, 'fieldmatch_version':__version__, 'implementation_sha256':implementation}
        emit(f"{od.name} x {md.name}: {variable}; observation={spec['obs_variable']}; "
             f"model sources={', '.join(spec['model_sources'])}")
        emit(f"matching: {json.dumps(spec['matching'], sort_keys=True)}")
        emit(f"reader: {od.kind} {json.dumps(spec['reader_options'])}; "
             f"model view: {json.dumps(spec['model_options'], default=json_default)}")
        write_run_manifest(stem,camp,od.name,md.name,'running',effective=effective)
        try:
            effective['inputs'] = {}
            for label, dataset in [('obs', od), ('model', md)]:
                records=[]
                for filename in dataset.files():
                    if filename not in identities:
                        path=Path(filename)
                        identities[filename]=dict(path=str(path.resolve()),size=path.stat().st_size,
                                                  sha256=_file_sha256(path))
                    records.append(identities[filename])
                effective['inputs'][label]=records
            key=execution_digest(dict(kind=od.kind, files=od.files(), options=spec['reader_options']))
            if key not in clouds:
                pieces=[]
                for filename in od.files():
                    ds=read_obs(od.kind,filename,**spec['reader_options'])
                    if ds is not None:
                        ds=crop_obs(ds,camp.bbox,camp.period)
                        if ds is not None: pieces.append(ds)
                if not pieces:
                    raise NoUsableModelValues(f'no {od.name} observations inside region/period')
                cloud=xr.concat(pieces,dim='obs').sortby('time')
                cloud.attrs=combine_provenance(pieces)
                if len(np.unique(cloud.obs_id.values)) != cloud.sizes['obs']:
                    raise ValueError('duplicate observation IDs across deliveries; select unique files')
                clouds[key]=cloud
            cloud=clouds[key]
            opts={k:v for k,v in spec['model_options'].items() if v is not None}
            rule=spec['matching'];tol=np.timedelta64(round(rule['tolerance_minutes']*60*1e9),'ns')
            mkey=execution_digest(dict(files=md.files(),options=opts,sources=spec['model_sources'],pad=str(tol)))
            if mkey not in models:
                models[mkey]=open_model(md.paths,engine=spec['model_engine'],bbox=camp.bbox,
                    period=camp.period,time_pad=tol,variables=spec['model_sources'],**opts).load()
            mod=models[mkey]
            pair=collocate_track(cloud,mod,variable=variable,obs_variable=spec['obs_variable'],
                model_variable=spec['model_variable'],tol=tol,time_tie=rule['time_tie'],
                space_method=rule['space_method'],direction_resultant_min=rule['direction_resultant_min'],
                wind_direction_min_speed=rule['wind_direction_min_speed'])
            # Separate observation/QC contract from match choices for common-sample checks.
            pair.attrs['observation_contract']=execution_digest(dict(reader=od.kind,
                options=spec['reader_options'],source=spec['obs_variable'],
                filters={k:v for k,v in cloud.attrs.items() if k.endswith('_filter') or k=='land_mask'},
                quantity=pair[variable].attrs.get('quantity'),units=pair[variable].attrs.get('units')))
            effective['reader_provenance']=dict(cloud.attrs)
            effective['observation_attributes']=dict(pair[variable].attrs)
            effective['model_attributes']={s:dict(mod[s].attrs) for s in spec['model_sources']}
            if 'lead_hours' in pair.coords:
                effective['actual_lead_hours']=np.unique(pair.lead_hours.values).tolist()
            pair.attrs['effective_comparison']=json.dumps(effective,sort_keys=True,default=json_default)
            outputs=write_pairs(pair,stem,formats)
            for fmt,ext in [('csv','.csv'),('netcdf','.nc')]:
                if fmt not in formats: Path(f'{stem}{ext}').unlink(missing_ok=True)
            write_run_manifest(stem,camp,od.name,md.name,'complete',effective=effective,
                rows=pair.sizes['obs'],pair_attributes={k:v for k,v in pair.attrs.items() if k != "effective_comparison"},
                outputs={k:str(p) for k,p in outputs.items()},
                output_sha256={k:_file_sha256(p) for k,p in outputs.items()})
            results.append(dict(variable=variable,outputs=outputs,rows=pair.sizes['obs']))
            emit(f"{variable}: {pair.sizes['obs']} accepted / {pair.attrs['n_input']} observations -> {outputs}")
        except Exception as exc:
            write_run_manifest(stem,camp,od.name,md.name,'failed',effective=effective,reason=str(exc))
            failures.append(dict(variable=variable,error=str(exc)))
            emit(f'{variable}: FAILED: {exc}')
    for model in models.values(): model.close()
    return results, failures
