"""Optional Matplotlib figures from prepared results; no matching or regridding.

Functions return figures/axes for ordinary Matplotlib customization. Multiple
model time series must already use identical observations. Map timestamps must
exist exactly. Saving with save_figure also writes a provenance JSON sidecar.
"""
import json
from pathlib import Path
import numpy as np
from .quantities import DIRECTION_VARS, definition


def _axes(ax, figsize=(7,4)):
    import matplotlib.pyplot as plt
    if ax is None:
        fig,ax=plt.subplots(figsize=figsize,constrained_layout=True)
    return ax.figure,ax


def _record(fig, kind, ds, **settings):
    from .campaign import json_default
    record={'plot':kind,'settings':settings,'comparison':dict(ds.attrs)}
    records=getattr(fig,'_fieldmatch_records',[])
    records.append(json.loads(json.dumps(record,default=json_default)))
    fig._fieldmatch_records=records


def _pair(ds):
    if ds.attrs.get('comparison_kind')=='grid' or 'variable' not in ds.attrs:
        raise ValueError('plot requires a prepared single-quantity observation/model result')
    v=ds.attrs['variable']
    if v not in ds or f'model_{v}' not in ds or ds[v].dims!=('obs',):
        raise ValueError('result must contain one observation variable and its model partner')
    return v,ds[v].attrs.get('units','')


def field_map(ds, time, *, field='reference', ax=None, clim=None, cmap=None, title=None):
    """Plot an exact timestamp of an already aligned grid result."""
    if ds.attrs.get('comparison_kind')!='grid' or field not in {'reference','candidate','difference'}:
        raise ValueError('field_map requires grid comparison output and a reference/candidate/difference field')
    stamp=np.datetime64(time,'ns')
    if stamp not in ds.time.values:
        raise ValueError('requested timestamp is absent; choose an exact comparison time')
    a=ds[field].sel(time=stamp)
    circular=definition(ds.attrs['variable']) in DIRECTION_VARS
    finite=a.values[np.isfinite(a.values)]
    if not finite.size:
        raise ValueError('no common finite cells at the requested time')
    if clim is None:
        if field=='difference':
            limit=float(np.max(abs(finite))) or 1.;clim=(-limit,limit)
        elif circular:clim=(0.,360.)
        else:clim=(float(finite.min()),float(finite.max()))
    if len(clim)!=2 or not np.isfinite(clim).all() or clim[0]>clim[1]:
        raise ValueError('clim must contain two ordered finite limits')
    if clim[0]==clim[1]:clim=(clim[0]-.5,clim[1]+.5)
    cmap=cmap or ('RdBu_r' if field=='difference' else 'twilight' if circular else 'viridis')
    fig,ax=_axes(ax)
    mesh=ax.pcolormesh(ds.lon.values,ds.lat.values,a.values,shading='nearest',
                       vmin=clim[0],vmax=clim[1],cmap=cmap)
    name=ds.attrs.get(field+'_name',ds.difference.attrs.get('long_name','candidate minus reference'))
    ax.set(xlabel='Longitude (°E)',ylabel='Latitude (°N)',
           title=title or f'{name}: {ds.attrs["variable"]}\n{np.datetime_as_string(stamp,unit="m")} UTC')
    ax.set_aspect(1/max(np.cos(np.deg2rad(float(ds.lat.mean()))),1e-6))
    ax.set_xlim(float(ds.lon.min()),float(ds.lon.max()));ax.set_ylim(float(ds.lat.min()),float(ds.lat.max()))
    fig.colorbar(mesh,ax=ax,label=a.attrs.get('units',''),shrink=.8)
    _record(fig,'field_map',ds,time=str(stamp),field=field,clim=list(clim),cmap=cmap,
            coordinates='geographic; aspect corrected at mean latitude')
    return fig,ax


def comparison_panels(ds, time, *, clim=None, difference_limit=None, figsize=(15,5)):
    """Reference, candidate and signed difference; shared field colour limits."""
    import matplotlib.pyplot as plt
    stamp=np.datetime64(time,'ns')
    if stamp not in ds.time.values:
        raise ValueError('requested timestamp is absent; choose an exact comparison time')
    if clim is None and definition(ds.attrs['variable']) not in DIRECTION_VARS:
        values=np.concatenate([ds[v].sel(time=stamp).values.ravel() for v in ['reference','candidate']])
        values=values[np.isfinite(values)]
        if not values.size:raise ValueError('no common finite cells at requested time')
        clim=(float(values.min()),float(values.max()))
    if difference_limit is not None and (not np.isfinite(difference_limit) or difference_limit<=0):
        raise ValueError('difference_limit must be positive and finite')
    fig,axes=plt.subplots(1,3,figsize=figsize,constrained_layout=True)
    for field,ax in zip(['reference','candidate','difference'],axes):
        limits=clim if field!='difference' else None if difference_limit is None else (-difference_limit,difference_limit)
        field_map(ds,stamp,field=field,ax=ax,clim=limits)
    return fig,axes


