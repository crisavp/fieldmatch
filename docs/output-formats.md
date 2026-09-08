# Output formats and provenance

One quantity per pair table. A batch has independent tables; missing wind or a
different wind timestamp cannot remove valid Hs observations.

| Column | Meaning |
|---|---|
| `obs_id` | Reader kind, source-content SHA-256, original flattened record index |
| `record_index`, `source_file` | Original record and delivery name |
| `time`, `lat`, `lon` | Observation timestamp and position |
| `hs`, `model_hs` (or another declared quantity) | Observed and matched model values |
| `model_time` | Actual selected model valid time |
| `time_offset_seconds` | Observation time minus model valid time, seconds |
| `init`, `lead_hours` | Actual forecast provenance, present only for forecast datasets |
| `x_*` | Explicitly requested extra observation variables |

With dataset option `retain_qc: true`, the principal provider quality fields
also use `x_*` names and retain their flag metadata. They are context variables,
not additional quantities scored automatically. Apply and document an explicit
mask before calling `stats_table` for a QC sensitivity result.

Only finite pairs are retained. Counts separate invalid time/position, missing
observation values, time rejection, and missing/out-of-grid/undefined model
values. Counts sum to the comparison's input cloud size; reader QC counts may
refer to the original files before region/time cropping.

## CSV and NetCDF

For observation/model comparisons, CSV is default: ISO timestamps, explicit `NaN`, full double-precision decimal
formatting (`%.17g`). NetCDF is available with `--format netcdf` or `both`.
Strings are not compressed as NetCDF variable-length strings. Numeric variables
are compressed. The formats derive from exactly the same pair Dataset.

Named comparisons use `<comparison>__<variable>`, for example
`ba04_operational__wave_dir.nc`. The comparison key already identifies both
datasets, while the manifest records the campaign and complete configuration.
Direct unnamed collocations use `<obs>__<model>__<variable>` and append an
explicit lead-window suffix when applicable. The campaign output directory is
therefore the campaign namespace; use a separate output directory for each
study. Repeating the same comparison replaces that result and its manifest; use
different named comparisons to retain policy sensitivity experiments. Temporary
files and a running/complete/failed manifest prevent a failed rerun from
masquerading as a successful current result.

## Why are there JSON files?

JSON is a plain-text format for structured records. FieldMatch writes these files
automatically; edit your YAML to change a comparison, not its JSON records.

| File | Purpose | What you should do |
|---|---|---|
| `.fieldmatch/*.manifest.json` | Records settings, sources, software, accepted/rejected counts, completion status and checksums. Readers use it to detect incomplete, modified or stale results. | Copy the whole results folder, including its hidden `.fieldmatch` directory. |
| `.fieldmatch/*.png.figure.json` | Records source-result hashes, plotting details, axis limits and figure checksum. Helps trace a figure back to its inputs. | Keep it for reproducibility; an image viewer does not need it. |

A checksum is a fingerprint of file contents. It helps detect changes; it does not
prove that the scientific decisions were correct. Manifests preserve those decisions
so you can review them. They are records, not substitutes for the data or the study script.

`fieldmatch run campaign.yaml --describe` displays resolved configuration in the
terminal without creating these files. It does not check that the underlying data
are readable or suitable; use `scan` and review the actual run diagnostics too.

## Provenance storage

`.fieldmatch/<stem>.manifest.json` saves the effective comparison, including defaults:

- source/quantity mapping, units, direction conventions and reader/QC provenance;
- matching policy, initialization/cycle/lead selection, actual matched leads;
- input file paths, sizes and content hashes;
- FieldMatch version and implementation source hashes;
- exact region/period, accepted/rejected counts and pair metadata;
- execution specification digest and output checksums.

NetCDF also embeds the effective specification. CSV metadata are restored from
the manifest when read by the CLI. `stats` verifies manifest state, the saved
specification digest, table checksum and current campaign/input metadata when
available. It uses the saved result, not today's default matching settings.
A portable old CSV without its manifest remains readable with a warning; its
scientific provenance cannot be reconstructed. Input freshness checks use
path/size/mtime; content fingerprints in the manifest support independent
stronger verification when needed.

