# FieldMatch

FieldMatch compares observations with model fields, or one model with another,
with explicit scientific choices. Each physical quantity has its own result.
Optional plotting functions draw prepared results without matching or regridding.

## Start your own analysis

**Start with [Your first complete analysis](docs/analysis-guide.md).** It walks
through copying the Harry example, setting paths, inspecting data, configuring
comparisons, checking results, selecting common observations and making figures.
It also covers storm subsets, sensitivity experiments and saving a reproducible study.

- [Harry notebook](examples/harry_exploration.ipynb): run and adapt the example.
- [Harry campaign](examples/harry_campaign.yaml): datasets and comparison choices.
- [Troubleshooting](docs/troubleshooting.md): setup, matching, stale results and figures.

From an activated environment, in this repository:

```bash
python -m pip install -e '.[notebook]'
fieldmatch doctor
python -m jupyterlab examples/harry_exploration.ipynb
```

The Harry data are not bundled. Set the notebook's `DATA_ROOT` and `OUTPUT` before
running it. The current Harry workspace uses conda `wave-models2`; a fresh
installation from `environment.yml` uses conda `fieldmatch`. Install `.[plot]`
for Matplotlib only, or `pip install -e .` for the numerical core without plotting.

## The usual workflow

```bash
fieldmatch scan your_campaign.yaml
fieldmatch vars your_campaign.yaml analysis
fieldmatch compare your_campaign.yaml buoy_analysis --describe
fieldmatch compare your_campaign.yaml buoy_analysis --format both
```

`analysis` and `buoy_analysis` are names defined in your YAML, not built-in names.
The example campaign contains those names. The notebook uses the same runner and
can execute every named comparison in a batch.

Shared choices go under `matching_defaults`. A comparison groups variables, each
with optional settings directly below its name:

```yaml
# Fragment inside an existing campaign; see the complete Harry template.
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

`hs: {}` inherits the defaults. In this illustrative period experiment, `tp`
requires exact timestamps. Source-name mappings such as `pp1d: tp` belong in the
model dataset's `rename` mapping. Distinct period/wind definitions are not aliases.

## What is explicit

- **Observation/model:** nearest valid time within a declared tolerance; bilinear
  or nearest spatial sampling. Missing wind never removes an accepted Hs pair.
- **Model/model:** exact shared valid times on the declared reference grid, with
  optional equal-initialization/lead restrictions. Difference = model minus reference.
- **Spatial behavior:** no extrapolation or automatic coastal filling. Directions
  use circular interpolation; atmospheric wind uses components where available.
- **Fair samples:** `common_sample` intersects observation IDs when you request it;
  plotting does not silently choose a different sample.
- **Provenance:** results record effective settings, mappings, units, source hashes,
  forecast coordinates and acceptance/mask information. Keep their manifests.

Observation comparisons default to CSV. Grid comparisons default to NetCDF;
their CSV contains spatial summaries, not the full fields. Use `--format both`
when you want both. Repeating a comparison replaces its outputs. Changing a
campaign currently requires rerunning its comparisons before provenance validation.

## Reference pages

| Page | Use it for |
|---|---|
| [Analysis guide](docs/analysis-guide.md) | A complete self-guided study |
| [Campaign reference](docs/campaign-reference.md) | YAML keys, defaults, readers, initialization and lead |
| [Output formats](docs/output-formats.md) | Pair columns, grid masks, summaries and manifests |
| [Grid and plotting guide](docs/grids-and-plotting.md) | Python functions, time bases, weighting and figure options |
| [Examples](examples/README.md) | Synthetic smoke test and lower-level Python workflows |
| [Troubleshooting](docs/troubleshooting.md) | Common errors and their meaning |
| [Contributing](CONTRIBUTING.md), [testing](docs/testing.md), [adding readers](docs/adding-readers.md) | Library development |

Version 0.3 adds grid comparisons and plotting while retaining the 0.2 observation
workflow. For older configurations, use `matching_defaults` and a `variables`
mapping, and include the quantity in downstream output filenames. See
[migration notes](docs/output-formats.md#migration-from-01) and [history](HISTORY.md).
