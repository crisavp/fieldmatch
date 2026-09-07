# FieldMatch

FieldMatch compares observations with model fields, or one model with another,
with explicit scientific settings and one result per physical quantity. Optional
plotting functions use prepared results without doing their own matching.

## Install

Use Python 3.10 or newer. From the supplied source folder, in an existing Python
environment:

```bash
python -m pip install '.[plot]'
fieldmatch doctor
```

For a **new conda environment**, including the GRIB C library:

```bash
conda env create -f environment.yml
conda activate fieldmatch
python -m pip install '.[plot]'
fieldmatch doctor
```

See [installation](docs/installation.md) for pip/venv, wheels, GRIB troubleshooting,
and optional VS Code cells. No JupyterLab setup is required.

## Run a study

Copy `examples/analyze.py` and `examples/harry.yaml` into your study folder.
Edit the YAML's data root and dataset declarations, then run the installed commands:

```bash
fieldmatch scan /path/to/study/harry.yaml
fieldmatch run /path/to/study/harry.yaml --describe
fieldmatch run /path/to/study/harry.yaml
```

`scan` inventories files and coverage. `run --describe` prints resolved scientific
choices without computing. `run` executes all declared comparisons and variables,
saving NetCDF, CSV and manifests. Use `fieldmatch compare` for one named comparison.

Set `CONFIG` in `analyze.py` to your YAML's absolute path, then run:

```bash
python /path/to/study/analyze.py
```

The script only reads saved results, calculates summaries and plots them.
Set `SHOW = True` to display figures and `SAVE = True` to save figures, tables,
provenance and an HTML gallery. Either can be disabled independently. For a headless
terminal use `SHOW = False, SAVE = True` (as two separate Python assignments).
Display uses your Matplotlib backend; no interactive-window detection is performed.

The same `CONFIG` works in the terminal and VS Code cells. Relative YAML data/output
paths resolve from the YAML. CLI paths use ordinary shell rules; absolute paths
work from anywhere. No script arguments or working-directory guessing are involved.

In VS Code, select your installed Python environment and run the two cells in order:
settings/functions, then load/plot. `tables`, `pairs`, `grids` and `analysis` remain
available for exploration. No JupyterLab server is required. Comparisons are always
run separately from the terminal.

See the [complete analysis guide](docs/analysis-guide.md).

## Scientific choices

```yaml
# Fragment within a campaign; datasets are declared separately.
matching_defaults:
  tolerance_minutes: 30
  space_method: bilinear
comparisons:
  buoy_analysis:
    obs: ba08
    model: analysis
    variables:
      hs: {}
      tp: {tolerance_minutes: 0}
  analysis_era5:
    reference: analysis
    model: era5
    time_basis: valid_time
    variables:
      hs: {}
```

`{}` inherits the defaults. The period setting above is an illustrative exact-time
experiment, not a physical requirement. Model source names are mapped once in the
dataset's `rename` block. Incompatible period/wind definitions are not aliases.

Observation matching uses nearest time within a declared tolerance. Grid matching
uses exact common times on the declared reference grid; difference = model minus
reference. Both use explicit spatial rules, no extrapolation or automatic coastal
filling, and circular/vector treatment where appropriate. Common-observation
selection is a separate, explicit analysis step.

The package CLI remains available for individual operations:

```bash
fieldmatch scan /path/to/study/harry.yaml
fieldmatch vars /path/to/study/harry.yaml analysis
fieldmatch compare /path/to/study/harry.yaml buoy_analysis --describe
fieldmatch compare /path/to/study/harry.yaml buoy_analysis --format both
```

## Documentation

- [Installation](docs/installation.md): existing/new environments and sharing.
- [Analysis guide](docs/analysis-guide.md): full terminal sequence and optional cells.
- [Campaign reference](docs/campaign-reference.md): datasets, units and matching choices.
- [Outputs](docs/output-formats.md): pair columns, grid masks and provenance.
- [Grid/plotting API](docs/grids-and-plotting.md): reusable Python functions.
- [Troubleshooting](docs/troubleshooting.md), [examples](examples/README.md).
- [Contributing](CONTRIBUTING.md), [testing](docs/testing.md), [history](HISTORY.md).

Version 0.4 changes the example workflow and installation guidance. Numerical
comparison settings and the 0.3 YAML schema remain compatible. The source archive
includes scripts and documentation; the wheel installs the package itself.
