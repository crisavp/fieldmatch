"""Campaign files: one YAML declaring region, period and named datasets.

A campaign is the sharing unit -- a colleague gets the repo plus one YAML that
points at their data tree, and never touches Python. Example:

    campaign: harry
    region: {lonmin: 9, lonmax: 22, latmin: 30, latmax: 41}
    period: [2026-01-16, 2026-01-23]
    outdir: fieldmatch_out         # relative to the YAML's directory
    datasets:
      jason3:   {kind: altimeter_cmems, path: "WAVE/JASON-3/*.nc"}
      ecmwf_an: {kind: grib, path: "data_Jean/analysis/*.grib"}

`path` (str or list) is relative to `data_root` (itself relative to the YAML's
directory unless absolute; default: the YAML's directory). Obs datasets carry
an obs `kind` from readers.READERS; model datasets use kind grib/netcdf with
optional `init` / `rename` options.
"""
import glob as _glob
import hashlib
import json
import os
import re
import warnings
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

from .readers import READERS

MODEL_KINDS = {"grib": "cfgrib", "netcdf": "netcdf4"}

MODEL_OPTIONS = {"init", "lead", "lead_tol", "rename", "coords", "overlap"}


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
        """Resolved files, de-duplicated only when their bytes are identical.

        Deliveries often ship the same product under several folders (the Harry
        set repeats altimeter files under both WAVE/ and WIND/), so a dataset
        may legitimately glob both. Identical copies must be counted once or
        every observation enters the statistics twice. Same name but different
        size means genuinely different files: keep both.
        """
        found = sorted(set(sum((_glob.glob(str(p), recursive=True) for p in self.paths), [])))
        out, candidates, digests = [], {}, {}

        def digest(path):
            if path not in digests:
                digests[path] = _file_sha256(path)
            return digests[path]
        for f in found:
            try:
                key = (os.path.basename(f), os.path.getsize(f))
            except OSError:
                key = (f, None)
            previous = candidates.setdefault(key, [])
            if previous:
                current_digest = digest(f)
                if any(digest(old) == current_digest for old in previous):
                    continue
                warnings.warn(
                    f"keeping distinct files with the same basename and size: "
                    f"{previous[0]} and {f}")
            previous.append(f)
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
    matching_defaults: dict = field(default_factory=dict)
    comparisons: dict = field(default_factory=dict)

    def get(self, name):
        if name not in self.datasets:
            raise KeyError(f"unknown dataset '{name}'; defined: {sorted(self.datasets)}")
        return self.datasets[name]


