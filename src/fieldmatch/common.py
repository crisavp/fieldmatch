"""Align finite pairs on identical observations; analysis choices stay with callers."""
import numpy as np
from .quantities import validate


def common_sample(tables):
    """Return (aligned tables, counts) for {model_name: pair Dataset}.

    Requires stable observation IDs, one quantity and identical observation/QC
    contracts. It does not choose event windows or equalize forecast lead:
    apply those explicit scientific restrictions before calling this function.
    """
    if not tables:
        raise ValueError('provide at least one pair table')
    variables={ds.attrs.get('variable') for ds in tables.values()}
    quantities={ds.attrs.get('quantity') for ds in tables.values()}
    contracts={ds.attrs.get('observation_contract') for ds in tables.values()}
    if len(variables)!=1 or None in variables or len(quantities)!=1 or None in quantities:
        raise ValueError('common samples require the same declared variable and quantity')
    if None in contracts or len(contracts)!=1:
        raise ValueError('common samples require matching, explicit observation/QC contracts')
    variable=next(iter(variables)); selected={}
    for name,ds in tables.items():
        validate(ds[variable], variable)
        if 'obs_id' not in ds or len(np.unique(ds.obs_id))!=ds.sizes['obs']:
            raise ValueError(f'{name}: stable unique obs_id values are required')
        valid=np.isfinite(ds[variable]) & np.isfinite(ds[f'model_{variable}'])
        selected[name]=ds.isel(obs=np.flatnonzero(valid))
    first=next(iter(selected.values())); ids=first.obs_id.values
    for ds in selected.values(): ids=ids[np.isin(ids,ds.obs_id.values)]
    aligned={};counts={}
    for name,ds in selected.items():
        lookup={v:i for i,v in enumerate(ds.obs_id.values)}
        aligned[name]=ds.isel(obs=[lookup[v] for v in ids])
        counts[name]=dict(input=tables[name].sizes['obs'],finite=ds.sizes['obs'],common=len(ids),
                          removed=tables[name].sizes['obs']-len(ids))
    reference=next(iter(aligned.values()))
    for name,ds in aligned.items():
        for column in ('time','lat','lon',variable):
            if not np.array_equal(ds[column].values,reference[column].values):
                raise ValueError(f'{name}: same observation IDs have conflicting {column} values')
    return aligned,counts
