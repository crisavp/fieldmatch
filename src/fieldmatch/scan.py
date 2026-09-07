"""`fieldmatch scan`: inventory a campaign -- what is on disk, what is readable,
and how much of it falls inside the campaign box/period. The first command to
run on any new data delivery; its report is the ground truth for 'the program
does not see my files' conversations."""
import numpy as np

from .campaign import MODEL_KINDS, combine_provenance, crop_obs
from .collocate_track import DEFAULT_TOL
from .models import open_model
from .readers import read_obs


def _t(v):
    return np.datetime_as_string(np.datetime64(v), unit="m")


def scan_obs(dset, bbox, period):
    files = dset.files()
    rep = {"role": "obs", "files": len(files), "readable": 0, "obs_total": 0,
           "obs_in_box": 0, "t0": None, "t1": None, "vars": set(), "errors": [],
           "clouds": []}
    tmin, tmax = None, None
    for f in files:
        try:
            ds = read_obs(dset.kind, f, **dset.options)
        except Exception as e:
            rep["errors"].append(f"{f}: {type(e).__name__}: {e}")
            continue
        rep["readable"] += 1
        if ds is None:
            continue
        rep["obs_total"] += ds.sizes["obs"]
        rep["vars"].update(ds.data_vars)
        rep["clouds"].append(ds)
        sub = crop_obs(ds, bbox, period)
        if sub is not None:
            rep["obs_in_box"] += sub.sizes["obs"]
            lo, hi = sub["time"].values.min(), sub["time"].values.max()
            tmin = lo if tmin is None else min(tmin, lo)
            tmax = hi if tmax is None else max(tmax, hi)
    rep["t0"], rep["t1"] = tmin, tmax
    rep["prov"] = combine_provenance(rep.pop("clouds"))
    return rep


def _fmt_step(td):
    """timedelta64 -> '1h' / '6h' / '30min' / '3d'."""
    if isinstance(td, tuple):
        return "/".join(_fmt_step(v) for v in td)
    secs = float(td / np.timedelta64(1, "s"))
    if secs <= 0 or not np.isfinite(secs):
        return "?"
    if secs % 86400 == 0:
        return f"{int(secs // 86400)}d"
    if secs % 3600 == 0:
        return f"{int(secs // 3600)}h"
    if secs % 60 == 0:
        return f"{int(secs // 60)}min"
    return f"{secs:.0f}s"


def _fmt_tol(td):
    return _fmt_step(td) if td is not None else "?"


def var_cadences(ds):
    """{var: (step, tol, nsteps, t0, t1)} on each variable's OWN non-empty
    steps -- merged cubes mix cadences (hourly waves, 6-hourly winds), so a
    single dataset-level timestep would be wrong for half the variables.
    `tol` is the fixed default matching tolerance used by collocation.
    """
    t = ds["time"].values
    out = {}
    for v in ds.data_vars:
        dims = ds[v].dims
        if "time" not in dims:
            continue
        axes = tuple(i for i, d in enumerate(dims) if d != "time")
        finite = np.flatnonzero(np.isfinite(ds[v].values).any(axis=axes))
        if finite.size == 0:
            out[v] = (None, None, 0, None, None)
            continue
        tv = t[finite]
        intervals = np.unique(np.diff(tv))
        step = (intervals[0] if len(intervals)==1 else tuple(intervals)) if len(intervals) else None
        tol = DEFAULT_TOL
        out[v] = (step, tol, tv.size, tv.min(), tv.max())
    return out


def scan_model(dset, bbox=None, period=None):
    rep = {"role": "model", "files": len(dset.files()), "errors": []}
    try:
        ds = open_model(dset.paths, engine=MODEL_KINDS[dset.kind], bbox=bbox,
                        period=period, time_pad=DEFAULT_TOL, **dset.options)
    except ValueError as e:
        if "several forecast inits" in str(e):
            # Not a failure: a multi-init archive simply has to be told which
            # forecast, or which lead window, to verify.
            rep["needs_lead"] = True
            return rep
        rep["errors"].append(f"{type(e).__name__}: {e}")
        return rep
    except Exception as e:
        rep["errors"].append(f"{type(e).__name__}: {e}")
        return rep
    rep.update(
        vars=sorted(ds.data_vars),
        cadences=var_cadences(ds),
        nlat=ds.sizes["lat"], nlon=ds.sizes["lon"],
        lat=(float(ds.lat.min()), float(ds.lat.max())),
        lon=(float(ds.lon.min()), float(ds.lon.max())),
        ntime=ds.sizes["time"], t0=ds["time"].values.min(), t1=ds["time"].values.max(),
    )
    ds.close()
    return rep


def scan_campaign(camp):
    """name -> report dict, in campaign declaration order."""
    out = {}
    for name, dset in camp.datasets.items():
        if dset.role == "model":
            out[name] = scan_model(dset, camp.bbox, camp.period)
        else:
            out[name] = scan_obs(dset, camp.bbox, camp.period)
    return out


