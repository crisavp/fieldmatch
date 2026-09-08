# FieldMatch

FieldMatch compares observations with model fields, or one model with another,
with explicit scientific settings and one result per physical quantity. Optional
plotting functions use prepared results without doing their own matching.

## Install

Use Python 3.10 or newer. The simplest route for someone who already has conda
and wants to use its base environment is one command from the repository:

```bash
bash install.sh --base
```

No conda activation is required. The installer adds FieldMatch and its plotting
dependencies to base and verifies GRIB and NetCDF support. To update a GitHub
checkout later:

```bash
git pull --ff-only
bash install.sh --base
```

In any other already-active Python environment, use:

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

## Run a study from Python

Use YAML as a catalogue for paths, readers, coordinate/variable names and provider
quality fields. Put the scientific experiment in one ordinary Python script:

```python
import fieldmatch as fm

study = fm.Study("harry.yaml")
buoy = study.open_observations("buoy_ba04")
forecast = study.open_model(
    "forecast", variables=["hs"], init_cycle="00:00", lead="12-35"
)

# Spatial extraction retains every native model time; it does not match time.
station = fm.extract_station(
    forecast, observations=buoy, variables=["hs"], space_method="bilinear"
)

# Time matching is a separate, explicit operation used for statistics.
pairs = fm.match_times(
    buoy, station, variable="hs", tolerance="30min", time_tie="earlier"
)
```

Plot `buoy.time/buoy.hs` and `station.time/station.hs` directly with Matplotlib.
They retain their independent native sampling. Use `common_sample` only when a
fair statistical ranking requires several models to share observations.

The same script can be run with `python analysis.py` or split into `# %%` cells.
Nothing detects the execution environment or requires JupyterLab. Saving prepared
NetCDF results is optional.

The command line remains useful for installation and data inspection:

```bash
fieldmatch doctor
fieldmatch scan /path/to/study/harry.yaml
fieldmatch vars /path/to/study/harry.yaml forecast
```

Named YAML comparisons and the `run`/`compare` commands remain available for
reproducible batch production, but are not required by the Python-first workflow.

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
    variables:
      hs: {}
```

`{}` inherits the defaults. The period setting above is an illustrative exact-time
experiment, not a physical requirement. Model source names are mapped once in the
dataset's `rename` block. Incompatible period/wind definitions are not aliases.

Observation matching uses nearest time within a declared tolerance. Grid matching
uses exact common valid times from the selected dataset views on the declared
reference grid; difference = model minus reference. Both use explicit spatial rules, no extrapolation or automatic coastal
filling, and circular/vector treatment where appropriate. Common-observation
selection is a separate, explicit analysis step.

The package CLI remains available for individual operations:

```bash
fieldmatch scan /path/to/study/harry.yaml
fieldmatch vars /path/to/study/harry.yaml analysis
fieldmatch compare /path/to/study/harry.yaml buoy_analysis --describe
fieldmatch compare /path/to/study/harry.yaml buoy_analysis --format both
```

Use `fieldmatch --help` for the command overview and `fieldmatch COMMAND --help`
for options. `run --describe` and `compare --describe` show labelled configuration
previews without computing or writing results. The automatic JSON files are
[provenance records](docs/output-formats.md#why-are-there-json-files), not extra
configuration to maintain.

## Documentation

- [Reader options](docs/readers.md) and [complete YAML catalogue](src/fieldmatch/config_example.yaml).

- [CLI reference](docs/cli.md): commands, options and preview mode.

- [Installation](docs/installation.md): existing/new environments and sharing.
- [Analysis guide](docs/analysis-guide.md): full terminal sequence and optional cells.
- [Campaign reference](docs/campaign-reference.md): datasets, units and matching choices.
- [Outputs](docs/output-formats.md): pair columns, grid masks and provenance.
- [Grid/plotting API](docs/grids-and-plotting.md): reusable Python functions.
- [Troubleshooting](docs/troubleshooting.md), [examples](examples/README.md).
- [Contributing](CONTRIBUTING.md), [testing](docs/testing.md), [history](HISTORY.md).

Version 0.5 provides the Python-first study API and compact forecast provenance.
The source archive includes scripts and documentation; the wheel installs the
package itself.

Use `fieldmatch config-example --output config_reference.yaml` for all editable keys,
and `fieldmatch info RESULT` to read provenance without opening internal JSON.
Preserve the hidden `.fieldmatch` folders when copying results.
