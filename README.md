# matchup

Config-driven **observation ↔ model collocation** for waves and winds.

Two workflows share one set of readers and one canonical output shape:

| workflow | entry point | purpose |
|---|---|---|
| **campaign** | `matchup scan / match / cstats <campaign.yaml>` | one storm or field study: any obs source × any model, straight to stats/plots/CSV |
| **archive** (legacy) | `matchup run / merge --data … --model …` | multi-year ASCAT × IFS point cloud feeding `wfetch` |

New work should use the **campaign** workflow. The archive workflow is
unchanged and still owns the `wfetch` contract (see the bottom of this file).

For a colleague who just wants to run comparisons and has no interest in
`trawl`/`wfetch`, hand them **[README_STANDALONE.md](README_STANDALONE.md)** —
it documents the campaign workflow alone.

Standalone and portable: depends on nothing from `wave_models2`. Mirrors the
`trawl` / `metaocean` packaging and the `wfetch` values-only-config convention.

## Install

Own environment (what a colleague gets — creates env `matchup`, installs, verifies):

```bash
cd ~/WAVEWATCH/matchup
./install.sh                 # or: ./install.sh <envname>
```

Into an existing environment:

```bash
conda activate wave-models2
pip install -e .
matchup doctor               # verify deps: netCDF, GRIB (cfgrib+eccodes), plots
```

`environment.yml` pins the conda-forge dependencies; `matchup doctor` exercises
each one for real (writes/reads a netCDF, loads the eccodes C library) and
prints the fix command for anything that fails.

---

# Campaign workflow

One YAML declares a region, a period and **named datasets**; commands take
dataset *names*, never file paths. File discovery, format handling and
obs↔model file pairing are automatic.

```bash
matchup scan   config/campaigns/harry.yaml                   # inventory the data
matchup vars   config/campaigns/harry.yaml s3                # what is in the files
matchup match  config/campaigns/harry.yaml jason3 ecmwf_an   # collocate -> .nc + .csv
matchup cstats config/campaigns/harry.yaml jason3 ecmwf_an   # stats table + plots
```

- **`scan`** — per dataset: files found/readable, observations inside the
  box/period, per-variable model cadence and the tolerance derived from it,
  rejection counts, which variables carry no quality flag, and loudly, anything
  unreadable. Run it first on every new data delivery.
- **`match`** — reads all files of an obs dataset, crops to the campaign
  box/period, collocates against the model cube, writes
  `<outdir>/<campaign>_<obs>_x_<model>.nc` **and `.csv`**. Exits non-zero when
  nothing matches, so scripts must check (`match ... && cstats ...`) or they
  will read a stale output.
- **`vars`** — a product's source variables grouped by the axis they lie on,
  marking which are already read as a standard name and which can be pulled
  through with `extra_vars`. `--all` includes the other sampling rates.
- **`cstats`** — bias / RMSE / SI / correlation / symmetric slope per variable
  (circular statistics for directions), plus scatter + difference-map PNGs.
  `--by-lead` splits a forecast collocation into lead bands.

Forecast verification: `match --lead 12-35` takes a lead **window** across
every init in the dataset (a single lead, `--lead 24`, is the degenerate case
but inherits the init spacing in its time tolerance — prefer a window). Filter
inits by hour through the glob. Each output row records `init` and
`lead_hours`.

Defaults worth knowing: time tolerance is a strict **30 min** independent of
the model timestep (observations are instantaneous); altimeter records within
**30 km of the coast** are dropped where the product supports it. Both are
recorded in every output alongside `<var>_source` / `<var>_filter` /
`n_rejected_*`, so results are auditable without rerunning.

## Campaign file

```yaml
campaign: harry
data_root: /home/valladca/WAVEWATCH/harry_storm/data   # paths below are relative to this
outdir:    /home/valladca/WAVEWATCH/harry_storm/matchup_out
region: {lonmin: -8, lonmax: 36, latmin: 26, latmax: 45}
period: [2026-01-15, 2026-01-23]

datasets:
  jason3:    {kind: altimeter_cmems, path: "WAVE/JASON-3/*.nc"}
  s1_sar:    {kind: sentinel1,       path: "WIND/SAR/**/*-ocn-*.nc"}
  buoy_ba04: {kind: buoy_ispra, path: "buoys/ba04_*.csv", lat: 38.5, lon: 9.0}
  ecmwf_an:  {kind: grib, path: "models/analysis/*.grib"}
  aifs_wave: {kind: grib, path: "models/AI/aifs_*wave*.grib", init: "2026-01-18T00"}
```

`config/campaigns/harry.yaml` is a complete worked example (Storm Harry, Med,
Jan 2026: 9 obs datasets × 8 model datasets).

## Supported data kinds

Observation `kind` → reader in `matchup.readers.READERS`:

| kind | source | structure handled |
|---|---|---|
| `altimeter_cmems` | CMEMS L3 NRT (Jason-3, SARAL, CryoSat-2, HY-2B/C, SWOT-nadir) | flat along-track |
| `altimeter_s3` | Sentinel-3 SRAL L2 WAT (RED/STD/ENH) | 1 Hz `_01` Ku rate + quality flags |
| `altimeter_s6` | Sentinel-6 P4 L2 LR | netCDF groups (`data_01`, `data_01/ku`) |
| `sentinel1` | Sentinel-1 IW OCN (owi grid) | 2-D swath → cloud; **IPF-aware** quality flags |
| `ascat` | ASCAT L2 wind | NUMROWS × NUMCELLS → cloud |
| `buoy_ispra` | ISPRA/RON CSV export | fixed point; needs `lat:`/`lon:` in the config |

Model `kind`: `grib` (cfgrib) or `netcdf`. Handles one-variable-per-file
dumps, forecast `step` → valid time, multi-init files (`init:` option) and
GRIBs mixing editions.

**Adding a format is one function** in `readers.py` returning the canonical
cloud, plus one line in `READERS` — no changes anywhere else.

## What config may and may not do

The readers keep a small standard map (Sentinel-3 RED ships 65 variables;
three become `hs`/`wind_speed`/`sig0`). A campaign file may:

- **add** any other variable on the same record axis, via `extra_vars: [...]`.
  They arrive under an `x_` prefix and are carried through untouched;
- **choose** among named alternatives for a standard slot: `retracker:
  sar|plrm` (S3), `retracker: mle|nr` and `band: ku|c` (S6), `qc`,
  `min_dist_coast_km`, `open_ocean_only`.

It may **not redefine what a standard name means**. `collocate_track` keys
circular interpolation and circular statistics off names like `wind_dir`, and
derives `wind_speed`/`wind_dir` from interpolated `u10`/`v10` — free-form
remapping would let a YAML edit silently change the physics. The `x_` prefix
exists so a passthrough column can never acquire those behaviours.

Variables on another axis (20 Hz against a 1 Hz track) are refused with the
axis named: that is a format problem needing reader support, not a preference.

## Architecture

```
readers.py    any obs file    -> canonical cloud (obs dim; time/lat/lon; hs, wind_speed, …)
models.py     any model file  -> standard cube  (time, lat, lon; lon -180..180, lat ascending)
campaign.py   YAML            -> named datasets + region/period cropping
collocate_track.py   cloud × cube -> flat pairs (per-variable time matching)
pairstats.py  pairs           -> stats table + plots
scan.py       campaign        -> inventory report
```

The split that matters is **observation geometry, not instrument**: everything
becomes a point cloud in `readers.py`, so one collocation path serves
altimeters, SAR swaths and buoys alike.

---

# Archive workflow (ASCAT × IFS → wfetch)

```
download (trawl / ifs_download)  ->  matchup run  ->  wfetch consumes merged .nc
```

Two stages, both idempotent:

1. **collocate** — one `*_colloc.nc` per raw satellite file (skips existing).
2. **merge** — stack the collocated files into one canonical
   `collocated/<PREFIX>_<model_label>_merged_<Ystart>_<Yend>.nc`, built
   incrementally via per-year parts under `collocated/_parts/` (only years whose
   source set changed are rebuilt).

```bash
matchup datasets                                        # list models + sat sources
matchup run   --data ASCAT_med --model IFS_HRES_neutral_med
matchup merge --data ASCAT_med --model IFS_HRES_neutral_med --dry-run   # which years rebuild
```

## Subregions

Collocate once per **basin** (redsea / med / arabgulf). A subregion (e.g. a
storm) is a cheap query over the basin's merged point cloud — no re-collocation:

```bash
matchup subset ASCAT_ifs_hres_neutral_med_merged_2016_2024.nc \
    --lonmin 2 --lonmax 20 --latmin 36 --latmax 44 \
    --t0 2023-11-01 --t1 2023-11-10 --out harry_storm.nc
```

or in Python: `from matchup.subset import subset`.

## Configuration

`config/config.yaml` is **values only** (roots, region boxes, named model/sat
datasets). All logic lives in `src/matchup/`. To add a model or satellite
source, add one entry — no code changes. The satellite `kind` (`ascat` /
`sentinel1`) selects the preprocess/loader pair in `matchup.registry.KINDS`.

## Consumer contract (do not break)

The merged file is a flat dataset with a single `time` dimension (one obs per
entry, monotonic), coords `time,lat,lon`, and required vars `wind_speed`,
`wind_dir` (meteorological "from"). `wfetch` globs exactly one file per
region/wind-type: `collocated/ASCAT_ifs_hres_<type>_<region>_merged*.nc`.
