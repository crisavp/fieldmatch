# Your first complete analysis

This guide uses FieldMatch 0.3 and the supplied Harry data. Start with the notebook,
then use the recipes below to extend the study. The numerical comparisons and
plotting functions are the same whether you use a notebook or a Python script.

## 1. Make your own study folder

Activate your existing environment and change to the FieldMatch repository:

```bash
conda activate wave-models2
# Run the following commands from the FieldMatch repository directory.
fieldmatch doctor
python -c "import fieldmatch, sys; print(sys.executable); print(fieldmatch.__version__)"
```

The current Harry installation uses `wave-models2`; a new installation made from
`environment.yml` uses an environment named `fieldmatch`. Use the environment
where the package is installed. If you need Jupyter or Matplotlib, install the
optional dependencies from the repository directory:

```bash
python -m pip install -e '.[notebook]'
```

Keep your work separate from the example and previous audit. For the existing
sibling `fieldmatch` and `harry_storm` directories:

```bash
mkdir -p ../harry_storm/my_analysis
cp examples/harry_exploration.ipynb ../harry_storm/my_analysis/
cp examples/harry_campaign.yaml ../harry_storm/my_analysis/
cd ../harry_storm/my_analysis
python -m jupyterlab harry_exploration.ipynb
```

On another machine, choose any study folder and copy both files into it. In
Jupyter, select the kernel from your FieldMatch environment. If it is missing,
register it from the activated environment before launching Jupyter:

```bash
python -m ipykernel install --user --name wave-models2 --display-name 'Python (wave-models2)'
```

In your copied notebook, set:

```python
DATA_ROOT = Path('../data').resolve()  # Correct for harry_storm/my_analysis.
OUTPUT = Path('results').resolve()
CONFIG = Path('harry_campaign.yaml')
RUN_COMPARISONS = True
MAP_TIME = '2026-01-20T18:00'
HS_LIMITS = (0, 10)
DIFFERENCE_LIMIT = 2
```

`DATA_ROOT` must contain `buoys/` and `models/`; use an absolute path if your study
folder is elsewhere. The notebook already imports `Path` in this cell. Run the
cells from top to bottom, using **Run → Run All Cells** or Shift+Enter one cell at
a time. Reading the GRIB files takes time; a quiet cell is not necessarily stuck.

The notebook writes an effective `results/campaign.yaml`, replacing the template's
`data_root` and `outdir` with these settings. The comparison files go under
`results/comparisons/`. For standalone CLI use, edit those two paths directly in
your YAML instead; notebook settings do not change a CLI invocation automatically.

## 2. Decide what you are testing

Begin with a few comparisons whose purpose you can state in one sentence:

| Question | Comparison | Restriction that makes it interpretable |
|---|---|---|
| Which product reproduces BA08 storm evolution? | Analysis, hindcast, ERA5 versus the buoy | Same observation records and storm window |
| Where do the model fields differ? | ERA5 minus analysis | Exact common times, declared reference grid and common finite cells |
| How do the two forecasts differ? | January 18 AIFS minus conventional forecast | Same initialization and exact common valid times |
| Is a discrepancy an interpolation/sampling effect? | Two matching policies for the same model | Report both coverage and scores on identical observations |

The supplied notebook implements the first three questions. The recipes below
cover the fourth and additional variables. The default example evaluates
**18–22 January 2026 inclusive, UTC**. A date-only end includes that entire day.
Use explicit timestamps when you need exact boundaries.

Keep Hs, peak period, direction and wind as separate scientific quantities. A
low overall RMSE does not establish accurate peak timing or severe-wave duration.
Analysis is a reference product, not observational truth; agreement with potentially
assimilated observations is not automatically independent validation.

## 3. Inspect the datasets before interpreting a result

After the notebook has created `results/campaign.yaml`, run these from your study
folder in an activated terminal:

```bash
fieldmatch scan results/campaign.yaml
fieldmatch vars results/campaign.yaml ba08
fieldmatch vars results/campaign.yaml analysis
fieldmatch vars results/campaign.yaml aifs18 --all
```

If you are using the CLI without the notebook, substitute your edited YAML path.
Dataset names come from **your YAML**; the example uses `analysis`, whereas the
original audit configuration used `ecmwf_an`. They are user-chosen labels.