## Common samples and statistics

`fieldmatch.common.common_sample({name: dataset, ...})` intersects finite pairs
by observation ID, checks identical declared quantity and observation/QC
contracts and observation values, and returns `(aligned, counts)`. Set desired
event/lead restrictions before calling it. It does not automatically equalize
forecast lead or select storm phases.

`fieldmatch stats pairs.csv --output scores.csv` produces basic scalar/circular
scores. `--by-lead --lead-bin 24` reports lead bins. Different sample sizes do
not support a fair model ranking without alignment. Bootstrap/block choices,
threshold exposure and physical interpretation belong to the analysis script.

## Migration from 0.1

- Add `--variable hs` (repeat for other quantities), or define named comparisons.
- Update filenames to include the quantity. Multiple quantities produce multiple
  outputs; there is no combined-row compatibility mode.
- In Python, pass `variable='hs'`; `variables=['hs']` is retained as a single-item
  spelling. Multiple variables must be separate calls. No shared variable is an
  error, not a request to sample every model field.
- Nearest-lead fallback defaults to zero tolerance. Distinct forecasts at one
  valid time are rejected; narrow the dataset selectors.
- Scalar-step valid times, conflicting file partitions, undefined directions
  and exact wet grid nodes are corrected. Expect intentional changes in those
  formerly incorrect cases.
- CSV numeric precision increases from four decimals to full precision.
- Existing old pair files remain readable where unambiguous; their original
  matching errors cannot be repaired by recalculating statistics. Re-collocate.

## Grid comparisons (0.3)

Grid NetCDF has only three scientific data variables on `(time, lat, lon)`:
`reference`, `candidate`, and `difference`. The first two preserve each source's
independent availability. `difference` exists only where both are finite and is
candidate minus reference, wrapped to [-180,180) for directions. Forecast
initialization and lead are retained as compact metadata and expanded only when
`forecast_table(result)` is called; they do not clutter the scientific fields or
coordinates. Valid-time-only datasets omit them. The common mask and counts are derived when
statistics or comparison panels are made, rather than stored as redundant fields.

Grid CSV contains `time` plus per-time spherical-area-weighted mean and RMS
differences, valid area fraction, and common-cell count. It cannot reconstruct field plots;
use the NetCDF. Both formats have the same hidden provenance directory convention with
input hashes, effective settings, source grids and source-code hashes.
Use `fieldmatch.results.open_result` to validate and load portable NetCDF or
observation-pair CSV. Figure sidecars (`.figure.json`) preserve result-file hashes,
comparison metadata, plot limits, axes and the figure checksum.

## Reuse and portability

Changing any comparison declaration can invalidate existing results from the
same campaign; rerun all its comparisons or keep separate campaign versions.
Reusing only plots (`python /path/to/analyze.py`) is appropriate
when scientific inputs/settings are unchanged. A figure sidecar identifies its
source result and display settings; keep the analysis code as well to document
additional sample selection and custom plotting.

## Read provenance without opening JSON

```bash
fieldmatch info /path/to/result.nc
fieldmatch info /path/to/figure.png
fieldmatch info /path/to/result.nc --details
```

New records live in a hidden `.fieldmatch` subfolder beside results or figures.
FieldMatch manages them; info is the user-facing view. Comparison info checks the
saved status, specification, result checksum and current inputs where available.
Figure info checks the PNG checksum and displays its recorded sources/settings;
it does not revalidate every source file. Missing records are reported explicitly.

Existing adjacent JSON records remain readable. A new hidden record takes precedence
over an old sidecar for the same result, including failed/running records. Reruns
write the new layout; existing sidecars are not automatically deleted. Copy the whole
results folder including hidden files when sharing. Hiding metadata reduces clutter;
it does not make it secret or remove the need to preserve it.
