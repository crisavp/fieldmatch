"""Configuration loading and path resolution. No domain logic.

Resolves the config YAML to region boxes, model/satellite specs, model file
lists, and collocated/parts/merged output paths. Everything here is mechanical
lookup + globbing (mirrors wfetch/config.py).
"""
import glob as _glob
import os
from pathlib import Path

import yaml

# Repo root = two levels up from this file (src/matchup/config.py -> repo root).
PKG_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG = PKG_ROOT / "config" / "config.yaml"


def load_config(path=None):
    """Load the config dict, resolving data_root to an absolute path."""
    path = Path(path) if path else DEFAULT_CONFIG
    with open(path) as fh:
        cfg = yaml.safe_load(fh)
    cfg["roots"]["data_root"] = _resolve(cfg["roots"]["data_root"])
    return cfg


def _resolve(p):
    """Absolute path; relative paths are taken relative to the repo root."""
    p = Path(p)
    return p if p.is_absolute() else (PKG_ROOT / p).resolve()


# ── spec lookups (fail loud on unknown names) ──────────────────────────────
def get_region(cfg, name):
    regions = cfg["regions"]
    if name not in regions:
        raise KeyError(f"unknown region '{name}'; defined: {sorted(regions)}")
    return regions[name]


def get_model(cfg, name):
    models = cfg["models"]
    if name not in models:
        raise KeyError(f"unknown model '{name}'; defined: {sorted(models)}")
    return models[name]


def get_sat(cfg, name):
    sats = cfg["sat_sources"]
    if name not in sats:
        raise KeyError(f"unknown sat source '{name}'; defined: {sorted(sats)}")
    return sats[name]


# ── file resolution ────────────────────────────────────────────────────────
def _data_root(cfg):
    return Path(cfg["roots"]["data_root"])


def model_files(cfg, model):
    """Sorted list of model files for a model spec (fail loud if none)."""
    pattern = str(_data_root(cfg) / model["glob"])
    files = sorted(_glob.glob(pattern))
    if not files:
        raise FileNotFoundError(
            f"model '{model['label']}' matched no files: {pattern}"
        )
    return files


def raw_sat_files(cfg, sat):
    """Sorted list of raw satellite files for a sat spec (fail loud if none)."""
    pattern = str(_data_root(cfg) / sat["raw_glob"])
    files = sorted(_glob.glob(pattern))
    if not files:
        raise FileNotFoundError(
            f"sat source matched no files: {pattern}"
        )
    return files


# ── collocated / parts / merged output paths ───────────────────────────────
def collocated_root(cfg):
    return _data_root(cfg) / cfg["roots"]["collocated_subdir"]


def collocated_dir(cfg, sat, model):
    """Per-file collocation output dir: collocated/{prefix}_{model_label}."""
    return collocated_root(cfg) / f"{sat['outdir_prefix']}_{model['label']}"


def parts_dir(cfg, sat, model):
    """Incremental yearly parts dir: collocated/_parts/{prefix}_{model_label}."""
    return collocated_root(cfg) / "_parts" / f"{sat['outdir_prefix']}_{model['label']}"


def years_tag(years):
    """'YYYY' when start==end else 'YYYY_YYYY'."""
    y0, y1 = int(years[0]), int(years[-1])
    return f"{y0}" if y0 == y1 else f"{y0}_{y1}"


def merged_stem(sat, model):
    """The merged filename stem WITHOUT the year tag, e.g.
    'ASCAT_ifs_hres_neutral_med_merged' -- used both to name new files and to
    prune stale ones so the wfetch glob resolves to exactly one file."""
    return f"{sat['merged_prefix']}_{model['label'].lower()}_merged"


def merged_path(cfg, sat, model, years):
    """Canonical single merged file: {stem}_{Ystart}_{Yend}.nc."""
    return collocated_root(cfg) / f"{merged_stem(sat, model)}_{years_tag(years)}.nc"
