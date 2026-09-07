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
| `dt` | Observation time minus model time, seconds |
| `init`, `lead_hours` | Actual forecast provenance; analysis uses valid time and lead zero by convention |
| `x_*` | Explicitly requested extra observation variables |

Only finite pairs are retained. Counts separate invalid time/position, missing
observation values, time rejection, and missing/out-of-grid/undefined model
values. Counts sum to the comparison's input cloud size; reader QC counts may
refer to the original files before region/time cropping.

## CSV and NetCDF

For observation/model comparisons, CSV is default: ISO timestamps, explicit `NaN`, full double-precision decimal
formatting (`%.17g`). NetCDF is available with `--format netcdf` or `both`.
Strings are not compressed as NetCDF variable-length strings. Numeric variables
are compressed. The formats derive from exactly the same pair Dataset.

Both use `<campaign>_<obs>_x_<model>_<variable>`. Named comparisons append their
name. Explicit lead views append a lead-window suffix. Entire stems, including
periods in campaign names, are retained. Repeating the same comparison replaces
that result and its manifest; use different named comparisons to retain policy
sensitivity experiments. Temporary files and a running/complete/failed manifest
prevent a failed rerun from masquerading as a successful current result.

## Manifest: keep it with the CSV

`<stem>.manifest.json` saves the effective comparison, including defaults:

- source/quantity mapping, units, direction conventions and reader/QC provenance;
- matching policy, initialization/lead/overlap selection, actual matched leads;
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
- Nearest-lead fallback defaults to zero tolerance; shortest-lead overlap
  selection is opt-in.
- Scalar-step valid times, conflicting file partitions, undefined directions
  and exact wet grid nodes are corrected. Expect intentional changes in those
  formerly incorrect cases.
- CSV numeric precision increases from four decimals to full precision.
- Existing old pair files remain readable where unambiguous; their original
  matching errors cannot be repaired by recalculating statistics. Re-collocate.

## Grid comparisons (0.3)

Grid NetCDF contains `reference`, `candidate`, `difference`, `valid` (0/1) on
(time, lat, lon), plus per-time finite counts and available reference/candidate
initializations and leads. Both fields are masked to the same finite cells at
each time. Differences are candidate minus reference, wrapped to [-180,180)
for directions. `n_reference` and `n_candidate` are counts before common masking;
`n_common` counts accepted cells. A time with no common cells remains present,
with zero count, NaN fields/statistics, and zero valid area fraction.

Grid CSV contains per-time spherical-area-weighted mean and RMS differences,
valid area fraction and common-cell count. It cannot reconstruct field plots;
use the NetCDF. Both formats have the same adjacent manifest convention with
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
