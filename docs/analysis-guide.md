# A complete analysis from the terminal

The main example is a normal [Python script](../examples/analyze.py). Its `# %%`
markers also allow optional VS Code cells. Start with the terminal; no notebook
server, browser kernel configuration or personal environment name is assumed.

## 1. Install and copy the study template

Follow [installation](installation.md), activate your chosen environment and run
`fieldmatch doctor`. Copy `examples/analyze.py` and `examples/harry.yaml` into your
own study folder. Keep the previous studies and raw data separate.

Edit just the data path in your copy of `harry.yaml` first:

```yaml
data_root: /absolute/path/to/harry/data
outdir: results
```

For the Harry template, data_root contains `buoys/` and `models/`. The supplied
raw data are not distributed with the library. On a new study, replace the dataset
paths, reader kinds, positions, region and period as needed.

Set the plotting script's `CONFIG` to the absolute YAML path. This same setting
is used in terminal execution and cells. YAML `data_root` and `outdir` resolve
relative to the YAML; dataset paths resolve from data_root. CLI paths follow shell
rules, so use absolute paths when invoking commands from elsewhere.

## 2. Inspect before running

```bash
fieldmatch scan /path/to/study/harry.yaml
fieldmatch run /path/to/study/harry.yaml --describe
fieldmatch vars /path/to/study/harry.yaml analysis
```

Scan inventories data; describe prints all effective comparison settings without
running comparisons.

Names such as `analysis` and `ba08` are YAML keys, not built-in aliases. Check units,
all reported time cadences, forecast initialization and sensor coordinates. A zero
file count means you need to fix paths/coverage before proceeding.

The template's questions are deliberately limited:

- Analysis, hindcast and ERA5 versus BA08 on common observations.
- ERA5 minus analysis on the analysis grid at exact shared times.
- AIFS versus a conventional forecast from the same January 18 initialization.

The default window is 18–22 January 2026 inclusive, UTC. A date-only end includes
the whole day. Use explicit timestamps for exact time bounds.

## 3. Understand the scientific configuration

```yaml
# Fragment: edit inside the existing root mappings; do not duplicate YAML keys.
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
      tp: {tolerance_minutes: 0}
```

`{}` inherits defaults. The exact-period setting is illustrative, not mandatory.
Each quantity has independent accepted rows and files. Model source names are
mapped once with `rename`, e.g. `{pp1d: tp, mwd: wave_dir}` in the dataset.

Grid groups use `reference`, `model`, `time_basis` and `variables`. The reference
sets the grid and the subtracted field: **difference = model − reference**.
Both output fields use the common finite mask at each exact shared time.
`same_init` additionally requires equal initializations; `same_lead` requires equal
finite leads. `valid_time` permits different initializations/leads and records them.
Observation-time tolerance never applies to a grid comparison.

Inspect definitions instead of forcing names to match. ECMWF energy period is
not buoy Tm01/Tm02. Neutral wave-forcing wind is not automatically atmospheric wind.
The example hindcast has no atmospheric u10/v10, and the supplied AIFS wave file
has no pp1d/tp. Add variables only where the physical quantity exists.

## 4. Compute and save comparisons

```bash
fieldmatch run /path/to/study/harry.yaml
```

This runs every declared quantity and saves both NetCDF and CSV with manifests.
A failed comparison produces an explicit error; the other completed comparisons
remain identifiable by their manifests. Inspect rejection counts and reasons.

For observation comparisons, CSV and NetCDF contain the same finite pairs. For
grid comparisons, NetCDF contains fields/mask/forecast coordinates; CSV contains
per-time area-weighted spatial summaries. Keep the manifests beside the files.

Repeating `run` replaces matching outputs with the same names. After editing the
scientific YAML, rerun **all** its comparisons: current freshness fingerprints
include all declarations. A copied configuration with changed settings cannot
reuse an older output silently. Preserve separate campaigns/output folders for
separate experiments.

## 5. Print scores and see the figures

Set the following near the top of your copied script:

```python
CONFIG = Path('/absolute/path/to/study/harry.yaml')
SHOW = True
SAVE = True
```

Then run:

```bash
python /path/to/study/analyze.py
```

The script validates saved results, explicitly intersects observation IDs within
each station/quantity group, prints scores and plots. It never runs comparisons.
`SHOW` controls display through Matplotlib; `SAVE` controls all writes (PNG,
provenance JSON, score/count CSV and HTML gallery under `<outdir>/figures`).
Use `SHOW = False` on a headless machine. Use `SAVE = False` for display only.
Both flags are ordinary Python settings, identical in terminal and cell execution.

