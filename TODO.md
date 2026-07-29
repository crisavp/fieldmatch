# matchup — outstanding tasks

Ordered by priority. Context for each is in the git history / conversation of
2026-07-27..28.

## Must — data correctness (results are wrong or incomplete until these land)

1. ~~Port the IPF-aware Sentinel-1 quality check into `preprocess.py`.~~
   **DONE 2026-07-29.** Both pipelines now call the one shared helper
   `readers.s1_good_quality_values()`, which reads `flag_meanings` from the
   file instead of hardcoding a value. Verified:
   - **legacy archive unchanged** — 40 real IPF 003.31 collocated files give
     byte-identical output (flag_meanings `good medium low poor` → keep {0},
     exactly the old rule); also pinned by tests.
   - **modern files fixed** — an IPF 004.02 Harry scene through the archive
     path: old rule kept 3 343 (the `no_data` pixels), new rule keeps 40 481
     (`good` + `acceptable`).
   `tests/test_s1_quality.py` pins both conventions, the missing-metadata
   fallback (strict legacy `{0}`), and the legacy-unchanged guarantee.
   First step of item 10: one implementation of this quirk, two consumers.

2. ~~Fix circular interpolation of `wind_dir` / `mwd` / `wave_dir`.~~
   **DONE 2026-07-28** — see the decision record below.

3. ~~`harry.yaml` misses files that exist only under `WIND/`.~~ (Q5)
   **DONE 2026-07-29.** Every instrument now globs both `WAVE/` and `WIND/`;
   `campaign.Dataset.files()` de-duplicates by `(basename, size)` so the
   repeated CMEMS L3 copies are counted once. Recovered: CryoSat-2 1→2 files,
   Sentinel-3 3→5, Sentinel-6 3→5 (also picked up the stray ALTIKA file
   misfiled under `WIND/SENTINEL-3/`). Observations in box: cryosat2 196→367,
   s3 616→966. Methodology unchanged; see the results note below.

4. ~~Land / coastal masking for altimeters is absent.~~ (Q7)
   **DONE 2026-07-29.** S3 and S6 now drop observations that are not open sea:
   `dist_coast >= 30 km` (the variable is NEGATIVE over land, so one threshold
   rejects land and the coastal strip together) **and** surface type resolved
   by `flag_meanings` to open ocean. Tunable per dataset in the campaign file
   (`min_dist_coast_km: 50`, `open_ocean_only: false`) — the reader kwargs pass
   straight through, so this is Q8 tier 2 for these two options already.
   Every output records `land_mask` (the exact expression applied) and
   `n_rejected_coastal`.

   **It mattered a lot.** Sentinel-3 was the worst-scattering altimeter and the
   cause was coastal contamination, not the retracker:

   | s3 × ecmwf_an, hs | n | bias | rmse | SI | corr |
   |---|---|---|---|---|---|
   | before | 729 | −0.13 | 0.61 | 0.232 | 0.961 |
   | after (30 km) | 550 | −0.11 | **0.34** | **0.113** | **0.990** |

   RMSE and SI roughly halved. S3 is now consistent with the other altimeters
   instead of an outlier. CMEMS L3 products (Jason-3, SARAL, CryoSat-2, HY-2B/C,
   SWOT) carry no `dist_coast` or surface type at all, so the filter cannot be
   applied to them; they record `land_mask: none (...)` rather than implying a
   mask that never ran. Their numbers are unchanged. **Open question**: whether
   CMEMS's upstream editing is equivalent — if not, the CMEMS-based results
   still contain coastal contamination that S3 no longer has, which is an
   inconsistency between instruments in the same table.

5. ~~Forecast and AIFS lead time is discarded.~~ (Q6)
   **DONE 2026-07-29.** `time` is now always the *valid* time, with `init` and
   `lead_hours` kept as coordinates through the merge and written as columns
   in every collocated output. Two resolution modes:
   - `init: <timestamp>` — follow ONE forecast across all its leads.
   - `match --lead <window>` — a lead **window** across EVERY init in the
     glob: `'24'` (single lead) or `'12-35'` (forecast day 1). The window is
     the primitive; a single lead is the degenerate case `(L, L)`. Stays lazy:
     one 2-D field per (init, step) kept, never the whole cube.
   Filter inits by hour through the glob (`forecast_*_0_*.grib` = 00 UTC only);
   campaign datasets `forecasts`, `forecasts_00z`, `aifs_all` do this.
   Mixing inits without choosing is refused with a message naming both
   options, instead of silently dropping 31 of 32 AIFS inits.
   `cstats --by-lead [--lead-bin]` groups statistics into lead bands.

   **Prefer a window to a single lead.** A constant-lead series inherits the
   *init* spacing, so its default time tolerance is half of that (±6 h for
   12-hourly inits) — enough slop to flip the sign of a bias. A day window
   yields hourly valid times and ±30 min. Where a window is wider than the
   init spacing, several forecasts cover the same valid time; the shortest
   lead wins and a warning says the sample is no longer a clean tiling.
   With daily inits, +12–35 h tiles the timeline exactly and warns nothing.

