# Installation and sharing

Use the supplied source folder or wheel. The commands below do not assume a
particular account, folder layout or pre-existing environment. Examples use a
source folder named `fieldmatch`; substitute its actual path.

## Existing Python environment

Activate the environment you normally use, then run from the source folder:

```bash
python -m pip install '.[plot]'
fieldmatch doctor
python -c "import sys, fieldmatch; print(sys.executable); print(fieldmatch.__version__)"
```

From another directory, provide the source path explicitly:

```bash
python -m pip install '/absolute/path/to/fieldmatch[plot]'
```

Use the same `python` to install and run. Installing dependencies may upgrade
packages to satisfy FieldMatch's requirements; choose a new environment if you
want to leave an existing environment's dependencies unchanged. There is no need
to recreate a working environment just because it has a different name.

Install without `[plot]` for the numerical core only. For VS Code interactive
cells, install `[interactive]`, which includes Matplotlib and ipykernel:

```bash
python -m pip install '.[interactive]'
```

This does not install or require JupyterLab. In VS Code, enable its Python and
Jupyter extensions and select this environment as the Interactive Window kernel.
The terminal interpreter and interactive kernel must have the same installation.

## New conda environment

Conda is convenient for the native GRIB dependencies. From the source folder:

```bash
conda env create -f environment.yml
conda activate fieldmatch
python -m pip install '.[plot]'
fieldmatch doctor
```

To choose a different name, use `conda env create -n your_name -f environment.yml`
and activate that name. `env create` refuses to overwrite an existing environment.
For an existing conda environment, activate it and use the existing-environment
installation above; do not apply the entire environment file with `--prune`.

On Bash systems, the optional helper performs the same steps:

```bash
bash install.sh --new fieldmatch
# OR, after activating an existing Python environment:
bash install.sh --existing
```

The helper creates a new conda environment or uses the active Python. It never
updates/prunes an existing conda environment. With no arguments it prints help.

## New pip/venv environment

Use Python 3.10 or newer. From the source folder:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install '.[plot]'
fieldmatch doctor
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` instead of
`source`. Then use the same Python/pip commands. The Bash installer is optional;
Python/pip commands are the cross-platform installation route.

`cfgrib` needs a working ecCodes C library. `doctor` checks that the library loads
and that the GRIB engine is available; it also performs a NetCDF round trip.
If your pip/platform combination cannot supply ecCodes, install its native
library for that platform, or use the conda route. In a conda environment:

```bash
conda install -c conda-forge cfgrib eccodes
fieldmatch doctor
```

Do not assume a successful Python import proves your provider files are readable;
run the scan and a small comparison on a representative delivery too.

## Source versus wheel

A source distribution contains the documentation, installer, environment file,
examples and tests. Copy `examples/analyze.py` and `examples/harry.yaml` into your
own study folder. A wheel contains the importable package and `fieldmatch` command;
copy the examples from the accompanying source archive when installing a wheel.

```bash
python -m pip install '/path/to/fieldmatch-0.4.2-py3-none-any.whl[plot]'
fieldmatch doctor
```

For library development, use `python -m pip install -e '.[plot,dev]'` instead of a
normal install. An editable install points at that checkout, so deleting or moving
the checkout can break it. Normal source/wheel installations do not depend on the
source folder after installation.

To build distributions from a checkout:

```bash
python -m pip install build
python -m build
```

Share the files under `dist/`, and share a separate study YAML/script if appropriate.
Raw Harry files and generated study outputs are not bundled. Paths and sensor/model
metadata in a collaborator's study must refer to their own data delivery.
