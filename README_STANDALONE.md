# matchup — comparing wave/wind models against measurements

`matchup` compares **model output** (ECMWF GRIB, ERA5, AIFS, netCDF) against
**measurements** (satellite altimeters, SAR winds, buoys) and gives you the
statistics, plots and a plain CSV table.

You describe your data **once** in a small text file. After that every
comparison is one command. You never write Python, and you never tell it which
file matches which — it works that out itself.

---

## 1. Install (once)

You need **conda**. Everything else is installed for you.

```bash
cd matchup
./install.sh
```

This creates a conda environment called `matchup`, installs every dependency
(including the ECMWF GRIB libraries), installs `matchup` itself, and then
checks that each piece actually works. It takes a few minutes, and it is safe
to run again at any time.

Then, in every new terminal:

```bash
conda activate matchup
matchup --help
```

<details>
<summary>Manual installation, or into an environment you already have</summary>

```bash
conda env create -f environment.yml     # creates the 'matchup' environment
conda activate matchup
pip install -e .
matchup doctor                          # verify
```

To use an existing environment instead, install the dependencies into it from
conda-forge and then `pip install -e .` from this directory:

```bash
conda install -c conda-forge xarray netcdf4 cfgrib eccodes scipy pandas \
                             matplotlib-base pyyaml typer rich joblib tqdm
```
</details>

### Checking the installation at any time

```bash
matchup doctor
```

```
matchup doctor
  OK    python >= 3.10                   3.13.5
  OK    core packages                    numpy 2.2.6, scipy 1.16.1, ...
  OK    netCDF read/write                netCDF4 1.7.2 (round-trip 4 values)
  OK    GRIB engine (cfgrib + eccodes)   cfgrib 0.9.15.1, eccodes C library 2.47.3
  OK    plotting                         matplotlib 3.10.5 (Agg backend)
  OK    matchup package                  6 obs readers: altimeter_cmems, ...
  OK    example campaign file            harry.yaml: 19 datasets declared
all checks passed
```

Run this first whenever something behaves oddly. Any `FAIL` line is printed
with the command that fixes it.

## 2. Describe your data (once per study)

Copy `config/campaigns/harry.yaml` and edit it. A **campaign** is one study —
a storm, a month, a region:

```yaml
campaign: harry                       # name used in output filenames
data_root: /data/harry                # all paths below are relative to this
outdir:    /data/harry/matchup_out    # where results are written

region: {lonmin: -8, lonmax: 36, latmin: 26, latmax: 45}
period: [2026-01-15, 2026-01-23]      # YYYY-MM-DD

datasets:
  # ---- measurements ----
  jason3:    {kind: altimeter_cmems, path: "WAVE/JASON-3/*.nc"}
  s1_sar:    {kind: sentinel1,       path: "WIND/SAR/**/*-ocn-*.nc"}
  buoy_ba04: {kind: buoy_ispra, path: "buoys/ba04_*.csv", lat: 38.5, lon: 9.0}

  # ---- models ----
  ecmwf_an:  {kind: grib, path: "models/analysis/*.grib"}
  era5:      {kind: grib, path: "models/ERA5/*.grib"}
```

Rules of thumb:

- **A name on the left, a kind and a path on the right.** The name is what you
  type on the command line; make it short.
- `path` may contain wildcards. `**` matches any depth of subdirectories —
  useful for Sentinel products buried inside `.SEN3` / `.SAFE` folders.
- Everything outside `region` and `period` is discarded, so you can point at a
  whole archive and let the campaign box do the filtering.
- Buoys need `lat:` and `lon:` — the position is not inside the CSV.

### Kinds you can use

**Measurements**

| kind | what it reads |
|---|---|
| `altimeter_cmems` | CMEMS L3 altimetry: Jason-3, SARAL, CryoSat-2, HY-2B/C, SWOT-nadir (`global_vavh_l3_*.nc`) |
| `altimeter_s3` | Sentinel-3 SRAL L2 WAT (`*_RED_*.nc` / STD / ENH) |
| `altimeter_s6` | Sentinel-6 P4 L2 LR (`*_RED_*.nc` / STD) |
| `sentinel1` | Sentinel-1 IW OCN wind (`*-ocn-*.nc`) |
| `ascat` | ASCAT L2 winds |
| `buoy_ispra` | ISPRA/RON buoy CSV export (semicolon-separated) |

**Models**

| kind | what it reads |
|---|---|
| `grib` | any ECMWF GRIB — analysis, hindcast, ERA5, forecasts, AIFS |
| `netcdf` | model output in netCDF |

Two options for awkward model files:

- `init: "2026-01-18T00"` — when one file holds **many forecast starts**
  (AIFS), pick which start to use.
- `rename: {my_var: hs}` — if your variable names differ from the standard.

Standard names used throughout: `hs` (significant wave height), `wind_speed`,
`wind_dir` (direction the wind comes **from**, degrees), `mwd`, `mwp`, `tp`.

## 3. Look at what you have

```bash
matchup scan my_campaign.yaml
```

