# Runnable examples

## Terminal-first real-data study

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

## Synthetic smoke test (no external data)

From the source folder:

```bash
python examples/create_demo_data.py
fieldmatch scan examples/minimal_campaign.yaml
fieldmatch vars examples/minimal_campaign.yaml altimeter
fieldmatch collocate examples/minimal_campaign.yaml altimeter model --variable hs --format both
fieldmatch stats examples/results/demo_altimeter_x_model_hs.nc
```

The generated examples/data and examples/results directories are ignored by Git.
The source scripts locate their bundled data relative to their own file locations.
The package CLI uses normal shell paths for its positional YAML argument; use an
absolute path when invoking it outside the source folder.

`python examples/python_api.py` demonstrates `read_obs`, `open_model`,
`collocate_track` and `write_pairs`. That lower-level workflow leaves campaign
provenance management to your script; named comparisons are the usual starting point.

## Other templates

`forecast_campaign.yaml` illustrates fixed initialization/lead selection.
`extra_variables_campaign.yaml` illustrates reader choices and extra source fields.
These templates contain placeholder paths and require your own datasets.
`config/campaigns/harry.yaml` is a larger inventory template; `examples/harry.yaml`
is the smaller runnable study once its data_root points at a Harry delivery.

All scientific choices remain in the YAML or Python script. Example data and
notebook results from a particular user's installation are not distributed.
