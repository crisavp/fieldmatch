# Runnable examples

## Terminal-first real-data study

Copy `analyze.py` and `harry.yaml` into a study folder. Edit the YAML's data_root
once, then use:

```bash
python /path/to/study/analyze.py inspect
python /path/to/study/analyze.py run
python /path/to/study/analyze.py plot
```

The default YAML is beside the script. An explicit `--config` can be absolute or
relative to the script; it never depends on the terminal working directory.
Data and output paths resolve from the YAML. Plotting reads saved results and
writes a browser gallery, images, tables and figure sidecars under `<outdir>/figures`.
`plot --show` also displays figures when a graphical backend is available.

The same script contains VS Code `# %%` cells. Install `.[interactive]`, select
your installed environment, and set `INTERACTIVE_CONFIG` to an absolute YAML path.
Run setup → inspect → run → plot; skip the run cell to reuse existing comparisons.
The returned `tables`, `pairs` and `grids` can be inspected or used in further cells.
No JupyterLab server is needed. See the [analysis guide](../docs/analysis-guide.md).

This script is intentionally editable study code, not another configuration
framework. It makes common-sample grouping and the optional severe-Hs threshold
visible. Adapt its analysis choices when the scientific question changes.

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
