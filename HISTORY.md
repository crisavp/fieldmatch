# 0.4.0 — Terminal-first, portable study example

- Replace the primary .ipynb example with analyze.py: inspect, run and plot actions,
  plus optional VS Code # %% cells. Plotting reuses validated saved comparisons.
- Resolve CLI configuration paths relative to the script, never the working
  directory. Interactive execution requires an explicit absolute config path.
- Document source/wheel installation in existing or new environments. The installer
  creates new environments or uses the active Python; it never prunes an environment.
- Replace the notebook extra with interactive (Matplotlib + ipykernel). JupyterLab
  is not required. Core numerical comparison policies are unchanged.

# 0.3.0 — Grid comparisons and optional plotting

- Add exact-time model/model comparisons on an explicitly chosen reference grid,
  with valid-time, same-initialization and same-lead policies, common masks and
  spherical area-weighted difference summaries.
- Share scalar/circular/vector spatial sampling with observation matching.
- Add optional field maps, difference panels, common-observation station series,
  scatter plots and figure provenance sidecars. Plotting never aligns data.
- Add a portable Harry campaign and an editable notebook in examples/.
- Keep existing observation YAML and outputs compatible with the 0.2 checkpoint.

# Configuration refinement

Named comparisons group independent quantities under `variables`; settings go
directly under each quantity. Shared settings use `matching_defaults`.
`compare` reads scientific settings from YAML; `--describe` shows all quantities.
The numerical matching engine is unchanged. See campaign reference for migration.

# 0.2 — Storm Harry scientific-accuracy fixes

- One declared quantity per result; independent batches retain valid Hs when
  winds select different timestamps. CLI variables are explicit.
- Checked time-partition assembly, scalar forecast steps, compatible grids/units
  and cross-variable forecast provenance. Overlap and nearest-lead fallback are
  explicit choices.
- Shared comparison execution and resolved YAML/CLI settings. Manifests retain
  source identities, units/QC, effective policies, implementation/output hashes.
- Exact-node missing-corner handling and undefined circular/vector directions.
- Stable observation IDs and checked common-observation alignment.
- Quantity suffixes, dotted output names and full-precision CSV values.

Existing readers, basic scores and CSV/NetCDF remain the core; linear temporal
interpolation, general regridding and storm-analysis orchestration are deferred.
See docs/output-formats.md for the intentional 0.1 migration.

# FieldMatch and archive workflow — audit and implementation history

This file preserves the detailed audit trail and completed refactor notes. It
is historical context, not the current work queue; see `TODO.md` for that.

Ordered by priority. Context for each is in the git history / conversation of
2026-07-27..30.

## Design principle — dropping must stay reversible

The library exists to make collocating many files easy, and it earns the clean
comparisons by discarding a great deal: rows outside the box, the coastal
strip, quality-flagged values, and — most of all — every source variable
outside each reader's small standard map (Sentinel-3 alone ships 62 variables
at 1 Hz; we keep three).

That is right for the default path and wrong as a hard limit. The intended
user is an advanced one who will legitimately want quantities that are NOT
directly comparable to a model field: retracker diagnostics, `sig0`, rain and
ice flags, wave periods, spectral partitions. **No decision in this library may
make those unreachable.** Concretely:

- keep the escape hatch (item 13, `extra_vars: [...]`) on the roadmap and
  treat it as a design requirement, not a nicety;
- prefer masking to deleting where the choice is a judgement call, and where a
  reader does drop rows (coastal masking) make the threshold configurable and
  record what was dropped — `min_dist_coast_km: 0` must always recover the
  full track;
- never let a standard name silently replace access to its source variable:
  the provenance attributes name the source, so the raw file can be reopened;
- the canonical cloud is a floor, not a ceiling — a reader may carry extra
  columns through, and collocation simply ignores what the model cannot match.

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
   `campaign.Dataset.files()` now uses `(basename, size)` only to find suspected
   collisions, then de-duplicates byte-identical content by SHA-256; distinct
   same-size files are retained with a warning. Recovered: CryoSat-2 1→2 files,
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

   **Prefer a window to a single lead.** The tolerance is always the fixed
   ±30 min default, so a constant-lead series from sparse inits yields fewer
   matches. A day window yields hourly valid times and denser coverage. Where a window is wider than the
   init spacing, several forecasts cover the same valid time; the shortest
   lead wins and a warning says the sample is no longer a clean tiling.
   With daily inits, +12–35 h tiles the timeline exactly and warns nothing.

