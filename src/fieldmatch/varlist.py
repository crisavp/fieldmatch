"""`fieldmatch vars`: show what a data file actually contains.

The readers keep a deliberately small map from source variables to standard
names -- Sentinel-3 RED ships 65 variables and three become hs/wind_speed/sig0.
That is a sensible default and a bad ceiling: an advanced user will want
`sig0`, a rain flag, a wave period or a retracker diagnostic, and should not
have to leave the tool (or read readers.py) to find out those exist.

This module answers three questions about one dataset, from its first file:
  - which source variables are there, grouped by the axis they lie on;
  - which are already mapped to a standard name, and to which;
  - which can be pulled through as-is with `extra_vars:` (those on the axis
    the reader builds its records on) and which cannot (another rate/axis).

Read-only: it opens a file and describes it, nothing else.
"""
import warnings

import numpy as np
import xarray as xr

from .readers import READERS


def _open_groups(path, kind):
    """{group label: Dataset} for the groups this kind reads."""
    layout = READERS[kind].layout
    out = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for g in (layout.get("group"),) + tuple(layout.get("extra_groups", ())):
            try:
                out[g or "/"] = xr.open_dataset(path, group=g, decode_timedelta=False)
            except (OSError, KeyError):
                continue
    return out


def _decode_flags(var):
    """CF flag metadata -> '0=no_rain 1=rain ...'.

    A flag variable is categorical: it stores small integers, and the file
    says what each one means via `flag_values` + `flag_meanings`. Showing the
    bare meanings alone ('no_rain rain ...') leaves the reader to guess which
    number is which; pairing them makes the variable usable without the spec.
    """
    meanings = str(var.attrs.get("flag_meanings", "")).split()
    if not meanings:
        return ""
    values = np.atleast_1d(var.attrs.get("flag_values", np.arange(len(meanings))))
    pairs = [f"{int(v)}={m}" for v, m in zip(values, meanings)]
    return " ".join(pairs)


def _clean_source(raw):
    """'data_01/ku:swh_ocean (MLE)' -> 'ku:swh_ocean'; 'VAVH' -> 'VAVH'.

    Provenance values carry a human note and, for grouped products, the full
    group path. Reduce them to the name this module displays.
    """
    name = raw.split(" (")[0].strip()
    if name.startswith("(") or not name:
        return None                      # e.g. '(campaign file: lat)'
    if ":" in name:                      # data_01/ku:swh_ocean -> ku:swh_ocean
        group, _, var = name.rpartition(":")
        short = group.rsplit("/", 1)[-1]
        return f"{short}:{var}" if short and short != "data_01" else var
    return name


def _mapped_sources(dset, path):
    """{source variable: standard name} the reader actually used.

    Derived by RUNNING the reader on the sample file and reading the
    `<standard>_source` attributes it wrote, rather than from a table kept
    alongside. A hardcoded copy silently went stale once already (CMEMS
    latitude/longitude/time showed as unmapped), which is exactly the drift
    this command exists to prevent.
    """
    from .readers import read_obs
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ds = read_obs(dset.kind, path, **dset.options)
    except Exception:
        return {}                        # listing still works, just unannotated
    if ds is None:
        return {}
    mapped = {}
    for key, val in ds.attrs.items():
        if not key.endswith("_source"):
            continue
        name = _clean_source(str(val))
        if name:
            mapped[name] = key[: -len("_source")]
    return mapped