```
campaign harry: lon [-8, 36] lat [26, 45]  2026-01-15T00:00 -> 2026-01-23T00:00
  jason3       OBS    2/2 files readable  vars=hs,hs_unfiltered,wind_speed  440/14032 obs in box, 2026-01-19T07:01 -> 2026-01-19T23:23
  buoy_ba04    OBS    1/1 files readable  vars=hmax,hs,tm01,tm02,tp,wave_dir  335/529 obs in box, ...
  ecmwf_an     MODEL  8 files  vars=dwi,hs,mwd,mwp,pp1d,u10,v10,wind,wind_dir,wind_speed  grid 191x441 lat[26.0,45.0] lon[-8.0,36.0]  192 steps ...
```

**Always run this first.** It tells you what was found, what was readable, how
many measurements actually fall inside your box and period, and — importantly —
names any file it could **not** read. If a comparison later looks empty, the
answer is almost always visible here.

`440/27384 obs in box` is normal: satellite files are global, and only the part
crossing your region counts.

## 4. Compare

```bash
matchup match  my_campaign.yaml jason3 ecmwf_an     # measurement first, model second
matchup cstats my_campaign.yaml jason3 ecmwf_an
```

`match` writes two files into `outdir`:

- `harry_jason3_x_ecmwf_an.nc` — for further work in Python
- `harry_jason3_x_ecmwf_an.csv` — **plain text**, one row per measurement:

```
time,lat,lon,hs,hs_unfiltered,wind_speed,model_hs,model_wind_speed,dt
2026-01-19 07:01:48,44.1993,9.2687,1.0060,0.8900,7.6000,0.8200,5.4570,108.0000
2026-01-19 07:01:49,44.1551,9.3067,1.0020,0.8990,9.3100,0.8573,4.7563,109.0000
```

Open it in Excel, MAGICS, Fortran, anything. `model_*` columns are the model
interpolated to that measurement's position and time; `dt` is the time
difference in seconds to the model step used.

`cstats` prints the verification table and writes plots:

```
harry: jason3 x ecmwf_an
var                n     obs     mod    bias    rmse     SI   corr  slope
-------------------------------------------------------------------------
hs               437    3.55    3.35   -0.20    0.48  0.123  0.966  0.934
wind_speed       440   13.38   12.83   -0.55    2.05  0.147  0.847  0.947
```

- **bias** = model − measurement (negative: the model is too low)
- **rmse** — root mean square error, same units
- **SI** — scatter index: scatter after removing the bias, relative to the
  mean measurement (0.12 = 12 %)
- **corr** — correlation coefficient
- **slope** — symmetric regression through the origin; below 1 means the model
  underestimates, increasingly so at the high end

Add `--no-plots` for the table alone. Plots are a scatter (measurement vs
model, with statistics in the title) and a map of the differences.

Useful option: `--tol-minutes` sets how far in time a measurement may be from a
model field. The default is **30 minutes**, whatever the model's output
interval — satellite measurements are instantaneous, so a model written every
6 h gets *fewer* matches rather than a looser standard.

If a model's output is too coarse you will see, per variable:

```
  wind_speed: 0/440 within tol (model every 6h) -- no pairs at 30 min tolerance
```

That is not missing data: the model simply has no field close enough in time.
Either widen deliberately (`--tol-minutes 180`, and state it in your write-up,
because values are then compared across a 3-hour gap) or use a measurement
that samples the model's output times — buoys report every 30 min, so they
always have a point at the model's hours.

## 5. Repeat for every combination

Any measurement against any model — the names are all you change:

```bash
for obs in jason3 saral s3 buoy_ba04 buoy_ba08; do
  for mod in ecmwf_an era5 aifs_wave; do
    matchup match  my_campaign.yaml $obs $mod
    matchup cstats my_campaign.yaml $obs $mod --no-plots
  done
done
```

---

## If something goes wrong

**`scan` shows `0/N obs in box`** — the measurements exist but fall outside your
region or period. Check the `region`/`period` in the YAML. Some satellite
passes genuinely never cross your area; that is a fact about the data, not an
error.

**`no <obs> observations inside the campaign box/period`** — same cause; run
`scan` to see which datasets actually have data.

**`scan` shows `UNREADABLE` for a model** — the file is a format the reader
doesn't cover yet. Send the message and the filename to Cristhian.

**A variable shows `(no valid pairs)`** — the model has no such variable
(e.g. wave files contain no wind), or its time steps are too far from the
measurement times. Try `--tol-minutes`.

**A comparison has fewer points than expected** — normal when the model covers
a shorter period than the measurements (a forecast starts at its own init
time), or when quality flags rejected part of the data.

**Anything odd after installing** — run `matchup doctor`. It tests each piece
(netCDF, GRIB, plotting) and prints the fix for whatever failed.

**`matchup: command not found`** — the environment is not active in this
terminal: `conda activate matchup`.

**A GRIB error such as `unknown engine cfgrib`** — the ECMWF libraries are
missing or came from a different channel:
`conda install -c conda-forge cfgrib eccodes` (both, conda-forge, same
environment), then `matchup doctor`.

## Notes

- Longitudes are handled automatically (0–360 and −180–180 are both fine).
- Times are UTC throughout.
- Quality flags of the satellite products are applied by default.
- Adding a new instrument or file format is a small, self-contained addition
  (one function in `src/matchup/readers.py`) — send a sample file.