Edit `MAP_TIME`, `FIELD_LIMITS`, `DIFFERENCE_LIMITS` and `SEVERE_HS` for analysis
choices, then rerun the script. Map times must exist exactly. Changing scientific
matching choices in YAML requires `fieldmatch run` again. Saved figure names are
overwritten when you redraw; comparison files are not modified by plotting.

## 6. Optional VS Code interactive inspection

Install `.[interactive]`, enable VS Code's Python and Jupyter extensions, and select
your installed environment as the Interactive Window kernel. No JupyterLab server
is needed. Run the settings/functions cell, then the load/plot cell. The script
contains no environment detection, argument parsing or alternate interactive path.
`CONFIG` is the same explicit absolute path for both ways of running it.

Inspect `tables`, `pairs`, `grids`, `analysis` and `campaign`, or add cells below:

```python
print(tables.keys())
station = pairs[('ba08', 'hs')]['buoy_analysis']
print(station[['time', 'model_time', 'dt', 'hs', 'model_hs']].to_dataframe().head())
```

`time` is observation time; `model_time` is sampled model time;
`dt = observation − model time` in seconds. Positive dt means an earlier model.

## 7. Extend the scientific analysis

The script's grouping and plotting is a starting example, not automatic scientific
interpretation. It groups all declared observation comparisons for a station and
quantity on a common sample. If your experiments have different purposes or lead
windows, select separate groups explicitly in your own analysis.

### A storm subset or matching sensitivity

Add a separate named comparison under the existing `comparisons` mapping:

```yaml
  buoy_analysis_nearest:
    obs: ba08
    model: analysis
    variables:
      hs: {space_method: nearest}
```

Rerun the campaign. For an isolated sensitivity comparison, select just its two
raw result tables from `analysis['loaded']`; avoid an unnecessary intersection with
other models:

```python
from fieldmatch.common import common_sample
from fieldmatch.pairstats import stats_table

selected = {name: analysis['loaded'][(name, 'hs')]
            for name in ['buoy_analysis', 'buoy_analysis_nearest']}
aligned, counts = common_sample(selected)
print(pd.DataFrame(counts).T)
print(pd.DataFrame({name: stats_table(ds)['hs'] for name, ds in aligned.items()}).T)
```

For event/lead restrictions, select `obs` rows before `common_sample`, using
`time`/`lead_hours`. Report both native coverage and common-sample scores: a policy
may change which observations survive. Wider tolerances admit larger phase offsets;
linear time interpolation is not currently a FieldMatch matching mode.

### Sampled peaks

```python
peak_rows = []
for name, ds in pairs[('ba08', 'hs')].items():
    io, im = int(ds.hs.argmax('obs').item()), int(ds.model_hs.argmax('obs').item())
    observed_time, model_time = ds.time.values[io], ds.model_time.values[im]
    peak_rows.append(dict(model=name, observed_peak=float(ds.hs.values[io]),
        sampled_model_peak=float(ds.model_hs.values[im]),
        lag_hours=float((model_time-observed_time)/np.timedelta64(1, 'h'))))
peaks = pd.DataFrame(peak_rows)
peaks.to_csv(campaign.outdir / 'sampled_peaks.csv', index=False)
print(peaks)
```

These are maxima **on the accepted common sample**. Check raw observations and
native model cadence before interpreting a missing extreme. Ties use the first
occurrence; a broad plateau makes one timing number unstable.

### More variables or datasets

Add `tp` or `wave_dir` where the models supply them, another verified buoy, or an
altimeter reader and its comparison groups. The script groups results by declared
variable and uses the quantity's scalar/circular statistics. Adjust its plotting
limits and titles for your question. Moving observations get scatter plots, not a
station time series. For track maps or more specialized diagnostics, use your own
analysis code and the returned datasets.

## 8. Interpret and preserve the work

Bias is model minus observed; RMSE has the quantity's units. Correlation is not
agreement. The six-metre severe-wave threshold is an explicit descriptive choice,
not a universal definition. A model reference is not truth, and potentially
assimilated observations are not automatically independent validation.

Scores alone do not quantify uncertainty. Successive buoy observations and nearby
satellite pixels are correlated; use stated event/track/block resampling when
making statistical claims. One storm does not establish general model superiority.
Hs squared relates to wave energy density but does not by itself quantify coastal
impact or wave power.

Keep the script, YAML, provider metadata, results and manifests, interpretation and
figure sidecars together. Figure sidecars retain result hashes and display settings;
your analysis code is still needed to reconstruct custom filters or artists. Do not
modify raw data in place. See [troubleshooting](troubleshooting.md) and the
[output reference](output-formats.md) when a result cannot be validated.