6. ~~Characterization test for the archive pipeline before any refactor.~~
   **DONE 2026-07-30.** `tests/test_archive_characterization.py` freezes the
   ASCAT path end to end — preprocess (0-360 longitude conversion, per-row time
   becoming the row dimension, empty-region skip), collocation (interpolation
   onto obs, idempotent re-run, `nomodel` retryable without writing), the
   merge-stage loader (quality filter, the +180 direction rotation that lives
   in the LOADER and is easy to double-apply), and the `wfetch` consumer
   contract (flat monotonic time index, REQUIRED variables present).

   Synthetic and hand-checkable (a 2x3 granule on a 3x3 uniform model grid),
   so it needs no external data and runs in milliseconds. Verified by mutation:
   removing the direction rotation, skipping the longitude conversion, and
   loosening the quality threshold each make it fail. Item 10 is now unblocked.

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
   fixed default time tolerance; reformat the report as per-dataset blocks
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

12. ~~Q8 tier 2 — a small, named set of scientific overrides.~~
    **DONE 2026-08-01.** `retracker: sar|plrm` (S3), `retracker: mle|nr` and
    `band: ku|c` (S6), alongside the already-shipped `qc`, `min_dist_coast_km`
    and `open_ocean_only`. Enumerated, not free strings: an unknown value
    fails listing the alternatives, and `retracker=nr` with `band=c` is
    refused because the C-band group ships no numerical-retracker variables.
    The choice is recorded in provenance (`retracker`, `band`, `hs_source`).

    Measured on Harry: SAR vs PLRM makes almost no difference inside the
    campaign box — hs bias −0.11 both, rmse 0.34 both, slope 0.955 vs 0.953.
    (Whole-track means differ by 0.29 m, but that is global sea-state
    sampling, not a retracker bias.) So cross-mission consistency with
    Jason-class altimeters is available if wanted, and nothing here hinges
    on it.

13. ~~Q8 tier 3 — `extra_vars: [...]`~~ **DONE 2026-08-01**, together with the
    discoverability command that makes it usable:

    - **`matchup vars <campaign> <dataset>`** lists a product's source
      variables grouped by the axis they lie on, marking which are already
      read as a standard name and which are eligible for `extra_vars`, with
      units, long names and flag meanings. Reads `readers.LAYOUT`, so the
      listing cannot drift from what the readers do. `--all` shows the other
      axes, labelled as needing reader support.
    - **`extra_vars: [...]`** carries named variables through verbatim under an
      `x_` prefix, into the collocated netCDF and the CSV.

    Three rules make it safe, and they are the boundary of what config may do:
    only variables on the reader's own record axis are accepted (a 20 Hz S3
    variable is refused *with the axis named* — a format problem, not a
    preference); Sentinel-6's identically-named Ku and C variables are written
    `ku:swh_ocean` / `c:swh_ocean` and land in separate columns; and a
    requested variable absent from the product warns and is recorded rather
    than silently dropped.

    **What config still may NOT do**: redefine what a standard name means.
    `collocate_track` keys circular interpolation and circular statistics off
    names like `wind_dir`, and derives `wind_speed`/`wind_dir` from
    interpolated `u10`/`v10`. Free-form remapping would let a YAML edit
    silently change the physics, so extras live in their own `x_` namespace
    where they can never acquire those behaviours. Config may **add**
    variables and **choose among named alternatives** (item 12); it may not
    **redefine** a slot.

## Campaign workflow — hardening audit resolved 2026-08-31

The campaign workflow remains separate from the archive workflow. The repair
did not merge their lifecycle or output contracts.

- YAML now has an explicit per-kind option schema; unknown/mistyped options,
  invalid bounds, unsafe names, and missing buoy positions fail immediately.