Check file coverage, units, forecast initialization, grid spacing and all reported
cadences. Inspect reader QC and missing filters in the output provenance. Verify
buoy positions and sensor conventions from the provider. In the Harry delivery:

- BA08 has wave and wind measurements; BA04's absent wind sensor is not a usable
  zero-wind record.
- The hindcast has wave fields, but no atmospheric u10/v10 components.
- The supplied AIFS wave file has Hs but not the peak period used in the buoy
  comparison. Mean wave direction is in its separate wind delivery.
- `pp1d → tp` and `mwd → wave_dir` are source-name mappings. `mwp → tm01` or
  `mwp → tm02` would change the physical meaning and must not be used.
- Neutral wave-forcing wind and atmospheric wind need separate treatment.

These are properties of these files, not assumptions to apply to every delivery.

## 4. Read and edit the comparison configuration

The complete runnable template is [harry_campaign.yaml](../examples/harry_campaign.yaml).
The examples in this section are **fragments to edit inside its existing mappings**;
do not paste a second `datasets:` or `comparisons:` root into the file. Duplicate
YAML keys can silently replace earlier definitions in the current parser.

### Shared defaults and per-variable choices

```yaml
matching_defaults:
  tolerance_minutes: 30
  space_method: bilinear
  time_tie: earlier

comparisons:
  buoy_analysis:
    obs: ba08
    model: analysis
    variables:
      hs: {}
      tp:
        tolerance_minutes: 0
      wave_dir: {}
```

`{}` means use the shared defaults. Only `tp` requires an exact timestamp here.
This demonstrates configuration syntax; zero tolerance is an experiment choice,
not a physical requirement for period. Every variable gets independent matching,
accepted rows and output files. There is no requirement that Hs and period have
the same valid samples.

The model dataset already contains `rename: {pp1d: tp, mwd: wave_dir}`, so source
names do not need to be repeated in comparison blocks. The scalar/circular/vector
sampling behavior follows the physical quantity; do not average directions as
ordinary scalar numbers.

### Model-to-model choices

```yaml
comparisons:
  analysis_era5:
    reference: analysis
    model: era5
    time_basis: valid_time
    variables:
      hs: {space_method: bilinear}
```

`reference` sets both the target grid and the field being subtracted. The result
is **model minus reference**, here ERA5 minus analysis. Both fields use the common
finite mask at each time. Finer interpolation does not add physical resolution.

Grid comparisons always use exact shared valid times. `time_basis` is required:

| Value | Additional restriction |
|---|---|
| `valid_time` | None; initializations/leads may differ and are retained |
| `same_init` | Both initializations must be finite and equal |
| `same_lead` | Both leads must be finite and equal |

Observation `tolerance_minutes` does not apply to grids. A variable-level tolerance
on a grid comparison is rejected. At a common valid time, equal lead normally also
means equal initialization. These options alone do not produce a lead-time skill curve.

## 5. Inspect the effective settings, then run

For one named comparison:

```bash
fieldmatch compare results/campaign.yaml buoy_analysis --describe
fieldmatch compare results/campaign.yaml buoy_analysis --format both
fieldmatch compare results/campaign.yaml analysis_era5 --describe
fieldmatch compare results/campaign.yaml analysis_era5 --format both
```

The copied notebook already runs all declared comparisons. Do not run these again
unless you want to recompute them. For a script of your own, this is the same batch
workflow used by the notebook:

```python
from pathlib import Path
from fieldmatch.campaign import load_campaign
from fieldmatch.comparison import resolve_comparisons, run_comparisons

campaign = load_campaign('results/campaign.yaml')
specs = [spec for name in campaign.comparisons
         for spec in resolve_comparisons(campaign, name)]
completed, failed = run_comparisons(campaign, specs, formats=('netcdf', 'csv'))
if failed:
    raise RuntimeError(failed)
```

Check the acceptance counts and failures. No matching times, missing fields and
missing contributing grid cells are different problems. Increasing the time
tolerance does not fix a missing physical variable or an observation before the
forecast begins.

Use `--format both` while learning:

| Comparison | NetCDF | CSV |
|---|---|---|
| Observation/model | Accepted pairs, coordinates and metadata | The same accepted pairs |
| Model/model | Aligned fields, signed difference, mask, counts and forecast coordinates | Per-time area-weighted spatial difference summaries |