def _wrap(items, width=68, indent=" " * 14):
    """Join short items into lines that fit a narrow terminal. Continuation
    lines are indented and the break keeps its separating comma."""
    lines, cur = [], ""
    for it in items:
        if cur and len(cur) + len(it) + 2 > width:
            lines.append(cur + ",")
            cur = it
        else:
            cur = f"{cur}, {it}" if cur else it
    if cur:
        lines.append(cur)
    return [lines[0]] + [indent + ln for ln in lines[1:]] if lines else [""]


def _wrap_text(text, prefix, width=78):
    """Prefixed free text wrapped to `width`, continuations hanging-indented."""
    import textwrap
    lines = textwrap.wrap(text, width=max(20, width - len(prefix))) or [""]
    return [prefix + lines[0]] + [" " * len(prefix) + ln for ln in lines[1:]]


def format_report(camp, reports):
    """Per-dataset blocks: short labelled lines that survive any terminal width
    (the previous single-row-per-dataset layout wrapped mid-field at ~150
    chars and was unreadable when pasted into mail)."""
    L = []
    L.append(f"campaign: {camp.name}")
    L.append(f"  region : lon [{camp.bbox['lonmin']}, {camp.bbox['lonmax']}]  "
             f"lat [{camp.bbox['latmin']}, {camp.bbox['latmax']}]")
    L.append(f"  period : {_t(camp.period[0])} -> {_t(camp.period[1])}")

    for name, r in reports.items():
        L.append("")
        if r["role"] == "model":
            L.append(f"{name}  [MODEL]  {r['files']} file(s)")
            if r.get("needs_lead"):
                L.extend(_wrap_text(
                    "multi-init forecast archive -- choose what to verify: "
                    "`collocate ... --lead 12-35` (a lead window across all inits) "
                    "or set `init:` in the campaign file to follow one forecast.",
                    "  note     : "))
                continue
            if r["errors"]:
                L.extend(_wrap_text(r["errors"][0], "  UNREADABLE: "))
                continue
            L.append(f"  grid     : {r['nlat']} x {r['nlon']}  "
                     f"lat [{r['lat'][0]:.2f}, {r['lat'][1]:.2f}]  "
                     f"lon [{r['lon'][0]:.2f}, {r['lon'][1]:.2f}]")
            L.append(f"  time     : {r['ntime']} steps  "
                     f"{_t(r['t0'])} -> {_t(r['t1'])}")
            # Per-variable cadence: grouped by step so equal-cadence variables
            # share a line (waves 1h / winds 6h is the common case).
            groups = {}
            for v, (step, tol, n, _, _) in sorted(r["cadences"].items()):
                key = (_fmt_step(step) if step is not None else "empty",
                       _fmt_tol(tol) if tol is not None else "-", n)
                groups.setdefault(key, []).append(v)
            L.append("  variables:")
            for (step, tol, n), vs in sorted(groups.items(), key=lambda kv: -kv[0][2]):
                head = f"    every {step:<5} ({n:>4} steps, default tol {tol:<5}) : "
                wrapped = _wrap(vs, width=max(20, 78 - len(head)), indent=" " * len(head))
                L.append(head + wrapped[0])
                L.extend(wrapped[1:])
        else:
            L.append(f"{name}  [OBS]  {r['readable']}/{r['files']} file(s) readable")
            L.append(f"  in box   : {r['obs_in_box']} of {r['obs_total']} obs")
            if r["t0"] is not None:
                L.append(f"  time     : {_t(r['t0'])} -> {_t(r['t1'])}")
            elif r["obs_total"]:
                L.append("  time     : (nothing inside the campaign box/period)")
            if r["vars"]:
                wrapped = _wrap(sorted(r["vars"]), width=64, indent=" " * 14)
                L.append(f"  variables: {wrapped[0]}")
                L.extend(wrapped[1:])
            # What the readers discarded, and why -- auditable without opening
            # a single file (the same record is written into every output).
            p = r.get("prov") or {}
            read = p.get("n_read")
            drops = [(lbl, p.get(k, 0)) for k, lbl in
                     (("n_rejected_qual", "quality"), ("n_rejected_coastal", "coastal/land"))]
            drops = [(lbl, n) for lbl, n in drops if n]
            if read or drops:
                bits = [f"{n} {lbl}" for lbl, n in drops] or ["none"]
                L.append(f"  rejected : {', '.join(bits)}"
                         + (f"  (of {read} read)" if read else ""))
            if p.get("land_mask"):
                L.extend(_wrap_text(str(p["land_mask"]), "  land mask: "))
            unfiltered = sorted(k[:-7] for k, v in p.items()
                                if k.endswith("_filter") and str(v).startswith("none"))
            if unfiltered:
                L.append(f"  UNFILTERED: {', '.join(unfiltered)} "
                         f"(no quality flag in this product)")
            for e in r["errors"]:
                L.append(f"  ERROR    : {e}")
    return "\n".join(L)
