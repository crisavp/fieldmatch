# Campaign reference

Required: `campaign`, `region`, `period`, `datasets`. Optional: `data_root`,
`outdir`, `matching_defaults`, `comparisons`. Unknown keys are errors. Paths resolve
relative to the campaign file; a relative dataset path is under `data_root`.
Date-only end bounds include the full UTC day; timestamps are exact bounds.
Names may contain letters, digits, periods, underscores and hyphens.

```yaml
campaign: example
data_root: ./data
outdir: ./results
region: {lonmin: 8, lonmax: 18, latmin: 34, latmax: 44}
period: [2026-01-15, 2026-01-22]
datasets:
  buoy: {kind: buoy_ispra, path: buoy.csv, lat: 38.5, lon: 9.0}
  model: {kind: grib, path: 'model/*.grib', init: '2026-01-18T00', rename: {pp1d: tp}}
matching_defaults:
  time_method: nearest
  tolerance_minutes: 30
  time_tie: earlier
  space_method: bilinear
  missing_corners: reject_nonzero_weight
comparisons:
  waves:
    obs: buoy
    model: model
    variables:
      hs: {}
      tp: {tolerance_minutes: 0}
```

`fieldmatch compare campaign.yaml waves --describe` shows resolved
settings. Omit `--describe` to execute. The positional command remains:
`fieldmatch collocate campaign.yaml buoy model --variable hs`.
Repeat `--variable` for separate outputs. `--obs-variable` and
`--model-variable` select source names for a single quantity.

## Matching settings

Precedence is library defaults → `matching_defaults` → settings directly under each
variable. The lower-level Python API also accepts explicit overrides. Each variable
is matched independently; `{}` uses the shared defaults. `variables` must be a
nonempty mapping, and unknown settings are errors. `compare --describe` returns
a list of fully resolved specifications. The named CLI command takes its scientific
settings from the configuration. The full result is saved, including defaults.

| Setting | Default | Meaning |
|---|---|---|
| `time_method` | `nearest` | Only nearest time is implemented; no hidden temporal interpolation |
| `tolerance_minutes` | 30 | Maximum absolute offset, independent of cadence; zero permits exact times |
| `time_tie` | `earlier` | `earlier` or `later` on an equal-distance time tie |
| `space_method` | `bilinear` | `bilinear` or nearest grid point; nearest spatial ties choose lower coordinate |
| `missing_corners` | `reject_nonzero_weight` | Ignore zero-weight corners; reject a missing contributing corner |
| `direction_resultant_min` | 1e-10 | Circular resultant must exceed this threshold, in [0,1] |
| `wind_direction_min_speed` | 1e-10 | Interpolated vector speed must exceed this threshold, m/s, for direction |

No spatial extrapolation or automatic nearest-*wet*-point filling is performed.
Nearest-time matching may accept an observation just outside the first/last
output time if within the declared tolerance; `dt` and `model_time` expose it.
Use period/lead restrictions or exact matching to limit the comparison further.

Direction thresholds detect numerical cancellation. A scientific exclusion for
light winds or small waves is a separate analysis decision, not implied by them.
All contributing wind components must be aligned before interpolation.

## Physical quantities and source selection

The small `quantities.py` table defines meanings, units and direction behavior.
Known aliases: `swh`→`hs`, `mwd`→`wave_dir`, `pp1d`→`tp`, `mwp`→`energy_period`,
`wind`→`neutral_wind_speed`, `dwi`→`neutral_wind_dir`. Except `swh`→`hs` in the
model loader, these are semantic definitions, not automatic renaming: declare
a dataset `rename` mapping, such as `{pp1d: tp}`, when model names differ.
Reader options handle observation source fields. The lower-level API and
`collocate` command retain explicit source arguments for custom experiments.