The grid CSV cannot recreate a map. Keep `.manifest.json` beside either format.
Repeating a comparison replaces its outputs; requesting one format also removes
the old counterpart format for that comparison.

## 6. Load results and check the match decisions

Continue in a notebook cell or script. This helper finds outputs by their saved
comparison name rather than requiring you to type long filenames. It works with
the unmodified example and with added variable blocks:

```python
import json
import numpy as np
import pandas as pd
from fieldmatch.results import open_result

campaign = load_campaign('results/campaign.yaml')

def result(name, variable='hs'):
    matches = []
    for path in campaign.outdir.glob('*.manifest.json'):
        record = json.loads(path.read_text())
        spec = record.get('effective', {})
        if spec.get('comparison') == name and spec.get('variable') == variable:
            if record['status'] != 'complete':
                raise RuntimeError(record.get('reason', record['status']))
            matches.append(record['outputs']['netcdf'])
    if len(matches) != 1:
        raise ValueError(f'Expected one {name}/{variable} result, found {len(matches)}')
    return open_result(matches[0])

analysis = result('buoy_analysis')
print(analysis[['time', 'model_time', 'dt', 'hs', 'model_hs']].to_dataframe().head())
print('Accepted:', analysis.sizes['obs'])
print('Maximum absolute offset (minutes):', float(abs(analysis.dt).max()) / 60)
print({k: v for k, v in analysis.attrs.items()
       if k.startswith('n_') or k in {'space_method', 'time_tolerance_minutes'}})
effective = json.loads(analysis.attrs['effective_comparison'])
print(effective['reader_provenance'])
```

`time` is observation time. `model_time` is the model time actually used.
**`dt = observation time − model time`, in seconds.** Positive dt means an earlier
model value was used. These offsets matter when the storm changes rapidly.

`open_result` checks the adjacent manifest, saved specification and output checksum,
and revalidates campaign/input metadata when available. It does not rematch data.
A copied file without its manifest has weaker provenance and produces a warning.

## 7. Compare models on identical observations

Before ranking models, explicitly choose the event or lead window and intersect
their observation IDs. This uses the example's three buoy results:

```python
from fieldmatch.common import common_sample
from fieldmatch.pairstats import pair_stats

pairs = {label: result(name) for label, name in {
    'Analysis': 'buoy_analysis',
    'Hindcast': 'buoy_hindcast',
    'ERA5': 'buoy_era5',
}.items()}

def event(ds, start='2026-01-18', end='2026-01-23'):
    keep = (ds.time.values >= np.datetime64(start)) & (ds.time.values < np.datetime64(end))
    return ds.isel(obs=np.flatnonzero(keep))

aligned, counts = common_sample({name: event(ds) for name, ds in pairs.items()})
print(pd.DataFrame(counts).T)
if not next(iter(aligned.values())).sizes['obs']:
    raise ValueError('No common observations remain for this experiment')
scores = pd.DataFrame({name: pair_stats(ds.hs.values, ds.model_hs.values)
                       for name, ds in aligned.items()}).T
print(scores[['n', 'bias', 'rmse', 'si', 'corr']])
scores.to_csv('results/common_hs_scores.csv', index_label='model')
```

Bias is model minus observed. RMSE and bias have the variable's units. SI is
centered error standard deviation divided by observed mean; correlation describes
association, not agreement. For directions use `pair_stats(..., circular=True)`,
or `stats_table(ds)`, which selects circular behavior from the declared variable.

For a quick score on an individual file, use `fieldmatch stats <pairs.nc>`.
That command scores that file's sample; separately scoring several files does
**not** intersect them automatically. `--by-lead --lead-bin 24` bins one pair file
by its actual forecast lead, but does not equalize samples between models.

### A severe-wave subset

Apply one observed threshold to the already aligned samples:

```python
first = next(iter(aligned.values()))
keep = np.flatnonzero(first.hs.values >= 6.0)
severe = {name: ds.isel(obs=keep) for name, ds in aligned.items()}
severe_scores = pd.DataFrame({name: pair_stats(ds.hs.values, ds.model_hs.values)
                              for name, ds in severe.items()}).T
print(severe_scores)
```

