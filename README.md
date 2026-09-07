# FieldMatch

FieldMatch reads observations and gridded model fields, matches **one physical
quantity per result**, and saves the pairs with their scientific settings.
A batch can request several quantities; each has independent accepted rows,
model times, and a CSV/NetCDF output. Basic statistics are a separate step.

```bash
conda activate wave-models2  # or your installation environment
fieldmatch scan harry.yaml
fieldmatch vars harry.yaml ecmwf_an
fieldmatch collocate harry.yaml buoy_ba08 ecmwf_an --variable hs
fieldmatch stats matchup_out/harry_buoy_ba08_x_ecmwf_an_hs.csv
```

To run Hs and wind together, repeat `--variable`. Adding wind never removes
an Hs pair:

```bash
fieldmatch collocate harry.yaml buoy_ba08 ecmwf_an \
  --variable hs --variable wind_speed --format both
```

The default is nearest model time within **30 minutes**, bilinear spatial
interpolation, no spatial extrapolation, and rejection of missing contributing
corners. The nearest-time tie goes to the earlier model step. Directions use
circular/vector interpolation; undefined directions remain missing. Zero
time tolerance explicitly requests exact timestamps.

All effective defaults, overrides, source mappings, units, reader/QC provenance,
input/source-code checksums and accepted/rejected counts are saved in the
adjacent manifest. CSV needs this manifest to carry its metadata. Console output
shows the resolved specification before matching.

## Explicit campaigns

Keep dataset declarations and put the scientific choices in the YAML:

```yaml
datasets:
  ecmwf_an:
    kind: grib
    path: "models/analysis/*.grib"
    rename: {pp1d: tp}
  # Add the buoy_ba08 observation dataset here.

matching_defaults:
  tolerance_minutes: 30
  time_tie: earlier
  space_method: bilinear

comparisons:
  peak_period:
    obs: buoy_ba08
    model: ecmwf_an
    variables:
      hs: {}
      tp: {}
```

```bash
fieldmatch compare harry.yaml peak_period --describe
fieldmatch compare harry.yaml peak_period
```

`pp1d` is peak period. ECMWF `mwp` is energy mean period, not buoy `tm01` or
`tm02`; FieldMatch checks known quantity identities and units. Neutral
wave-forcing wind and atmospheric wind also remain distinct.

## Installation and runnable example

```bash
python -m pip install -e .
fieldmatch doctor
python examples/create_demo_data.py
fieldmatch collocate examples/minimal_campaign.yaml altimeter model --variable hs
fieldmatch stats examples/results/demo_altimeter_x_model_hs.csv
```

Optional plotting: `python -m pip install -e '.[plot]'`, then `stats --scatter`.
Supported observations: CMEMS altimetry, Sentinel-3/6 altimetry, Sentinel-1 OWI,
ASCAT, and ISPRA buoy CSV. Models: rectilinear GRIB or NetCDF.

## Model differences and figures

Keep grid comparisons in the same campaign:

```yaml
comparisons:
  analysis_era5:
    reference: analysis       # Defines the grid; difference = ERA5 minus analysis.
    model: era5
    time_basis: valid_time    # Or same_init / same_lead, at exact shared valid times.
    variables:
      hs: {space_method: bilinear}
```

```bash
fieldmatch compare campaign.yaml analysis_era5 --describe
fieldmatch compare campaign.yaml analysis_era5 --format both
```

Grid output defaults to NetCDF (fields, differences, mask and forecast coordinates).
For grids, CSV means per-time area-weighted difference summaries, not a flat grid.
The observation command retains its CSV default. A model reference is not truth.

```python
from fieldmatch.results import open_result
from fieldmatch.plotting import comparison_panels, save_figure

result = open_result("comparison.nc")
fig, axes = comparison_panels(result, "2026-01-20T18:00", clim=(0, 10), difference_limit=2)
save_figure(fig, "storm.png")  # also writes storm.png.figure.json
```

Install `.[notebook]` for Jupyter and open
[the Harry notebook](examples/harry_exploration.ipynb). Edit its data folder and
settings, then run the cells. [Grid and plotting guide](docs/grids-and-plotting.md)
explains the scientific choices and limits. The core has no plotting dependency.

## Documentation

- [Campaign reference](docs/campaign-reference.md): selection, matching and named comparisons.
- [Output formats and migration](docs/output-formats.md): independent quantity tables and provenance.
- [Python examples](examples/README.md): shared runner and common samples.
- [Adding readers](docs/adding-readers.md), [testing](docs/testing.md), [contributing](CONTRIBUTING.md).

Version 0.2 changes output filenames to include the quantity and requires an
explicit CLI variable. Nearest-lead fallback and shortest-lead overlap selection
are now opt-in. See the migration notes before updating a downstream reader.

Configuration migration: rename top-level `matching` to `matching_defaults`; replace
comparison `variable: hs` with `variables: {hs: {}}`. Move comparison matching
settings directly under that variable and model source mappings into dataset
`rename`. The previous configuration spelling is rejected to keep one clear schema.