Default atmospheric `wind_speed`/`wind_dir` in the campaign runner use `u10` and
`v10`. Select a scalar model source explicitly when appropriate. Supplying a
source does not bypass unit/quantity checks or convert atmospheric wind to
neutral wind. Known incompatible definitions are errors even after renaming.
Unknown variables use scalar comparison with an explicit source identity; extend
`quantities.py` to give a new quantity checked units or circular behavior.
Provider units are preserved; missing units on known reader/canonical names use
the documented quantity contract and are marked as such. There is no automatic
unit conversion. Reader wind-height/stability metadata still need assessment
before treating a comparison as independent physical validation.

## Observation dataset options

`path` accepts a glob or list of globs. Identical basename/content deliveries
are deduplicated; duplicate stable observation IDs after reading are errors.

| Kind | Options |
|---|---|
| `altimeter_cmems` | `extra_vars` |
| `altimeter_s3` | `extra_vars`, `retracker` (`sar`/`plrm`), `min_dist_coast_km`, `open_ocean_only` |
| `altimeter_s6` | `extra_vars`, `retracker` (`mle`/`nr`), `band` (`ku`/`c`), `min_dist_coast_km`, `open_ocean_only` |
| `sentinel1` | `extra_vars`, `qc` |
| `ascat` | `extra_vars` |
| `buoy_ispra` | required `lat`, `lon` |

Defaults: 30 km exclusion where available, `open_ocean_only: true`, SAR `qc: true`.
CMEMS files have no coastal-distance guarantee; provenance reports no local
coastal filter. Missing requested coastal/surface fields in supported readers
are reported as unapplied. An unavailable filter is never implicitly satisfied.
Sentinel-6 numerical retracking is Ku-only. `extra_vars` copies source columns
under `x_`; inspect available axes with `fieldmatch vars`.

## Model dataset options

Kinds: `grib` or `netcdf`. Options: `rename`, `coords`, `init`, `lead`,
`lead_tol`, `overlap`. `coords` maps raw names to `time`, `lat`, `lon`;
`rename` maps raw variable names to chosen model names. `swh` is normalized to
`hs` before applying `rename`, for compatibility with existing campaigns.

- `init`: follow one initialization; valid times and actual leads are retained.
- `lead`: exact lead or `lo-hi` window across initializations; overrides `init`.
- `lead_tol`: default **0 hours**. Explicit positive values permit nearest-lead
  fallback only when there is no step inside the requested window. Actual leads
  are recorded. This is unrelated to observation-time tolerance.
- `overlap`: default **error** for distinct forecasts valid at the same time.
  Explicit `shortest_lead` chooses the freshest forecast and emits a warning.
  It does not resolve conflicting finite values for the same forecast.

Scalar and dimensional forecast steps must satisfy valid time = init + lead.
Same-variable time partitions combine without silently overriding later values.
Conflicting finite overlaps, units, grids or cross-variable provenance fail;
complementary missing cells and identical repeated values may combine.
Only rectilinear 1-D latitude/longitude grids are supported. Regridding is an
explicit external operation, not an automatic part of assembling files.

Configuration migration: rename top-level `matching` to `matching_defaults`; replace
comparison `variable: hs` with `variables: {hs: {}}`. Move comparison matching
settings directly under that variable and model source mappings into dataset
`rename`. The previous configuration spelling is rejected to keep one clear schema.

## Model-to-model groups

A group may instead contain exactly `reference`, `model`, `time_basis`, and
`variables`. Both datasets must be models. `reference` defines the target grid
and the subtracted field; the result is candidate (`model`) minus reference.
`time_basis` is required: `valid_time`, `same_init`, or `same_lead`.
All three use exact shared valid times; the latter two additionally require
matching finite initialization or lead coordinates. No implicit temporal
interpolation or tolerance applies to grid comparisons.

Grid variables accept only `space_method`, `missing_corners`,
`direction_resultant_min`, and `wind_direction_min_speed`. Shared spatial
settings come from `matching_defaults`; its observation time settings do not
apply. Variable-level time-tolerance settings on a grid group are rejected.
`compare --describe` shows the exact effective rules. See
[grid and plotting guide](grids-and-plotting.md) for examples.