Six metres is a stated descriptive choice, not a universal storm threshold.
Report the subset count beside the full-sample result. Do not select a separate
model-based threshold for each model and call the resulting scores a fair ranking.

### Sampled peak magnitude and timing

This measures peaks in the aligned pairs. It does not recover omitted observations
or unsampled model output times:

```python
peak_rows = []
for name, ds in aligned.items():
    io = int(ds.hs.argmax('obs').item())
    im = int(ds.model_hs.argmax('obs').item())
    observed_time = ds.time.values[io]
    model_time = ds.model_time.values[im]  # Actual model time, not observation time.
    peak_rows.append(dict(
        model=name,
        observed_peak_m=float(ds.hs.values[io]),
        sampled_model_peak_m=float(ds.model_hs.values[im]),
        observed_peak_time=str(observed_time),
        model_peak_time=str(model_time),
        lag_hours=float((model_time - observed_time) / np.timedelta64(1, 'h')),
    ))
print(pd.DataFrame(peak_rows))
```

A positive lag means the sampled model peak occurs later. With tied maxima,
`argmax` selects the first occurrence; a broad plateau can make a single peak-time
number unstable. Inspect the series and native cadence alongside this table.

## 8. Draw and customize figures

### Common-observation station series and scatter

```python
import matplotlib.pyplot as plt
from fieldmatch.plotting import time_series, scatter, save_figure

fig, ax = time_series(aligned, title='BA08: common Hs observations')
ax.set_ylim(0, 10)
save_figure(fig, 'results/my_buoy_series.png')
plt.show()

fig, axes = plt.subplots(1, 3, figsize=(14, 4), constrained_layout=True)
for ax, (name, ds) in zip(axes, aligned.items()):
    scatter(ds, ax=ax, title=name)
    ax.set(xlim=(0, 10), ylim=(0, 10))
save_figure(fig, 'results/my_scatter_panels.pdf')
plt.show()
```

`time_series` requires one fixed station and identical observations between
models. It does not silently align samples. Default markers show matched values
at observation times. `connect=True` adds visual line segments, not interpolated
model values. For tracks, use scatter plots or your own geographic scatter;
the station-series helper is not a satellite track analysis routine.

### Maps and difference panels

```python
from fieldmatch.plotting import comparison_panels, field_map
from fieldmatch.grids import grid_stats

grid = result('analysis_era5')
print(grid.time.values)  # Choose a timestamp that actually exists.
fig, axes = comparison_panels(grid, '2026-01-20T18:00',
                              clim=(0, 10), difference_limit=2)
save_figure(fig, 'results/my_model_panels.png')
plt.show()

fig, ax = field_map(grid, '2026-01-20T18:00', field='difference', clim=(-2, 2))
ax.set_title('ERA5 minus analysis — Hs, 20 January 18 UTC')
save_figure(fig, 'results/my_difference.pdf')
plt.show()

spatial = grid_stats(grid)
print(spatial[['mean_difference', 'rms_difference', 'valid_area_fraction', 'n_common']]
      .to_dataframe().head())
```

Maps require an exact time; there is no hidden nearest-time choice. Blank regions
have no common finite value. The two field panels share colour limits; signed
differences use a symmetric scale. When comparing several dates, reuse the same
limits. Grid statistics use spherical midpoint-cell area weights and the saved
common mask. Inspect changing valid area before interpreting temporal trends.

`field_map` plots fields from an already prepared grid comparison, including its
common mask. It is not a raw-file viewer. Maps use regional geographic axes with
an aspect correction, not a cartographic projection or downloaded coastlines.
Use a separate geographic plotting tool if your final map needs those features.

## 9. Test a scientific decision without losing the original

To compare bilinear and nearest spatial matching, add a separate named comparison
under the existing `comparisons` mapping:

```yaml
  buoy_analysis_nearest:
    obs: ba08
    model: analysis
    variables:
      hs: {space_method: nearest}
```

Keep `buoy_analysis` unchanged. For time-tolerance sensitivity, use another name
with `hs: {tolerance_minutes: 0}` or your justified alternative. For model/model
grid sensitivity, change the spatial method or reference grid in a separately
named grid comparison; grid time tolerance is not supported.