6. **Characterization test for the archive pipeline before any refactor.**
   Collocate ~3 known ASCAT files, save the output, assert byte/statistical
   equality afterwards. Required because `wfetch` consumes the merged product
   by exact filename glob — no test, no safe refactor.

## Must — transparency (Q8, tier 1: make choices visible before configurable)

7. ~~Record provenance in every collocated output.~~
   **DONE 2026-07-29.** Every reader emits a record — `<var>_source`,
   `<var>_filter` (including `none (<flag> not present in this product)` when
   a product simply has no flag), `land_mask`, `n_read`, `n_rejected_qual`,
   `n_rejected_coastal`, plus reader-specific notes (S1 records the IPF
   version and that `owiEcmwf*` is the CMOD first guess; buoys record the
   configured position and any all-zero column dropped). `match` adds campaign,
   datasets, file counts, region, period, lead window, timestamp and version.
   `campaign.combine_provenance()` sums the COUNT attributes across files
   instead of inheriting the first file's (which is what `xr.concat` does) and
   flags disagreement as `MIXED: a | b`, so a delivery mixing two processor
   versions cannot look uniform.

8. ~~`scan` reports rejection counts per dataset.~~
   **DONE 2026-07-29.** Each obs block now shows `rejected:` (quality,
   coastal/land, of N read), the `land mask:` expression, and an `UNFILTERED:`
   line naming variables with no quality flag in the product. Multi-init
   forecast archives are reported as a note explaining `--lead`, not as
   `UNREADABLE`.

   **Found by doing this**: none of S3's three quality flags
   (`swh_ocean_qual_01_ku`, `wind_speed_alt_qual_01_ku`, `sig0_ocean_qual_01_ku`)
   exist in these files, so **S3 is coastal-masked only, never quality-masked**.
   Previously only the wind flag had been confirmed absent.

## Should — usability (Q1)

9. ~~`scan`: report the model timestep **per variable** (waves and winds have
   different cadences in the same cube, so one number would mislead) and the
   time tolerance derived from it; reformat the report as per-dataset blocks
   instead of ~150-char rows that wrap in a normal terminal.~~
   **DONE 2026-07-28.**

## Should — consolidation (after the vacation, not before)

10. **Make `preprocess.py` ASCAT/S1 functions thin wrappers over
    `readers.py`.** One implementation of each format quirk feeding both
    pipelines. Blocked by (6). Do *not* merge the pipelines themselves:
    `collocate.py`/`merge.py`/`ledger.py` serve the incremental multi-year
    archive; `collocate_track.py` serves interactive single-campaign work.
    Two access patterns, two strategies — legitimate, keep both.
    Reconcile carefully:
    - legacy keeps `(time, NUMROWS, NUMCELLS)` shape; readers flatten to `obs`
    - the ASCAT wind-direction +180° flip lives in `load_and_stack_ascat`, not
      in preprocessing — easy to double-apply or drop

11. **Do not unify the two output contracts.** The archive product exists for
    `wfetch`; the campaign product exists for a human reading a CSV.

12. **Q8 tier 2 — a small, named set of scientific overrides** in the campaign
    file (after tier 1, item 7). Roughly six options, each one line of docs:
    `retracker: sar|plrm` (S3), `retracker: mle|nr` (S6), `qc: true|false`
    (S1), `max_dist_coast_km`. Not a general variable-exposure mechanism: the
    config must never remap arbitrary names into standard slots, or every
    campaign file becomes a place for silent scientific errors.

13. **Q8 tier 3 — `extra_vars: [...]`** escape hatch passing named raw
    variables through unstandardized, so "I need one more field" never
    requires editing `readers.py`. Cheap; keeps matchup out of the business of
    standardizing all 401 S3 variables.

## Nice to have

14. Model × model intercomparison verb (`matchup compare era5 aifs --var hs`):
    regrid one field onto the other, difference maps + stats. Separate code
    path from obs collocation.
15. CFOSAT reader (Luigi mentioned directional data on a moving circular path;
    no sample file yet).