def load_campaign(path):
    path = Path(path).resolve()
    with open(path) as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ValueError("campaign YAML must contain a mapping")
    for required in ("campaign", "region", "period", "datasets"):
        if required not in raw:
            raise ValueError(f"campaign YAML is missing required key {required!r}")
    allowed_top = {"campaign", "data_root", "outdir", "region", "period", "datasets", "matching_defaults", "comparisons"}
    unknown_top = sorted(set(raw) - allowed_top)
    if unknown_top:
        raise ValueError(f"campaign YAML has unsupported key(s) {unknown_top}")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", str(raw["campaign"])):
        raise ValueError("campaign name may contain only letters, digits, '.', '_' and '-'")
    if (not isinstance(raw["period"], (list, tuple)) or len(raw["period"]) != 2):
        raise ValueError("period must be a two-item [start, end] sequence")
    if not isinstance(raw["datasets"], dict) or not raw["datasets"]:
        raise ValueError("datasets must be a non-empty mapping")
    base = path.parent
    root = Path(raw.get("data_root", "."))
    root = root if root.is_absolute() else (base / root).resolve()

    datasets = {}
    for name, spec in raw["datasets"].items():
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", str(name)):
            raise ValueError(f"dataset name {name!r} contains unsafe characters")
        if not isinstance(spec, dict) or "kind" not in spec or "path" not in spec:
            raise ValueError(f"dataset {name!r} needs both 'kind' and 'path'")
        kind = spec["kind"]
        if kind not in READERS and kind not in MODEL_KINDS:
            raise KeyError(f"dataset '{name}': unknown kind {kind!r}; obs kinds: "
                           f"{sorted(READERS)}, model kinds: {sorted(MODEL_KINDS)}")
        p = spec["path"]
        patterns = [p] if isinstance(p, str) else list(p)
        if not patterns or not all(isinstance(item, str) and item for item in patterns):
            raise ValueError(f"dataset {name!r} path must be a string or non-empty string list")
        patterns = [str(q if Path(q).is_absolute() else root / q) for q in patterns]
        opts = {k: v for k, v in spec.items() if k not in ("kind", "path")}
        allowed = MODEL_OPTIONS if kind in MODEL_KINDS else READERS[kind].options
        unknown = sorted(set(opts) - allowed)
        if unknown:
            raise ValueError(
                f"dataset {name!r} ({kind}) has unsupported option(s) {unknown}; "
                f"allowed: {sorted(allowed)}")
        _validate_options(name, kind, opts)
        datasets[name] = Dataset(name=name, kind=kind, paths=patterns, options=opts)

    t0, t1 = raw["period"]
    t0, t1 = _period_bound(t0, end=False), _period_bound(t1, end=True)
    if t1 < t0:
        raise ValueError(f"campaign period is empty: {t0} .. {t1}")
    bbox = raw["region"]
    needed = {"lonmin", "lonmax", "latmin", "latmax"}
    if not isinstance(bbox, dict) or set(bbox) != needed:
        raise ValueError(f"region must contain exactly {sorted(needed)}")
    bbox = {k: float(v) for k, v in bbox.items()}
    if not (-90 <= bbox["latmin"] < bbox["latmax"] <= 90):
        raise ValueError("region latitude bounds must satisfy -90 <= latmin < latmax <= 90")
    if not (-180 <= bbox["lonmin"] < bbox["lonmax"] <= 180):
        raise ValueError("region longitude bounds must satisfy -180 <= lonmin < lonmax <= 180")
    outdir = Path(raw.get("outdir", "fieldmatch_out"))
    outdir = outdir if outdir.is_absolute() else base / outdir
    from .comparison import validate_matching, validate_comparisons
    matching = raw.get("matching_defaults", {})
    validate_matching(matching)
    comparisons = raw.get("comparisons", {})
    validate_comparisons(comparisons, datasets)
    return Campaign(
        name=str(raw["campaign"]), bbox=bbox,
        period=(t0, t1),
        outdir=outdir, datasets=datasets, path=path, matching_defaults=matching, comparisons=comparisons,
    )