**After editing the campaign, rerun all its comparisons.** Current freshness
fingerprints include all comparison declarations; even adding an unrelated group
can make older results from that campaign fail validation. The notebook's normal
run-all workflow handles this. Merely rerunning plotting cells cannot repair stale
comparison outputs.

Then assess both coverage and differences on shared observations:

```python
variants = {'Bilinear': result('buoy_analysis'),
            'Nearest': result('buoy_analysis_nearest')}
shared, removed = common_sample(variants)
print(pd.DataFrame(removed).T)
print(pd.DataFrame({name: pair_stats(ds.hs.values, ds.model_hs.values)
                    for name, ds in shared.items()}).T)
```

If a policy changes which observations survive, its native-sample score and its
common-sample score answer different questions. Keep both. Wider tolerances can
include larger storm phase errors; they are not a free increase in evidence.
Bracketed linear-time interpolation is not currently a FieldMatch matching mode.

For a clean new experiment, copy the YAML to another study/output folder and use
a distinct campaign name. That preserves the earlier configuration and results.
For cosmetic changes only, set `RUN_COMPARISONS = False` in the notebook and rerun
it: saved data are checked and figures regenerated. Figure paths are overwritten
when reused; choose new names to retain alternative layouts.

## 10. Extend to another variable or dataset

- **Peak period:** add `tp: {}` to the buoy comparisons whose models supply pp1d/tp.
  Load with `result('buoy_analysis', 'tp')`. Adapt score/plot limits to seconds.
- **Wave direction:** add `wave_dir: {}` where available. The same plot helpers
  recognize the declared quantity; use circular statistics. Direction differences
  are wrapped to [-180,180); values near the seam need careful interpretation.
- **Wind:** use models with compatible u10/v10 and a station with valid wind data.
  Inspect sensor height/stability metadata before physical interpretation.
- **Another buoy:** add a dataset with its verified position and file glob, and new
  comparison names. Run separate station figures; do not mix positions in a single
  `time_series` call.
- **An altimeter:** choose the matching reader, inspect its QC and coastal filtering,
  then compare Hs against selected models. Dense track pixels are correlated;
  use track/segment-level uncertainty or aggregation for scientific inference.

Changing YAML alone does not rewrite the notebook's hard-coded experiment names,
Hs columns or metre-based figure limits. Its `result(name, variable)` helper is
general, but change those analysis cells when changing the question. Keep new
scientific logic in your notebook/script rather than editing the library.

## 11. Decide whether your conclusions are supported

For Harry, a useful first analysis includes the full-sample errors, a severe-wave
subset, storm evolution, peak magnitude and timing, and one spatial comparison.
Check that the interpretation survives reasonable matching/sampling choices.

- A peak from accepted pairs is the peak on that **matched sample**, not necessarily
  the full observed peak or the maximum of all model outputs. Examine unmatched
  observations and native model cadence before interpreting missing extremes.
- Hs squared is related to wave energy density, but it is not coastal damage or
  wave-power validation. Period definitions, spectra and coastal transformation
  matter for stronger physical claims.
- Hundreds of neighbouring pixels or successive half-hour observations are not
  hundreds of independent storm realizations. Basic FieldMatch scores do not
  include uncertainty intervals. Event/track/block resampling belongs in the
  analysis, with its block choice stated.
- A same-initialization comparison helps separate forecast differences from lead
  differences. One storm still cannot establish general model superiority.

Keep a short interpretation next to each figure: question, sample/window, matching
policy, evidence, and the most relevant limitation. This makes the analysis easier
to review than a large set of unexplained figures.

## 12. Save a reproducible study

Keep your edited notebook/script, the effective campaign YAML, source metadata,
comparison NetCDF/CSV files and manifests, and figure sidecars together. Record
which provider information is still missing. Avoid modifying raw deliveries in place.

`save_figure` records input-result hashes, comparison metadata, plot settings, axes
and an output hash. Your notebook remains necessary to explain additional sample
filters and custom Matplotlib edits; the sidecar is not a complete replacement
for analysis code. Save an executed notebook so the tables and decisions are
visible alongside the code.

Next: [troubleshooting](troubleshooting.md), [campaign options](campaign-reference.md),
[output fields](output-formats.md), [grid and plotting details](grids-and-plotting.md).
