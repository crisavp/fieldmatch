# matchup

Config-driven **satellite ↔ model wind collocation**. Interpolates model winds
(IFS HRES, ERA5, …) onto satellite scatterometer/SAR observations (ASCAT,
Sentinel-1) and produces a single flat, time-indexed merged product per
region/model — the input `wfetch` (wind_fetch) consumes.

Standalone and portable: it depends on nothing from `wave_models2`. Mirrors the
`trawl` / `metaocean` packaging and the `wfetch` values-only-config convention.

## Install

```bash
cd ~/WAVEWATCH/matchup
conda activate wave-models2
pip install -e .
```

## Flow

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
