"""`fieldmatch scan`: inventory a campaign -- what is on disk, what is readable,
and how much of it falls inside the campaign box/period. The first command to
run on any new data delivery; its report is the ground truth for 'the program
does not see my files' conversations."""
import numpy as np

from .campaign import MODEL_KINDS, combine_provenance, crop_obs
from .collocate_track import DEFAULT_TOL
from .models import _coordinate_names, _hours, _open_one, open_model
from .readers import READERS, read_obs


def _t(v):
    return np.datetime_as_string(np.datetime64(v), unit="m")


def _retained_sources(ds):
    """Canonical retained-QC name -> provider name from reader provenance."""
    text = str(ds.attrs.get("retained_qc", ""))
    return dict(item.split("=", 1) for item in text.split(", ") if "=" in item)


def _add_quality_inventory(inventory, ds, sources):
    """Accumulate human-readable values/counts from retained provider evidence."""
    for name, source in sources.items():
        if name not in ds:
            continue
        arr = ds[name]
        values = np.asarray(arr.values).ravel()
        entry = inventory.setdefault(name, {
            "source": source, "total": 0, "finite": 0, "meanings": {},
            "unrecognized": {}, "missing": 0, "min": None, "max": None,
            "bitmask": False,
        })
        entry["total"] += values.size
        finite_mask = np.ones(values.shape, dtype=bool)
        if np.issubdtype(values.dtype, np.number):
            finite_mask = np.isfinite(values)
            finite = values[finite_mask]
            entry["finite"] += finite.size
            entry["missing"] += int(np.count_nonzero(~finite_mask))
            if finite.size:
                lo, hi = float(finite.min()), float(finite.max())
                entry["min"] = lo if entry["min"] is None else min(entry["min"], lo)
                entry["max"] = hi if entry["max"] is None else max(entry["max"], hi)
        meanings = str(arr.attrs.get("flag_meanings", "")).split()
        flag_values = np.atleast_1d(arr.attrs.get("flag_values", []))
        bitmask = arr.attrs.get("fieldmatch_flag_mode") == "bitmask"
        entry["bitmask"] = entry["bitmask"] or bitmask
        recognized = np.zeros(values.shape, dtype=bool)
        for meaning, flag_value in zip(meanings, flag_values):
            item = entry["meanings"].setdefault(meaning, {"values": set(), "count": 0})
            scalar = np.asarray(flag_value).item()
            item["values"].add(scalar)
            match = (values == scalar if not bitmask or scalar == 0 else
                     ((values.astype("int64") & int(scalar)) == int(scalar)))
            recognized |= match
            item["count"] += int(np.count_nonzero(match))
        if meanings:
            unknown = finite_mask & ~recognized
            if bitmask:
                known_bits = 0
                for value in flag_values:
                    known_bits |= int(value)
                unknown = finite_mask & ((values.astype("int64") & ~known_bits) != 0)
            for raw, count in zip(*np.unique(values[unknown],
                                             return_counts=True)):
                scalar = np.asarray(raw).item()
                entry["unrecognized"][scalar] = \
                    entry["unrecognized"].get(scalar, 0) + int(count)


def scan_obs(dset, bbox, period):
    files = dset.files()
    rep = {"role": "obs", "files": len(files), "readable": 0, "obs_total": 0,
           "obs_in_box": 0, "t0": None, "t1": None, "vars": set(), "errors": [],
           "clouds": [], "quality_inventory": {},
           "retain_qc": bool(dset.options.get("retain_qc", False))}
    tmin, tmax = None, None
    scan_options = dict(dset.options)
    if "retain_qc" in READERS[dset.kind].options:
        # Inventory quality evidence even when ordinary pair output remains compact.
        scan_options["retain_qc"] = True
    for f in files:
        try:
            ds = read_obs(dset.kind, f, **scan_options)
        except Exception as e:
            rep["errors"].append(f"{f}: {type(e).__name__}: {e}")
            continue
        rep["readable"] += 1
        if ds is None:
            continue
        rep["obs_total"] += ds.sizes["obs"]
        retained = _retained_sources(ds)
        _add_quality_inventory(rep["quality_inventory"], ds, retained)
        rep["vars"].update(
            name for name in ds.data_vars
            if rep["retain_qc"] or name not in retained)
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


def _finite_times(values):
    values = np.asarray(values).astype("datetime64[ns]").ravel()
    return values[~np.isnat(values)]


def _forecast_cycles(inits):
    """Sorted UTC times of day represented by initialization timestamps."""
    if not len(inits):
        return []
    offsets = inits - inits.astype("datetime64[D]").astype("datetime64[ns]")
    seconds = np.unique(offsets / np.timedelta64(1, "s")).astype(int)
    out = []
    for value in seconds:
        hour, remainder = divmod(value, 3600)
        minute, second = divmod(remainder, 60)
        out.append(f"{hour:02d}:{minute:02d}" if second == 0 else
                   f"{hour:02d}:{minute:02d}:{second:02d}")
    return out