def describe_model(dset):
    """Model datasets: every variable is already exposed, so this is a plain
    listing with each variable's own output cadence -- there is nothing to
    'add', because nothing was withheld."""
    from .campaign import MODEL_KINDS
    from .models import open_model
    from .scan import _fmt_step, var_cadences
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ds = open_model(dset.paths, engine=MODEL_KINDS[dset.kind], **dset.options)
    except ValueError as e:
        if "several forecast inits" in str(e):
            return {"error": "multi-init forecast archive -- set `init:` in the "
                             "campaign file, or use `fieldmatch collocate --lead`."}
        return {"error": f"{type(e).__name__}: {e}"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}

    cad = var_cadences(ds)
    entries = []
    for v in sorted(ds.data_vars):
        step, _tol, n, _t0, _t1 = cad.get(v, (None, None, 0, None, None))
        entries.append({
            "name": v, "group": "/", "n": n,
            "units": ds[v].attrs.get("units", ""),
            "long_name": (ds[v].attrs.get("long_name")
                          or ds[v].attrs.get("GRIB_name") or ""),
            "codes": "", "mapped_to": None, "usable": False,
            "cadence": _fmt_step(step) if step is not None else "-",
        })
    out = {"path": (dset.files() or ["?"])[0], "kind": dset.kind,
           "n_files": len(dset.files()), "model": True, "entries": entries,
           "grid": f"{ds.sizes['lat']} x {ds.sizes['lon']}"}
    ds.close()
    return out


def describe_dataset(dset):
    """Inspect the first file of `dset` -> a description for format_vars()."""
    if dset.role == "model":
        return describe_model(dset)
    files = dset.files()
    if not files:
        return {"error": f"no files match {dset.paths}"}
    path = files[0]
    kind = dset.kind
    spec = READERS.get(kind)
    if spec is None:
        return {"error": f"no layout known for kind {kind!r}"}
    layout = spec.layout
    if kind == "buoy_ispra":
        return _describe_csv(path, dset, len(files))

    groups = _open_groups(path, kind)
    if not groups:
        return {"error": f"could not open {path}"}
    mapped = _mapped_sources(dset, path)
    cloud_dim = layout["dim"]
    cloud_dims = cloud_dim if isinstance(cloud_dim, tuple) else (cloud_dim,)

    # A name is not unique across groups: Sentinel-6 stores Ku and C band under
    # data_01/ku and data_01/c with IDENTICAL variable names. Qualify those, so
    # what is listed is also what `extra_vars` can unambiguously ask for.
    seen = {}
    for label, ds in groups.items():
        for name in ds.variables:
            seen.setdefault(name, set()).add(label)
    ambiguous = {n for n, labels in seen.items() if len(labels) > 1}

    axes = {}
    for label, ds in groups.items():
        for name, var in ds.variables.items():
            sig = tuple(var.dims)
            short = label.rsplit("/", 1)[-1] if label != "/" else ""
            shown = f"{short}:{name}" if name in ambiguous and short else name
            entry = {
                "name": shown,
                "group": label,
                "n": int(np.prod([ds.sizes[d] for d in sig])) if sig else 1,
                "units": var.attrs.get("units", ""),
                "long_name": (var.attrs.get("long_name")
                              or var.attrs.get("standard_name") or ""),
                "codes": _decode_flags(var),
                # Qualified first: only ku:swh_ocean is read as hs, not c:.
                "mapped_to": mapped.get(shown, mapped.get(name)
                                        if shown == name else None),
                "usable": sig == cloud_dims,
            }
            axes.setdefault(sig, []).append(entry)
    for ds in groups.values():
        ds.close()

    return {"path": path, "kind": kind, "n_files": len(files),
            "cloud_dims": cloud_dims, "axes": axes}


def _describe_csv(path, dset, n_files):
    """Buoy CSVs: one flat table, so every column is on the same axis."""
    import csv
    with open(path) as fh:
        header = next(csv.reader(fh, delimiter=";"))
    mapped = _mapped_sources(dset, path)
    entries = []
    for h in header:
        name = h.split(" [")[0].strip()
        unit = h.split("[")[1].rstrip("]").strip() if "[" in h else ""
        entries.append({"name": name, "group": "/", "n": 0, "units": unit,
                        "long_name": "", "codes": "",
                        "mapped_to": mapped.get(name), "usable": True})
    return {"path": path, "kind": dset.kind, "n_files": n_files,
            "cloud_dims": ("row",), "axes": {("row",): entries}}