16. Sentinel-1 OSW spectral products (`*-iw{1,2,3}-osw-*.nc`): partitions +
    directional spectra. Out of scope for wind/wave-parameter matchup.
17. More tests for the campaign path (readers, campaign parsing, scan).

## Data gaps

- **Sentinel-6 contributes nothing to Harry.** Confirmed after item 3: all
  **five** passes (3 under `WAVE/`, 2 more under `WIND/`) cross Med latitudes
  at 37–47°E, east of the campaign box — 0 of 16 525 obs in box. Not a bug.
  Ask Angela whether other passes exist.
- ba08 buoy: wind columns are all zero (no anemometer); waves only.

## Results note — forecast skill by day (2026-07-29, lead windows)

Jason-3 Hs against `forecasts_00z` (daily 00 UTC inits), day-N windows:

| window | day | n | bias | rmse | SI | corr | slope |
|---|---|---|---|---|---|---|---|
| +12–35 h | 1 | 437 | −0.25 | 0.62 | 0.158 | 0.941 | 0.922 |
| +36–59 h | 2 | 437 | −0.18 | 0.66 | 0.179 | 0.925 | 0.924 |
| +60–83 h | 3 | 437 | −0.20 | 0.60 | 0.158 | 0.941 | 0.927 |
| +84–107 h | 4 | 127 | −0.77 | 1.26 | 0.184 | 0.758 | 0.839 |

**This supersedes the single-lead numbers computed earlier the same day**, and
resolves the sign anomaly they showed. Those slices had ±5 h of time-matching
slop (a constant-lead series inherits the *init* spacing — 12 h — so the
default tolerance was half of that); the day windows give hourly valid times
and ±30 min. Measured: max|dt| 298 min → 30 min. With the slop removed the
forecast Hs bias is **negative at every lead** (−0.18 to −0.25 m on days 1–3),
consistent with the analysis, hindcast and buoy comparisons. The earlier
positive bias was an artefact of comparing against fields up to 5 h away.

Controlled check that this is the window and not the init set: all inits
(12-hourly) with the same +12–35 h window gives bias −0.20, rmse 0.60,
SI 0.159 — i.e. the same as the 00 UTC-only run, and still ±30 min.

Day 4 has n=127 only (few inits reach that far back) and samples a
higher-sea subset (obs mean 5.39 m vs 3.55 m); not comparable with days 1–3.

## Time tolerance — decision record (2026-07-29)

**Was**: half the model's own median timestep. That made the standard scale
with the model's coarseness — a 6-hourly field earned ±3 h — which is backwards:
altimeter, scatterometer and SAR retrievals are *instantaneous* snapshots, and
a coarse model should get **fewer matches**, not a looser standard. It also
made results depend on the model's output frequency in a way that silently
flipped the sign of the forecast Hs bias (see the day-window note).

**Now**: `DEFAULT_TOL = 30 min`, fixed, independent of the model timestep.
`--tol-minutes` widens it explicitly. Every output records
`time_tolerance_minutes`, `n_rejected_time` and `matched_per_variable`
(per variable: how many obs were admitted and that variable's own cadence),
and `match` prints both. When nothing matches at all, `NoMatchInTime` explains
the cadence mismatch and names the two ways out.

**Consequence — 6-hourly winds are no longer comparable to altimeters by
default.** In `ecmwf_an` the waves are hourly but u10/v10 are 6-hourly, so
altimeter wind now yields 0 pairs where it previously produced numbers built
on up to ±3 h of slop. That is the honest outcome: those wind statistics were
never meaningful. To restore them, either widen deliberately
(`--tol-minutes 180`, and say so in the write-up) or use ERA5, whose winds
*are* hourly (jason3 × era5 wind still gives n=440 at 30 min).

Unaffected: every Hs comparison against hourly fields, and SWOT (its pass
happens to fall near a 6-hourly step, n=103).

**Correction (2026-07-29).** An earlier note here claimed the S1 SAR winds
were unaffected. That was wrong: it came from a `cstats` run that read a
**stale output file** after `match` had already failed. `s1_sar × ecmwf_an`
does NOT survive the 30 min default — the scene is at 05:05 UTC, 55 min from
the nearest 6-hourly wind field. Use ERA5, whose winds are hourly:

| s1_sar × era5 | n | bias | rmse | SI | slope |
|---|---|---|---|---|---|
| wind_speed | 82 479 | −0.83 | 1.56 | 0.066 | 0.955 |
| wind_dir | 82 479 | −2.52° | 3.93° | — | — |

*Process lesson*: `match` exits non-zero and leaves the previous output in
place, so a shell loop that ignores its exit status will silently report stale
numbers. Always check the exit status, or delete the outputs before a rerun.

## AIFS — verification and what can honestly be compared (2026-07-29)

**`time` IS the init — confirmed.** Raw GRIB keys: `dataDate/dataTime` =
20260108/0000 with `startStep` 0…240 and `validityDate/Time` = init + step;
`dataType=fc`, `stream=wave`, `class=rd`, `expver=j0b1`. So it is an ECMWF
*research* experiment (class `rd`), 12-hourly inits, 6-hourly steps to +10 d.
Worth asking Luigi/Jean what j0b1 is before citing it by name.

**Bug found while doing this**: `_dedupe_by_shortest_lead` only ran when a
dataset had several parts, so a *single* multi-init file (AIFS) kept duplicate,
unsorted valid times — which silently corrupts the `searchsorted` time matching
in `collocate_track`. Fixed (dedupe now always runs for a lead window).
Effect on AIFS day-1 Hs: bias −0.20 → −0.16, slope 0.959 → 0.965.

**AIFS vs the physical forecast cannot be compared on altimeter data.** AIFS
is 6-hourly, the forecast hourly, so either AIFS gets ±3 h of matching slop
(unfair to AIFS) or a tight tolerance keeps almost nothing: Jason-3 at ±45 min
leaves **n=25** for AIFS against n=437 for the forecast. Different samples,
not a comparison.

**Use the buoys for this.** Their 30-min series always contain a point at
AIFS's 6-hourly times, so both models can be matched at ±45 min (both achieve
max|dt| = 30 min), day-1 window +12–35 h:

| obs | model | n | bias | rmse | SI | corr | slope |
|---|---|---|---|---|---|---|---|
| ba04 | AIFS | 84 | −0.32 | 0.55 | 0.164 | 0.985 | 0.858 |
| ba04 | forecast | 313 | −0.08 | 0.41 | 0.138 | 0.977 | 0.973 |
| ba08 | AIFS | 85 | +0.01 | 0.30 | 0.091 | 0.991 | 0.996 |
| ba08 | forecast | 314 | −0.16 | 0.44 | 0.122 | 0.984 | 0.952 |

Still not a clean win either way: AIFS is better at ba08 (SE Sicily) and worse
at ba04 (W Sardinia), and its n is 4x smaller because of the 6-hourly output.
The earlier claim that "AIFS beats the physical forecast" is **not supported** —
it came from single-lead slices with ±5 h slop. Treat AIFS as comparable, not
better, on this storm.

Remaining check: the storm peak (20 Jan 15:00/17:30 UTC at the buoys) falls
between AIFS's 6-hourly steps, so AIFS structurally cannot represent the peak
instant. Any peak-underestimation statement about AIFS is partly about its
output frequency, not its physics.

## Results note — effect of the WIND/ folder fix (2026-07-29)

Adding the previously-missed files changed two datasets materially:

| pair | before | after |
|---|---|---|
| cryosat2 × ecmwf_an, hs | n=196, bias −0.30, SI 0.10 | n=353, bias −0.06, SI 0.118 |
| s3 × ecmwf_an, hs | n=464, bias −0.19, SI 0.223 | n=729, bias −0.13, SI 0.232 |

The extra passes sample the storm's build-up (19 Jan) and decay (21 Jan 20:12)
rather than only the peak, so both biases move toward zero — the earlier
numbers were biased by a peak-weighted sample. Peak underestimation itself is
unchanged; the *mean* bias was overstated. Unaffected: jason3, saral, hy2b,
hy2c, swot, s1_sar, buoys (their file sets were already complete).

## What each reader actually reads and filters (answers to Q2, Q3, Q4, Q7)

Source variables selected, and the filtering applied:

| kind | variables read | filtering |
|---|---|---|
| `altimeter_cmems` | `VAVH`→hs, `VAVH_UNFILTERED`, `WIND_SPEED` | **none** — CMEMS L3 is edited upstream, `VAVH` is already the filtered field |
| `altimeter_s3` | `swh_ocean_01_ku`→hs, `wind_speed_alt_01_ku`, `sig0_ocean_01_ku`, `lat/lon/time_01` | `*_qual_01_ku == 0` **only where the flag exists**; `wind_speed_alt_qual_01_ku` is absent in these files, so **S3 wind is unfiltered** (likely why its SI is the worst of any altimeter) |
| `altimeter_s6` | `data_01`: `latitude`, `longitude`, `time`, `wind_speed_alt`; `data_01/ku`: `swh_ocean`→hs, `sig0_ocean` | `swh_ocean_qual == 0`, `sig0_ocean_qual == 0`; **`wind_speed_alt` is not filtered** |
| `sentinel1` | `owiWindSpeed`, `owiWindDirection`, `owiLat/Lon`, `owiEcmwfWindSpeed/Direction`; time from attr `firstMeasurementTime` | `owiWindQuality` ∈ {good, acceptable} **and** `owiMask == 0` (no land/ice/no-data/RFI); `qc: false` disables |
| `ascat` | `wind_speed`, `wind_dir` (+180° met), `lat`, `lon`, row `time` | `wvc_quality_flag < 65536` (unchanged from the legacy rule) |
| `buoy_ispra` | `hm0`→hs, `hmax`, `mdir`, `tm01`, `tm02`, `tp`, `la1WindSpd/Dir` | empty cells → NaN; an all-zero wind column is dropped (no anemometer) |

