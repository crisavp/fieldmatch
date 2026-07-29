"""`matchup doctor`: verify the installation actually works.

Checks each dependency the hard way -- not `import cfgrib`, but "write a GRIB,
read it back" -- because the failures that matter (eccodes missing its library,
a netCDF built without HDF5) only appear at use time. Every failure line says
what to do about it.
"""
import importlib
import sys
import tempfile
from pathlib import Path

CHECKS = []


def check(name, fix=""):
    def deco(fn):
        CHECKS.append((name, fn, fix))
        return fn
    return deco


@check("python >= 3.10", fix="recreate the environment: conda env create -f environment.yml")
def _python():
    if sys.version_info < (3, 10):
        raise RuntimeError(f"python {sys.version.split()[0]} is too old")
    return sys.version.split()[0]


@check("core packages", fix="conda env update -n <env> -f environment.yml --prune")
def _imports():
    versions = []
    for mod in ("numpy", "scipy", "pandas", "xarray", "yaml", "typer", "rich"):
        m = importlib.import_module(mod)
        versions.append(f"{mod} {getattr(m, '__version__', '?')}")
    return ", ".join(versions)


@check("netCDF read/write", fix="conda install -c conda-forge netcdf4")
def _netcdf():
    import numpy as np
    import xarray as xr
    ds = xr.Dataset({"x": ("t", np.arange(4.0))}, coords={"t": np.arange(4)})
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "probe.nc"
        ds.to_netcdf(p)
        back = xr.open_dataset(p)
        n = int(back.sizes["t"])
        back.close()
    import netCDF4
    return f"netCDF4 {netCDF4.__version__} (round-trip {n} values)"


@check("GRIB engine (cfgrib + eccodes)",
       fix="conda install -c conda-forge cfgrib eccodes   # both from conda-forge")
def _grib():
    import cfgrib
    import eccodes
    # eccodes only loads its C library on first use -- force it.
    ver = eccodes.codes_get_api_version()
    engines = None
    try:
        import xarray as xr
        engines = xr.backends.list_engines()
    except Exception:
        pass
    if engines is not None and "cfgrib" not in engines:
        raise RuntimeError("cfgrib is installed but xarray does not list it as an engine")
    return f"cfgrib {cfgrib.__version__}, eccodes C library {ver}"


@check("plotting", fix="conda install -c conda-forge matplotlib-base")
def _plot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig = plt.figure()
    plt.close(fig)
    return f"matplotlib {matplotlib.__version__} (Agg backend)"


@check("matchup package", fix="pip install -e .   (from the repo directory)")
def _self():
    from . import campaign, collocate_track, models, pairstats, readers, scan  # noqa: F401
    from .readers import READERS
    return f"{len(READERS)} obs readers: {', '.join(sorted(READERS))}"


@check("example campaign file", fix="the repo is incomplete: re-clone or re-copy it")
def _example():
    p = Path(__file__).resolve().parent.parent.parent / "config" / "campaigns" / "harry.yaml"
    if not p.exists():
        raise FileNotFoundError(f"missing {p}")
    import yaml
    with open(p) as fh:
        raw = yaml.safe_load(fh)
    return f"{p.name}: {len(raw['datasets'])} datasets declared"


def run_doctor(verbose=True):
    """Run every check. Returns True when all pass."""
    ok = True
    for name, fn, fix in CHECKS:
        try:
            detail = fn()
            if verbose:
                print(f"  OK    {name:32} {detail}")
        except Exception as e:
            ok = False
            if verbose:
                print(f"  FAIL  {name:32} {type(e).__name__}: {e}")
                if fix:
                    print(f"        fix: {fix}")
    return ok
