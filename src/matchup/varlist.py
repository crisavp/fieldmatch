"""`matchup vars`: show what a data file actually contains.

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

from .readers import LAYOUT


def _open_groups(path, kind):
    """{group label: Dataset} for the groups this kind reads."""
    layout = LAYOUT.get(kind, {"group": None, "extra_groups": ()})
    out = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for g in (layout.get("group"),) + tuple(layout.get("extra_groups", ())):
            try:
                out[g or "/"] = xr.open_dataset(path, group=g, decode_timedelta=False)
            except (OSError, KeyError):
                continue
    return out


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


def describe_dataset(dset):
    """Inspect the first file of `dset` -> a description for format_vars()."""
    files = dset.files()
    if not files:
        return {"error": f"no files match {dset.paths}"}
    path = files[0]
    kind = dset.kind
    layout = LAYOUT.get(kind)
    if layout is None:
        return {"error": f"no layout known for kind {kind!r}"}
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
                "flags": var.attrs.get("flag_meanings", ""),
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
                        "long_name": "", "flags": "",
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
    L.extend(_wrap_text(os.path.basename(desc["path"]), "  sample : ", width=width))
    L.append(f"  records lie on: {' x '.join(desc['cloud_dims'])}")

    # Column width from the longest tag actually present, with a guaranteed
    # trailing space: a long standard name (`-> hs_unfiltered`) used to run
    # straight into the units, reading as 'hs_unfilteredm'.
    tags = [f"-> {e['mapped_to']}" if e["mapped_to"]
            else ("extra_vars" if e["usable"] else "")
            for entries in desc["axes"].values() for e in entries]
    tagw = max([len(t) for t in tags] + [10]) + 1

    def _fmt(e):
        tag = (f"-> {e['mapped_to']}" if e["mapped_to"]
               else ("extra_vars" if e["usable"] else ""))
        head = f"    {e['name']:<28} {tag:<{tagw}}"
        detail = " ".join(x for x in (e["units"], e["long_name"]) if x)
        if not detail:
            return [head.rstrip()]
        return _wrap_text(detail[:120], head, width=width)

    main = tuple(desc["cloud_dims"])
    for sig, entries in sorted(desc["axes"].items(), key=lambda kv: -len(kv[1])):
        on_axis = sig == main
        if not on_axis and not show_all:
            L.append("")
            L.append(f"  {len(entries)} more variable(s) on {sig} -- a different "
                     f"rate/axis;")
            L.append(f"  not usable with extra_vars. Show with --all.")
            continue
        L.append("")
        L.append(f"  variables on {sig}  ({len(entries)})"
                 + ("" if on_axis else "   [OTHER AXIS -- needs reader support]"))
        for e in sorted(entries, key=lambda e: (e["mapped_to"] is None, e["name"])):
            L.extend(_fmt(e))
            if e["flags"]:
                L.extend(_wrap_text(e["flags"][:110], " " * 6 + "flags: ", width=width))
    L.append("")
    L.append("  '-> name' is already read as that standard variable.")
    L.append("  'extra_vars' can be added verbatim via the campaign file, e.g.")
    L.append(f"      {name}: {{..., extra_vars: [<name>, ...]}}")
    return "\n".join(L)