Applied to every kind, regardless of reader:

- rows with non-finite lat/lon or `NaT` time are dropped (`readers._finish`)
- campaign **bbox + period** crop (`campaign.crop_obs`)
- **time tolerance** in collocation, per variable, default ½ its own median
  timestep; obs outside it are dropped
- obs outside the model grid get `NaN` model values but **the row is kept**
- `pairstats` excludes pairs where either side is non-finite — so CSV row
  count and the stats `n` deliberately differ

Deliberate choices worth revisiting (candidates for item 12):

- S3 uses the **SAR-mode** retracker (`_01_ku`), not pseudo-LRM
  (`_01_plrm_ku`). PLRM is what is backward-comparable with Jason-class
  altimeters, so strict cross-mission consistency would want it.
- S6 uses `swh_ocean` (MLE), not `swh_ocean_nr` (numerical retracker, often
  considered the better S6 product). Ku only, no C-band.
- Only `*_RED_*` products are read for S3 and S6. RED is the *reduced* 1 Hz
  product; STD adds a 20 Hz group, ENH adds waveform matrices. At 1 Hz the
  along-track spacing (~7 km) is already finer than any model grid here, so
  20 Hz would only oversample. **No data is lost**: RED's 1 Hz fields are
  identical to STD's.
- S1 `owiEcmwfWindSpeed/Direction` is the ECMWF first guess used *inside* the
  CMOD inversion, so SAR wind is **not statistically independent of ECMWF**.
  The −0.26 m/s bias against `ecmwf_an` is partly circular — state this in any
  write-up.

## Interpolation — decision record (resolved 2026-07-28)

**The question**: interpolate wind *components* or interpolate *speed and
direction*? The legacy `collocate.py` (and Luigi's Fortran) interpolate u10/v10
and derive speed/direction afterwards. The first version of
`collocate_track.py` did the opposite: it derived speed/direction on the model
grid and interpolated those two scalars.

These are not the same operation wherever direction varies across a grid cell:
|mean(u,v)| ≤ mean(|u,v|), so component interpolation gives a slightly *lower*
speed in turning or converging flow. Interpolating a *direction* as a plain
number is not merely different, it is wrong: 350° and 10° average to 180°
instead of 0°.

**Decision — component interpolation everywhere**, matching the legacy Fortran:

- `wind_speed` / `wind_dir` ← interpolate `u10`, `v10`; derive at the obs point.
- any other angle (`mwd`, `wave_dir`, `dwi`, …) has no components in the cube,
  so interpolate sin/cos and recombine with `arctan2`.
- statistics on angles are circular too (`pairstats`): errors wrapped to
  ±180°, vector means; SI / correlation / regression slope are meaningless on
  an angle and reported as `-`.

Implemented in `collocate_track._plan()`; covered by `tests/test_interpolation.py`
(a 350°/10° cell must interpolate to 0°, opposing winds must cancel to zero
speed, derived speed/direction must agree with interpolated u/v).

**Measured effect on the Harry results** (before → after, all pairs):

| quantity | change |
|---|---|
| `hs` (all pairs) | none — not a vector quantity |
| `wind_speed` bias | 0.00 to −0.02 m/s more negative; max per-point change 1.48 m/s (S3) |
| `wind_dir` bias | ≤ 0.02°; max per-point change 0.37° |

Conclusion unchanged, as expected — Harry's flow is smooth at 0.1–0.25°
resolution, so the two schemes almost agree, and the earlier judgement that
"the differences were minimal" is confirmed quantitatively. The speed bias
moves consistently *more negative*, exactly as |mean(u,v)| ≤ mean(|u,v|)
predicts, which is a useful sanity check that the change does what it claims.
The direction figures barely moved only because these particular passes have
few cells straddling north — the wrap bug was real and would have shown up on
any northerly case.