- Generic netCDF models accept `lat/lon` or `latitude/longitude`, support an
  explicit `coords` map, enforce/transposes rectilinear `(time, lat, lon)`, and
  subset to the campaign region/period before interpolation.
- A row is successful only with a finite obs/model pair. All-NaN spatial
  interpolation is rejected, and rows whose variables sample different model
  valid times are dropped so shared `dt/init/lead_hours` cannot lie.
- Match outputs use temporary files + atomic replacement. A pair manifest
  tracks current input/config identity and latest-run state; `cstats` refuses
  missing, stale, failed, or interrupted results while preserving the last
  successful NetCDF for recovery.
- Date-only end bounds include the full final UTC day; exact timestamp bounds
  remain exact. CLI tolerances and lead-bin widths reject invalid values.
- Pass-through variables retain dtype and metadata. ASCAT validates one time
  per row and records provenance. A zero buoy direction remains valid north;
  only a jointly all-zero wind speed/direction pair means no sensor.
- The reported regression is now accurately named origin-constrained OLS
  (`OLS0` / `ols_origin_slope`). Empty-pair plots no longer crash. Scan reports
  the actual fixed 30-minute default instead of half the model cadence.
- Campaign parsing, readers, model normalization, collocation failure modes,
  manifest lifecycle, atomic writes, and CLI success/failure now have synthetic
  regression coverage in `tests/test_campaign_hardening.py`.

## Archive workflow — reliability findings (audit 2026-08-31)

These findings apply to the legacy/archive `matchup run` / `matchup merge`
workflow only, not to campaign mode. They are production risks found by code
audit; they do **not** establish that an existing merged product is corrupt.

### Must — make incremental ingestion genuinely resumable

1. **Make yearly-part and ledger updates transactional.** `_fold_year()`
   atomically replaces the year part before `run_merge()` saves the ledger. If
   the process stops between those operations, the next run appends the same
   scenes again. Redesign the commit/recovery protocol so a crash at any point
   cannot duplicate observations.

2. **Record ingestion success per input file.** `_stack_files()` drops loader
   failures (`None`), but a successful batch currently marks every filename in
   that batch as ingested. A bad or temporarily unreadable file can therefore
   be hidden permanently when another file succeeds. Only acknowledge files
   positively confirmed as folded; retain failures for retry and report them.

3. **Add failure-recovery tests.** Cover interruption after part replacement
   but before ledger commit, restart after that interruption, and a batch that
   mixes successful, empty, and failed loaders. Assert exactly-once rows and
   that failed files remain retryable.

4. **Audit the existing Mediterranean state before treating it as
   authoritative.** Compare the ledger's source basenames with each yearly
   part and check for duplicate observations/source scenes. This is a
   precaution prompted by the transaction design, not evidence that the file
   is currently duplicated.

### Should — provenance, compatibility and ownership

5. **Write production provenance into merged NetCDF files.** Record the
   `matchup` version/commit, creation time, dataset names, effective config,
   source-file identity or manifest digest, per-status input counts, and the
   year-part/ledger generation. The present filename contract identifies the
   product type but not how its bytes were produced.

6. **Remove the xarray MultiIndex deprecation warning** in the ASCAT
   merge-stage loader and pin the resulting flat `time` contract with a test,
   before a future xarray release turns the warning into an error.

7. **Add an installed-package smoke test.** Build/install a wheel in a clean
   environment and exercise default config discovery plus the archive CLI.
   Default configuration currently depends on the source-tree layout and is
   not declared as package data.

8. **Document the producer/consumer boundary.** `wind_fetch` does not import or
   invoke `matchup`; it discovers a merged NetCDF through the filename and data
   contract. State explicitly that refreshing collocations is a separate
   upstream `matchup` operation, and fail clearly when zero or multiple merged
   files satisfy the consumer glob.

### Current on-disk lineage (checked 2026-08-31)

- Red Sea neutral (`...merged_2016_2025.nc`, written 2026-03-02) and Red Sea
  stress-equivalent (`...merged_2018_2020.nc`, written 2026-05-21) predate the
  `matchup` package. They were produced by the predecessor workflow from which
  the archive implementation was ported.