def time_series(tables, *, ax=None, connect=False, title=None):
    """Station observation/model series on preselected identical observation IDs.

    Default markers avoid suggesting continuous model evolution between matches.
    connect=True draws straight visual links only; it never creates model values.
    """
    if not tables:raise ValueError('provide a label-to-result mapping')
    first=next(iter(tables.values()));variable,units=_pair(first)
    for label,ds in tables.items():
        if _pair(ds)!=(variable,units):raise ValueError('all series require the same quantity and units')
        for key in ('obs_id','time','lat','lon',variable):
            if key not in ds or key not in first or not np.array_equal(ds[key].values,first[key].values):
                raise ValueError('series need identical observations; call common_sample explicitly first')
        if len(np.unique(ds.lat))!=1 or len(np.unique(ds.lon))!=1:
            raise ValueError('time_series requires one fixed station; select the station before plotting')
    fig,ax=_axes(ax,figsize=(10,4))
    order=np.argsort(first.time.values)
    def draw(values,label,**kwargs):
        values=np.asarray(values)[order].copy()
        points,=ax.plot(first.time.values[order],values,label=label,marker='.',ms=3,
                        linestyle='none',**kwargs)
        if connect:
            if definition(variable) in DIRECTION_VARS:
                values[np.r_[False,np.abs(np.diff(values))>180]]=np.nan
            ax.plot(first.time.values[order],values,color=points.get_color(),lw=.9)
    draw(first[variable].values,'Observations',color='black')
    for label,ds in tables.items():
        draw(ds[f'model_{variable}'].values,label)
        _record(fig,'time_series',ds,label=label,connect=connect)
    ax.set(xlabel='Observation time (UTC)',ylabel=f'{variable} ({units})',title=title or variable)
    if definition(variable) in DIRECTION_VARS:ax.set_ylim(0,360)
    ax.grid(alpha=.2);ax.legend();fig.autofmt_xdate()
    return fig,ax


def scatter(ds, *, ax=None, title=None):
    """Plot the saved finite observation/model pairs; no sample selection or fitting."""
    v,units=_pair(ds);o=ds[v].values;p=ds[f'model_{v}'].values
    valid=np.isfinite(o)&np.isfinite(p);o,p=o[valid],p[valid]
    if not len(o):raise ValueError('no finite pairs to plot')
    fig,ax=_axes(ax,figsize=(5,5))
    limits=(0,360) if definition(v) in DIRECTION_VARS else (float(min(o.min(),p.min())),float(max(o.max(),p.max())))
    if limits[0]==limits[1]:limits=(limits[0]-.5,limits[1]+.5)
    ax.scatter(o,p,s=10,alpha=.5)
    ax.plot(limits,limits,'k--',lw=.8)
    ax.set(xlabel=f'Observed {v} ({units})',ylabel=f'Model {v} ({units})',
           title=title or f'{v}: {len(o)} pairs',xlim=limits,ylim=limits)
    ax.set_aspect('equal');ax.grid(alpha=.2)
    _record(fig,'scatter',ds,n=int(len(o)),limits=list(limits))
    return fig,ax


def save_figure(fig, path, *, dpi=180):
    """Save a normal Matplotlib figure and an adjacent .figure.json provenance file."""
    import matplotlib
    from .campaign import _file_sha256
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(path,dpi=dpi)
    record=dict(figure=str(path.resolve()),sha256=_file_sha256(path),matplotlib=matplotlib.__version__,
        dpi=dpi,plots=getattr(fig,'_fieldmatch_records',[]),
        axes=[dict(title=a.get_title(),xlabel=a.get_xlabel(),ylabel=a.get_ylabel(),
                   xlim=list(a.get_xlim()),ylim=list(a.get_ylim())) for a in fig.axes])
    metadata = path.parent / '.fieldmatch' / (path.name + '.figure.json')
    metadata.parent.mkdir(parents=True, exist_ok=True)
    metadata.write_text(json.dumps(record,indent=2))
    return path
