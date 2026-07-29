"""Campaign files: one YAML declaring region, period and named datasets.

A campaign is the sharing unit -- a colleague gets the repo plus one YAML that
points at their data tree, and never touches Python. Example:

    campaign: harry
    region: {lonmin: 9, lonmax: 22, latmin: 30, latmax: 41}
    period: [2026-01-16, 2026-01-23]
    outdir: matchup_out            # relative to the YAML's directory
    datasets:
      jason3:   {kind: altimeter_cmems, path: "WAVE/JASON-3/*.nc"}
      ecmwf_an: {kind: grib, path: "data_Jean/analysis/*.grib"}

`path` (str or list) is relative to `data_root` (itself relative to the YAML's
directory unless absolute; default: the YAML's directory). Obs datasets carry
an obs `kind` from readers.READERS; model datasets use kind grib/netcdf with
optional `init` / `rename` options.
"""
import glob as _glob
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

from .readers import READERS

MODEL_KINDS = {"grib": "cfgrib", "netcdf": "netcdf4"}


@dataclass
class Dataset:
    name: str
    kind: str
    paths: list          # resolved absolute glob patterns
    options: dict = field(default_factory=dict)

    @property
    def role(self):
        return "model" if self.kind in MODEL_KINDS else "obs"

    def files(self):
        """Resolved files, de-duplicated by (basename, size).

        Deliveries often ship the same product under several folders (the Harry
        set repeats altimeter files under both WAVE/ and WIND/), so a dataset
        may legitimately glob both. Identical copies must be counted once or
        every observation enters the statistics twice. Same name but different
        size means genuinely different files: keep both.
        """
        found = sorted(set(sum((_glob.glob(str(p), recursive=True) for p in self.paths), [])))
        out, seen = [], set()
        for f in found:
            try:
                key = (os.path.basename(f), os.path.getsize(f))
            except OSError:
                key = (f, None)
            if key in seen:
                continue
            seen.add(key)
            out.append(f)
        return out


@dataclass
class Campaign:
    name: str
    bbox: dict           # lonmin/lonmax/latmin/latmax
    period: tuple        # (np.datetime64, np.datetime64)
    outdir: Path
    datasets: dict       # name -> Dataset
    path: Path

    def get(self, name):
        if name not in self.datasets:
            raise KeyError(f"unknown dataset '{name}'; defined: {sorted(self.datasets)}")
        return self.datasets[name]


def load_campaign(path):
    path = Path(path).resolve()
    with open(path) as fh:
        raw = yaml.safe_load(fh)
    base = path.parent
    root = Path(raw.get("data_root", "."))
    root = root if root.is_absolute() else (base / root).resolve()

    datasets = {}
    for name, spec in raw["datasets"].items():
        kind = spec["kind"]
        if kind not in READERS and kind not in MODEL_KINDS:
            raise KeyError(f"dataset '{name}': unknown kind {kind!r}; obs kinds: "
                           f"{sorted(READERS)}, model kinds: {sorted(MODEL_KINDS)}")
        p = spec["path"]
        patterns = [p] if isinstance(p, str) else list(p)
        patterns = [str(q if Path(q).is_absolute() else root / q) for q in patterns]
        opts = {k: v for k, v in spec.items() if k not in ("kind", "path")}
        datasets[name] = Dataset(name=name, kind=kind, paths=patterns, options=opts)

    t0, t1 = raw["period"]
    outdir = Path(raw.get("outdir", "matchup_out"))
    outdir = outdir if outdir.is_absolute() else base / outdir
    return Campaign(
        name=raw["campaign"], bbox=raw["region"],
        period=(np.datetime64(str(t0)), np.datetime64(str(t1))),
        outdir=outdir, datasets=datasets, path=path,
    )


def combine_provenance(clouds):
    """Merge per-file reader attributes into one record for the whole dataset.

    `xr.concat` keeps only the FIRST dataset's attrs, which would silently
    report one file's rejection counts as if they were the campaign's. Counts
    are summed; descriptive attributes must agree across files, and any
    disagreement is surfaced rather than hidden (e.g. a delivery mixing two
    Sentinel-1 processor versions with different quality conventions).
    """
    from .readers import COUNT_ATTRS
    out = {}
    for ds in clouds:
        for k, v in ds.attrs.items():
            if k in COUNT_ATTRS:
                out[k] = out.get(k, 0) + int(v)
            elif k not in out:
                out[k] = v
            elif out[k] != v:
                prev = out[k] if isinstance(out[k], str) else str(out[k])
                if not prev.startswith("MIXED:"):
                    out[k] = f"MIXED: {prev}"
                if str(v) not in out[k]:
                    out[k] = f"{out[k]} | {v}"
    return out


def crop_obs(ds, bbox, period):
    """Cut an obs cloud to the campaign bbox + period (None if nothing left)."""
    keep = ((ds["lon"].values >= bbox["lonmin"]) & (ds["lon"].values <= bbox["lonmax"])
            & (ds["lat"].values >= bbox["latmin"]) & (ds["lat"].values <= bbox["latmax"])
            & (ds["time"].values >= period[0]) & (ds["time"].values <= period[1]))
    if not keep.any():
        return None
    return ds.isel(obs=np.flatnonzero(keep))
