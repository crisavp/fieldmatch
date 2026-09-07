# FieldMatch examples

## Runnable synthetic campaign

Generate three synthetic observations and a tiny model grid:

```bash
python examples/create_demo_data.py
fieldmatch scan examples/minimal_campaign.yaml
fieldmatch vars examples/minimal_campaign.yaml altimeter
fieldmatch collocate examples/minimal_campaign.yaml altimeter model --variable hs
fieldmatch stats examples/results/demo_altimeter_x_model_hs.csv
```

Try the other output modes:

```bash
fieldmatch collocate examples/minimal_campaign.yaml altimeter model --variable hs --format netcdf
fieldmatch collocate examples/minimal_campaign.yaml altimeter model --variable hs --format both
fieldmatch stats examples/results/demo_altimeter_x_model_hs.nc \
  --output examples/results/demo_statistics.csv
```

The generated `examples/data/` and `examples/results/` directories are ignored
by Git and may be deleted at any time.

### Python building blocks

The campaign CLI is the recommended public workflow because it handles file
discovery, cropping, manifests and provenance. For code that already owns those
concerns, the same synthetic files can exercise the lower-level Python API:

```bash
PYTHONPATH=src python examples/python_api.py
```

The example shows the three boundaries directly: `read_obs`, `open_model` and
`collocate_track`, followed by `write_pairs`.

## Templates for real products

- `forecast_campaign.yaml` shows a multi-initialization GRIB archive with a
  fixed buoy. Run collocation with `--lead 24` or a window such as `--lead
  12-35`.
- `extra_variables_campaign.yaml` shows reader choices, coordinate/variable
  mappings and `extra_vars`. Run `fieldmatch vars ... --all` against the real
  delivery before choosing source names.

Templates intentionally contain `/path/to/study`; they are documentation and
will not run until paths, region and period are replaced. Copy a template for
each real study instead of editing the examples in place.

## Shared runner and fair samples

```python
from fieldmatch.campaign import load_campaign
from fieldmatch.comparison import resolve_comparisons, run_comparisons

camp = load_campaign("campaign.yaml")
specs = resolve_comparisons(camp, "waves")
results, failures = run_comparisons(camp, specs, formats=("csv", "netcdf"))
if failures:
    raise RuntimeError(failures)
```

For a multi-model study, read the generated NetCDF files and apply explicit
event/lead restrictions, then:

```python
from fieldmatch.common import common_sample
from fieldmatch.pairstats import stats_table
aligned, counts = common_sample({"analysis": analysis_pairs, "hindcast": hindcast_pairs})
scores = {name: stats_table(ds) for name, ds in aligned.items()}
```

The returned counts expose how much each model loses when selecting common
observations. This helper does not select event phases or confidence intervals.

## Harry exploration with reusable plots

Install the optional notebook dependencies (`pip install -e '.[notebook]'`), then
open `harry_exploration.ipynb` in Jupyter. Set `DATA_ROOT` to the Harry data tree.
The notebook uses `harry_campaign.yaml`, writes a resolved campaign next to its
outputs, runs comparisons, intersects buoy samples explicitly, and makes four
figures with provenance sidecars. It can redraw saved results by setting
`RUN_COMPARISONS = False`; stale inputs/configurations are rejected.

For automated execution, `FIELDMATCH_DATA_ROOT` and `FIELDMATCH_OUTPUT` override
the two notebook paths. These are conveniences for the example, not library
configuration rules. The original data are not redistributed.