def model_time_inventory(dset):
    """Inspect raw model coordinates without inventing forecast provenance.

    A forecast is selectable only when the source carries ``step`` with an
    initialization ``time``, or already-normalized ``init`` and ``lead_hours``.
    Filenames are deliberately not parsed.
    """
    kinds, inits, leads, valid, errors = set(), [], [], [], []
    for filename in dset.files():
        try:
            groups = _open_one(filename, MODEL_KINDS[dset.kind])
        except Exception as exc:
            errors.append(f"{filename}: {type(exc).__name__}: {exc}")
            continue
        for raw in groups:
            try:
                ds = raw.rename(_coordinate_names(raw, dset.options.get("coords")))
                if "step" in ds.coords:
                    if "time" not in ds.coords:
                        kinds.add("ambiguous")
                        continue
                    init_values = _finite_times(ds["time"].values)
                    lead_values = np.asarray(_hours(ds["step"].values), dtype=float).ravel()
                    kinds.add("forecast")
                    inits.extend(init_values)
                    leads.extend(lead_values[np.isfinite(lead_values)])
                    valid.extend(_finite_times((ds["time"] + ds["step"]).values))
                elif ("init" in ds.coords) != ("lead_hours" in ds.coords):
                    kinds.add("ambiguous")
                elif "init" in ds.coords:
                    kinds.add("forecast")
                    inits.extend(_finite_times(ds["init"].values))
                    lead_values = np.asarray(ds["lead_hours"].values, dtype=float).ravel()
                    leads.extend(lead_values[np.isfinite(lead_values)])
                    if "time" in ds.coords:
                        valid.extend(_finite_times(ds["time"].values))
                elif "time" in ds.coords:
                    kinds.add("valid_time_only")
                    valid.extend(_finite_times(ds["time"].values))
                else:
                    kinds.add("ambiguous")
            except Exception as exc:
                errors.append(f"{filename}: {type(exc).__name__}: {exc}")
            finally:
                raw.close()
    if not kinds:
        time_kind = "unknown"
    elif len(kinds) == 1:
        time_kind = next(iter(kinds))
    else:
        time_kind = "ambiguous"
    inits = np.unique(np.asarray(inits, dtype="datetime64[ns]"))
    leads = np.unique(np.asarray(leads, dtype=float))
    valid = np.unique(np.asarray(valid, dtype="datetime64[ns]"))
    selection = {key: dset.options[key] for key in ("init", "init_cycle", "lead")
                 if dset.options.get(key) is not None}
    report = dict(time_kind=time_kind, raw_init_count=len(inits), raw_lead_count=len(leads),
                  raw_valid_count=len(valid), raw_cycles=_forecast_cycles(inits),
                  selection=selection, time_inventory_errors=errors)
    if len(inits):
        report.update(raw_init_t0=inits.min(), raw_init_t1=inits.max())
    if len(leads):
        intervals = np.unique(np.diff(leads))
        report.update(raw_lead_min=float(leads.min()), raw_lead_max=float(leads.max()),
                      raw_lead_intervals=intervals.tolist())
    if len(valid):
        report.update(raw_valid_t0=valid.min(), raw_valid_t1=valid.max())
    return report