def format_vars(name, desc, show_all=False, width=78):
    """Render describe_dataset() output as terminal blocks."""
    from .scan import _wrap_text
    L = []
    if "error" in desc:
        return f"{name}: {desc['error']}"
    import os
    L.append(f"{name}  [{desc['kind']}]  {desc['n_files']} file(s)")

    if desc.get("model"):
        # Models hide nothing: open_model exposes every field in the files, so
        # there is no standard-name selection and no extra_vars to offer. The
        # useful facts are the variable's own output cadence and its units.
        L.append(f"  grid   : {desc['grid']}")
        L.append("")
        L.append(f"  ALL model variables are read  ({len(desc['entries'])})")
        w = max((len(e["cadence"]) for e in desc["entries"]), default=4) + 1
        for e in desc["entries"]:
            head = f"    {e['name']:<14} every {e['cadence']:<{w}}"
            detail = " ".join(x for x in (e["units"], e["long_name"]) if x)
            L.extend(_wrap_text(detail[:120], head, width=width) if detail
                     else [head.rstrip()])
        L.append("")
        L.append("  Nothing is withheld for models, so `extra_vars` does not")
        L.append("  apply -- it exists only for observation products, where each")
        L.append("  reader selects a few variables out of many.")
        return "\n".join(L)

    L.extend(_wrap_text(os.path.basename(desc["path"]), "  sample : ", width=width))
    L.append(f"  records lie on: {' x '.join(desc['cloud_dims'])}")

    # Two labelled blocks, not a tag column. With 65 variables of which 6 are
    # read, a per-row tag is invisible; a heading that says what the whole
    # block is can be scanned at a glance.
    def _fmt(e, tagw):
        tag = f"-> {e['mapped_to']}" if e["mapped_to"] else ""
        head = f"    {e['name']:<28} {tag:<{tagw}}" if tagw else f"    {e['name']:<28} "
        detail = " ".join(x for x in (e["units"], e["long_name"]) if x)
        out = _wrap_text(detail[:120], head, width=width) if detail else [head.rstrip()]
        if e["codes"]:
            out.extend(_wrap_text(e["codes"], " " * 6 + "values: ", width=width))
        return out

    def _block(title, entries, tagged):
        L.append("")
        L.append(f"  {title}  ({len(entries)})")
        tagw = (max(len(f"-> {e['mapped_to']}") for e in entries) + 1) if tagged else 0
        for e in sorted(entries, key=lambda e: e["name"]):
            L.extend(_fmt(e, tagw))

    main = tuple(desc["cloud_dims"])
    for sig, entries in sorted(desc["axes"].items(), key=lambda kv: -len(kv[1])):
        on_axis = sig == main
        if not on_axis and not show_all:
            L.append("")
            L.append(f"  {len(entries)} more variable(s) on {sig} -- a different "
                     f"rate/axis, not usable with extra_vars. Show with --all.")
            continue
        if not on_axis:
            L.append("")
            L.append(f"  ---- {sig}: a different rate/axis. These need reader "
                     f"support; ----")
            L.append(f"  ---- they cannot be added with extra_vars.              "
                     f"       ----")
            _block(f"variables on {sig}", entries, tagged=False)
            continue
        read = [e for e in entries if e["mapped_to"]]
        avail = [e for e in entries if not e["mapped_to"]]
        if read:
            _block("ALREADY READ, as these standard variables", read, tagged=True)
        if avail:
            _block("AVAILABLE -- add any of these with extra_vars", avail, tagged=False)

    L.append("")
    L.append("  To add variables, list them in the campaign file:")
    L.append(f"      {name}: {{..., extra_vars: [<name>, <name>]}}")
    L.append("  They arrive as extra `x_<name>` columns, carried through unchanged.")
    return "\n".join(L)