- Mediterranean neutral (`...merged_2016_2026.nc`, written 2026-07-08) was
  assembled through `matchup`'s yearly `_parts` + `ledger.json` workflow. The
  deleted per-scene collocation files prevent proving whether interpolation was
  rerun by `matchup` or whether existing predecessor outputs were folded.
- No matching Arabian Gulf merged input was present. `wind_fetch` currently
  consumes these products indirectly through its configured glob; it has no
  runtime or packaging dependency on `matchup`.

## Blocked — fresh-environment install is unverified (2026-07-30)

`./install.sh` has **never been run to completion**, on this machine only,
because of a machine-level fault unrelated to matchup. Do this after the next
reboot; it is the first thing a colleague will run.

```bash
rm -rf ~/anaconda3/envs/matchup-testinstall ~/anaconda3/envs/matchup-verify
cd ~/WAVEWATCH/matchup && ./install.sh          # expect 5-15 min
```

**What happens instead.** Three separate runs wedged identically: the conda
process enters uninterruptible sleep (`D`), `wchan=lookup_slow`, 0 % CPU, with
`write_bytes` frozen and the environment stuck at exactly 100 MB. The first
sat like that for 40 h. `D`-state processes ignore SIGKILL, so they survive
until reboot; two are still parked plus their partial env directories (inert,
not registered with conda, harmless).

**Ruled out**: the solver (libmamba is default; the solve takes seconds with
the explicit `--solver=libmamba` flag), the downloads (they complete), the disk
(125 MB/s to the same filesystem), the sshfs mounts to KAUST (`/mnt/shaheen`,
`/mnt/project/k10036` both respond), and conda's own config (`pkgs_dirs` and
`envs_dirs` are all local). `df` on the anaconda path also hangs, which points
below conda entirely -- a wedged kernel/FUSE or ext4 path-lookup state on
`/dev/sdc1`.

**If it stalls again after a reboot** it is the machine, not matchup: check
`dmesg | grep -iE 'ext4|I/O error'` (needs root) and raise it with whoever
administers the box.

Note that the *library* is not in doubt: 21 tests pass and every command has
been run end-to-end against the real Harry data in an existing scientific Python
environment. Only the fresh-environment bootstrap is unverified. The timeout
added in `install.sh` (`MATCHUP_CONDA_TIMEOUT`, default 3600 s) means this
failure now reports "conda exceeded 3600s and was stopped" with a retry hint
rather than appearing to hang overnight.

## Nice to have

14. Model × model intercomparison verb (`matchup compare era5 aifs --var hs`):
    regrid one field onto the other, difference maps + stats. Separate code
    path from obs collocation.
15. CFOSAT reader (Luigi mentioned directional data on a moving circular path;
    no sample file yet).
16. Sentinel-1 OSW spectral products (`*-iw{1,2,3}-osw-*.nc`): partitions +
    directional spectra. Out of scope for wind/wave-parameter matchup.
17. ~~More tests for the campaign path (readers, campaign parsing, scan).~~
    **DONE 2026-08-31** for the hardening cases above; add format-specific
    fixtures as new products arrive.

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

*Process lesson at the time*: `match` exited non-zero and left the previous
output in place, so a shell loop that ignored its exit status could report stale
numbers. **Resolved 2026-08-31:** the last good file is still preserved, but a
run-state/input manifest makes `cstats` refuse it after a failed, interrupted,
or configuration-changing run. Scripts should still check exit status.

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
| `buoy_ispra` | `hm0`→hs, `hmax`, `mdir`, `tm01`, `tm02`, `tp`, `la1WindSpd/Dir` | empty cells → NaN; a jointly all-zero wind speed/direction pair is dropped (no anemometer), but 0° direction is valid north |

Applied to every kind, regardless of reader:

- rows with non-finite lat/lon or `NaT` time are dropped (`readers._finish`)
- campaign **bbox + period** crop (`campaign.crop_obs`)
- **time tolerance** in collocation, per variable, fixed at 30 min by default;
  obs outside it are dropped
- obs outside the model grid or with no finite obs/model pair are dropped;
  rows sampling different model valid times are also dropped
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
