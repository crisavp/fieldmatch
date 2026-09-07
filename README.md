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

Copy [analyze.py](examples/analyze.py) and [harry.yaml](examples/harry.yaml) into a
study folder. Edit `data_root` in the YAML to point to your data. The Harry source
data are not included; [synthetic examples](examples/README.md) need no downloads.

```bash
python /path/to/study/analyze.py inspect
python /path/to/study/analyze.py run
python /path/to/study/analyze.py plot
```

- `inspect`: list files and resolved scientific settings.
- `run`: compute comparisons and save NetCDF, CSV and manifests.
- `plot`: read validated saved results, print scores and save figures/tables plus
  an `index.html` gallery you can open in a browser. It does not recompute matches.
- `plot --show`: also display Matplotlib windows when a graphical backend is available.

The default configuration is `harry.yaml` beside the script. `--config` selects
another YAML; relative values are resolved **from the script**, not the terminal
working directory. Data/output paths are resolved **from the YAML**. Nothing
searches the current directory for a project automatically.

In VS Code, the same script has `# %%` cells. Set its `INTERACTIVE_CONFIG` to an
absolute YAML path, choose your Python environment in the Interactive Window, and
run setup → inspect → run → plot. Skip the run cell when adjusting figures.

Start with the [complete analysis guide](docs/analysis-guide.md).

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

Unlike the example script's `--config`, a relative positional YAML path passed to
`fieldmatch` is a normal terminal path. Use an absolute path to invoke it anywhere.

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