def scan_model(dset, bbox=None, period=None):
    rep = {"role": "model", "files": len(dset.files()), "errors": []}
    rep.update(model_time_inventory(dset))
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
            kind = r.get("time_kind", "unknown")
            labels = {"forecast": "forecast (initialization + lead)",
                      "valid_time_only": "valid-time only",
                      "ambiguous": "ambiguous/incomplete forecast metadata",
                      "unknown": "unknown (no readable time metadata)"}
            L.append(f"  time type: {labels.get(kind, kind)}")
            if kind == "forecast":
                if r.get("raw_init_count"):
                    L.append(f"  init     : {r['raw_init_count']} available  "
                             f"{_t(r['raw_init_t0'])} -> {_t(r['raw_init_t1'])}")
                    L.append(f"  cycles   : {', '.join(r['raw_cycles'])} UTC")
                if r.get("raw_lead_count"):
                    lo, hi = r['raw_lead_min'], r['raw_lead_max']
                    increments = r.get('raw_lead_intervals', [])
                    inc = "/".join(f"{v:g}h" for v in increments) if increments else "single value"
                    L.append(f"  leads    : {lo:g} -> {hi:g} h  "
                             f"({r['raw_lead_count']} available; increments {inc})")
                selection = r.get("selection") or {}
                selected = ", ".join(f"{k}={v}" for k, v in selection.items()) or "none"
                L.append(f"  selection: {selected}")
            elif kind == "valid_time_only":
                if r.get("selection"):
                    selected = ", ".join(f"{k}={v}" for k, v in r["selection"].items())
                    L.append(f"  selection: NOT APPLICABLE ({selected})")
                else:
                    L.append("  selection: not applicable (no initialization/lead metadata)")
            elif r.get("selection"):
                selected = ", ".join(f"{k}={v}" for k, v in r["selection"].items())
                L.append(f"  selection: unavailable ({selected})")
            if r.get("raw_valid_count"):
                L.append(f"  valid raw: {r['raw_valid_count']} available  "
                         f"{_t(r['raw_valid_t0'])} -> {_t(r['raw_valid_t1'])}")
            for error in r.get("time_inventory_errors", [])[:1]:
                L.extend(_wrap_text(error, "  time note: "))
            if r.get("needs_lead"):
                L.extend(_wrap_text(
                    "multi-init forecast archive -- choose what to verify: "
                    "set `init:` for one forecast or `init_cycle:` for a recurring "
                    "UTC cycle, then optionally narrow it with `lead:`.",
                    "  note     : "))
                continue
            if r["errors"]:
                L.extend(_wrap_text(r["errors"][0], "  UNREADABLE: "))
                continue
            L.append(f"  grid     : {r['nlat']} x {r['nlon']}  "
                     f"lat [{r['lat'][0]:.2f}, {r['lat'][1]:.2f}]  "
                     f"lon [{r['lon'][0]:.2f}, {r['lon'][1]:.2f}]")
            L.append(f"  valid load: {r['ntime']} steps  "
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
            inventory = r.get("quality_inventory") or {}
            if inventory:
                L.append("  quality available (after dataset screening):")
                for variable, item in sorted(inventory.items()):
                    meanings = item["meanings"]
                    if meanings:
                        parts = []
                        for meaning, detail in meanings.items():
                            codes = "/".join(str(v) for v in sorted(detail["values"]))
                            parts.append(f"{meaning}[{codes}]={detail['count']}")
                        parts.extend(
                            f"unrecognized[{value}]={count}"
                            for value, count in sorted(item["unrecognized"].items()))
                        if item["missing"]:
                            parts.append(f"missing={item['missing']}")
                        detail = ", ".join(parts)
                    else:
                        missing = item["total"] - item["finite"]
                        detail = f"finite={item['finite']}, missing={missing}"
                        if item["min"] is not None:
                            detail += f", range={item['min']:g}..{item['max']:g}"
                    mode = (" (bit mask; counts may overlap)"
                            if item.get("bitmask") else "")
                    L.append(f"    {variable} <- {item['source']}{mode}")
                    L.extend("      " + line for line in _wrap(
                        detail.split(", "), width=68, indent=""))
                status = ("retained in pair output" if r.get("retain_qc") else
                          "not retained in pair output; set retain_qc: true to keep it")
                L.append(f"  quality output: {status}")
            # What the readers discarded, and why -- auditable without opening
            # a single file (the same record is written into every output).
            p = r.get("prov") or {}
            read = p.get("n_read")
            drops = [(lbl, p.get(k, 0)) for k, lbl in
                     (("n_rejected_qc_union", "QC union"),
                      ("n_rejected_qual", "quality flag"),
                      ("n_rejected_surface", "surface/mask"),
                      ("n_rejected_coastal", "coastal/land"))]
            drops = [(lbl, n) for lbl, n in drops if n]
            if read or drops:
                bits = [f"{n} {lbl}" for lbl, n in drops] or ["none"]
                L.append(f"  rejected : {', '.join(bits)}"
                         + (f"  (of {read} read)" if read else ""))
            if p.get("land_mask"):
                L.extend(_wrap_text(str(p["land_mask"]), "  land mask: "))
            flagged = sorted(
                (k[len("n_flagged_"):-len("_quality")], v,
                 p.get(k.replace("n_flagged_", "n_newly_masked_")))
                for k, v in p.items()
                if k.startswith("n_flagged_") and k.endswith("_quality"))
            for variable, bad, newly in flagged:
                detail = f"{bad} bad flag(s)"
                if newly is not None:
                    detail += f"; {newly} finite value(s) newly masked"
                L.append(f"  {variable} QC: {detail}")
            filters = sorted((k[:-7], str(v)) for k, v in p.items()
                             if k.endswith("_filter") and not str(v).startswith("none"))
            for variable, rule in filters:
                L.extend(_wrap_text(rule, f"  {variable} filter: "))
            unfiltered = sorted((k[:-7], str(v)) for k, v in p.items()
                                if k.endswith("_filter") and str(v).startswith("none"))
            if unfiltered:
                names = ", ".join(name for name, _ in unfiltered)
                reason = ("no quality flag in this product"
                          if all("not present" in value for _, value in unfiltered)
                          else "configured QC is disabled or unavailable")
                L.append(f"  UNFILTERED: {names} ({reason})")
            for e in r["errors"]:
                L.append(f"  ERROR    : {e}")
    return "\n".join(L)
