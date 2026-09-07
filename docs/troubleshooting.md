# Troubleshooting an analysis

Start with `fieldmatch doctor`, then `fieldmatch scan your_campaign.yaml` and
`fieldmatch vars your_campaign.yaml dataset_name`. Inspect a named experiment with
`fieldmatch compare your_campaign.yaml comparison_name --describe`.

## Setup and configuration

| Symptom | What to check or change |
|---|---|
| `fieldmatch` or a Python import is unavailable | Activate the installation environment. Check `python -c "import sys; print(sys.executable)"`. Install the repository with that environment's `python -m pip install -e .` if needed. |
| Jupyter opens, but the notebook cannot import FieldMatch | Select the kernel from the same environment. Register it using the command in the [analysis guide](analysis-guide.md). The Jupyter server and kernel can use different environments. |
| Matplotlib or Jupyter is missing | From the repository, install `.[plot]` for figures or `.[notebook]` for the notebook workflow. |
| No files match | Inspect `data_root`, path globs and the scan. Relative paths are relative to the campaign file/data root, not automatically to the terminal directory. The copied notebook overrides data_root/outdir using its settings cell. |
| Unknown dataset or comparison | Use the exact YAML key. Example names such as `analysis` and `ecmwf_an` are not built-in aliases. |
| `matching` or `variable` is rejected in a named comparison | Use `matching_defaults` and `variables: {hs: {}}`. Put variable settings below `hs`, without another `matching` or `overrides` block. |
| Only some definitions seem to exist | Check for duplicate YAML keys. Edit the existing `datasets`/`comparisons` mappings instead of pasting another root block. The current YAML parser can replace a duplicate key silently. |
| `compare --tol-minutes` is rejected | Scientific settings for `compare` belong in YAML. The lower-level `collocate` command has explicit one-off CLI options. |

## Matching and physical meaning

| Symptom | Interpretation and next step |
|---|---|
| Missing model field / no selected fields | Inspect source variables and dataset `rename`. Confirm that this delivery contains the requested quantity. Do not rename a different physical quantity just to make it load. |
| Incompatible quantity or units | Check provider definitions. pp1d/tp and mwp/energy_period are different quantities. Normalize actual units/conventions explicitly in a documented preprocessing step; changing only the units label is not conversion. |
| Observation is outside forecast coverage | Check initialization, valid-time range and the campaign period. A forecast cannot verify observations before its start. |
| Model time gaps exceed tolerance | Inspect available times and offsets. A six-hour forecast may have no satellite pass within 30 minutes. Restrict the experiment or test another justified sampling policy; wider tolerance changes its scientific meaning. |
| Time matches, but no usable model values remain | Inspect the domain, land/missing cells, observation coordinates and direction cancellation. No automatic wet-neighbour search or extrapolation is performed. |
| Conflicting or overlapping forecasts | Select `init` or an exact `lead`/lead window. Use `overlap: shortest_lead` only if a freshest-forecast composite is the intended experiment. It is not equivalent to following one forecast. |
| Grid comparison has no common times | Grid matching is exact. Inspect both time axes and `time_basis`; equal initialization/lead requirements may remove all shared times. Observation-time tolerance cannot change this. |
| A direction is missing although source angles exist | Opposing directions or a nearly zero interpolated wind vector can make direction undefined. Check the saved thresholds; do not replace undefined direction with zero degrees. |

## Results and figures

| Symptom | Interpretation and next step |
|---|---|
| Stale result after editing YAML | Fingerprints currently cover all comparison declarations. Rerun all comparisons from the edited campaign, or preserve a separate campaign and output folder for a new experiment. |
| An old file exists but `open_result` refuses it | Its latest manifest may be failed/running, or its checksum/configuration may differ. Read the manifest reason and rerun successfully. File existence alone does not prove a valid current result. |
| Result opens with a provenance warning | The adjacent manifest or original campaign may be unavailable. Restore them when possible. A readable portable file does not imply that its source inputs could be revalidated. |
| Grid CSV does not load as a map | It contains spatial summaries. Use the grid NetCDF, which includes coordinates, both fields, differences and mask. |
| Requested map time is absent | Inspect `grid.time.values` and choose an exact available timestamp. Plotting never substitutes the nearest one. |
| Map is blank at a time | There may be no common finite cells. Check `n_common`, `valid` and the two pre-mask counts. The whole comparison can succeed while a particular time has zero coverage. |
| A map looks coarser or has more blank coastal cells than one source | It uses the selected reference grid and common finite mask. Bilinear sampling rejects any missing contributing corner; plotting does not fill those cells. |
| Multi-model station series rejects the inputs | Apply explicit event/lead selection and then `common_sample`. The plotting function requires identical observations. |
| Station series rejects a satellite track or several buoys | It requires one fixed location. Split stations or use scatter/geographic track analysis. |
| Fewer common pairs than in individual files | This is expected when coverage, QC or matching differs. Inspect the returned counts and report the common sample size. |
| A peak changed after matching | Accepted pairs may exclude the raw observed maximum or omit a model output time. Check native observations/model cadence and actual offsets before interpreting a physical peak error. |
| YAML runs, but the example notebook still plots Hs/old experiments | Adapt its experiment names, result variable, score columns and axis limits. Configuration changes do not rewrite analysis code. |

For a reproducible problem report, keep the YAML, `--describe` output, failing
manifest/error text, environment version and a small representative source file
when it can be shared. State the expected physical comparison and actual behavior.
