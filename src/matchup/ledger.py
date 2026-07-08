"""Per-product processing ledger.

The ledger is the durable record of *which raw scenes are already handled* for a
(sat x model) product, so skip/resume no longer depends on the transient per-file
`*_colloc.nc` still existing. Once a year's obs are folded into its part file and
recorded here, the per-file colloc can be deleted to save storage.

Stored at `_parts/{prefix}_{label}/ledger.json`:
    {
      "ingested": [<colloc_basename>, ...],   # folded into a year part (durable)
      "empty":    [<raw_basename>, ...]        # processed, no obs in region / bad
                                               # time -- a PERMANENT skip. Scenes
                                               # that only lacked model coverage are
                                               # NOT recorded (they retry once the
                                               # model catches up).
    }
"""
import json
import os
import re
from collections import Counter

from . import config as _cfg

_YMD = re.compile(r"(20\d{2})(0[1-9]|1[0-2])([0-2]\d|3[01])")


def ledger_path(cfg, sat, model):
    return os.path.join(str(_cfg.parts_dir(cfg, sat, model)), "ledger.json")


def load_ledger(cfg, sat, model):
    p = ledger_path(cfg, sat, model)
    d = {}
    if os.path.exists(p):
        with open(p) as fh:
            d = json.load(fh)
    d.setdefault("ingested", [])
    d.setdefault("empty", [])
    return d


def save_ledger(cfg, sat, model, ledger):
    p = ledger_path(cfg, sat, model)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    ledger["ingested"] = sorted(set(ledger["ingested"]))
    ledger["empty"] = sorted(set(ledger["empty"]))
    tmp = p + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(ledger, fh)
    os.replace(tmp, p)


def raw_to_colloc(raw_basename):
    """Map a raw filename to its collocated filename."""
    return raw_basename.replace(".nc", "_colloc.nc")


def month_counts(ledger):
    """Ingested-obs-file count per YYYY-MM, parsed from the basenames."""
    c = Counter()
    for b in ledger["ingested"]:
        m = _YMD.search(b)
        if m:
            c[f"{m.group(1)}-{m.group(2)}"] += 1
    return dict(sorted(c.items()))