def _validate_options(name, kind, opts):
    for key in ("rename", "coords"):
        if key in opts and not isinstance(opts[key], dict):
            raise ValueError(f"dataset {name!r}: {key} must be a mapping")
    for key in ("qc", "open_ocean_only"):
        if key in opts and not isinstance(opts[key], bool):
            raise ValueError(f"dataset {name!r}: {key} must be true or false")
    if opts.get("overlap", "error") not in {"error", "shortest_lead"}:
        raise ValueError("overlap must be error or shortest_lead")
    if "lead_tol" in opts and (not np.isfinite(float(opts["lead_tol"])) or float(opts["lead_tol"]) < 0):
        raise ValueError(f"dataset {name!r}: lead_tol cannot be negative")
    if "extra_vars" in opts:
        value = opts["extra_vars"]
        values = [value] if isinstance(value, str) else value
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise ValueError(f"dataset {name!r}: extra_vars must be a string or string list")
    if kind == "buoy_ispra":
        missing = [key for key in ("lat", "lon") if key not in opts]
        if missing:
            raise ValueError(f"dataset {name!r}: buoy_ispra requires {missing}")
        lat, lon = float(opts["lat"]), float(opts["lon"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError(f"dataset {name!r}: buoy position is outside valid bounds")


def _period_bound(value, end=False):
    """Parse a campaign bound; a date-only end includes its full UTC day."""
    text = str(value)
    result = np.datetime64(text, "ns")
    if end and re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        result += np.timedelta64(1, "D") - np.timedelta64(1, "ns")
    return result


def _file_sha256(path, chunk_size=1024 * 1024):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pair_digest(camp, obs_name, model_name):
    """Digest the campaign contract and current inputs for one output pair."""
    def dataset_record(dset):
        files = []
        for name in dset.files():
            st = os.stat(name)
            files.append((str(Path(name).resolve()), st.st_size, st.st_mtime_ns))
        return {"kind": dset.kind, "paths": dset.paths, "options": dset.options,
                "files": files}

    record = {
        "campaign": camp.name, "bbox": camp.bbox,
        "matching_defaults": camp.matching_defaults, "comparisons": camp.comparisons,
        "period": [str(v) for v in camp.period],
        "obs": dataset_record(camp.get(obs_name)),
        "model": dataset_record(camp.get(model_name)),
    }
    payload = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def manifest_path(stem):
    return Path(f"{stem}.manifest.json")


def write_run_manifest(stem, camp, obs_name, model_name, status, **details):
    """Atomically record whether the stable output belongs to the latest run."""
    target = manifest_path(stem)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "status": status,
        "pair_digest": pair_digest(camp, obs_name, model_name),
        "campaign": camp.name, "obs_dataset": obs_name, "model_dataset": model_name,
        "campaign_file": str(camp.path),
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **details,
    }
    if "effective" in record:
        record["execution_digest"] = execution_digest(record["effective"])
    tmp = target.with_suffix(target.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(record, indent=2, sort_keys=True, default=json_default) + "\n")
    tmp.replace(target)
    return record


def validate_run_manifest(stem, camp, obs_name, model_name):
    """Return (ok, reason) for a pair produced from a known campaign."""
    path = manifest_path(stem)
    if not path.exists():
        return False, f"{path} is missing (rerun `fieldmatch collocate`)"
    try:
        record = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"cannot read {path}: {exc}"
    if record.get("status") != "complete":
        return False, f"latest collocation run is {record.get('status', 'unknown')!r}"
    if record.get("pair_digest") != pair_digest(camp, obs_name, model_name):
        return False, "campaign settings or input files changed since this pair was written"
    return True, ""


def validate_output_manifest(output):
    """Validate a result when provenance is available without harming portability.

    Returns ``(ok, reason, warning)``. A copied data file remains readable
    without its adjacent manifest, but an explicit failed/running manifest is
    never accepted.
    """
    output = Path(output)
    path = manifest_path(output.with_suffix(""))
    if not path.exists():
        return True, "", "no adjacent manifest; provenance cannot be revalidated"
    try:
        record = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"cannot read {path}: {exc}", ""
    if record.get("status") != "complete":
        return False, f"latest collocation run is {record.get('status', 'unknown')!r}", ""
    if "effective" in record and record.get("execution_digest") != execution_digest(record["effective"]):
        return False, "effective comparison specification does not match its digest", ""
    fmt = "netcdf" if output.suffix in {".nc", ".netcdf"} else "csv"
    expected = record.get("output_sha256", {}).get(fmt)
    if expected and _file_sha256(output) != expected:
        return False, "pair contents differ from the saved output checksum", ""
    campaign_file = record.get("campaign_file")
    if not campaign_file or not Path(campaign_file).exists():
        return True, "", "campaign YAML is unavailable; inputs were not revalidated"
    try:
        camp = load_campaign(campaign_file)
        current = pair_digest(camp, record["obs_dataset"], record["model_dataset"])
    except Exception as exc:
        return False, f"cannot revalidate provenance: {exc}", ""
    if current != record.get("pair_digest"):
        return False, "campaign settings or input files changed since this pair was written", ""
    return True, "", ""


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


def execution_digest(effective):
    return hashlib.sha256(json.dumps(effective, sort_keys=True, default=json_default,
                                     separators=(",", ":")).encode()).hexdigest()


def json_default(value):
    """Keep numerical provider metadata numerical in portable manifests."""
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic) and not isinstance(value, (np.datetime64, np.timedelta64)):
        return value.item()
    return str(value)
