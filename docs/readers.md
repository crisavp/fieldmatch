# Built-in readers: editable settings and fixed behavior

Start with the [fully commented configuration catalogue](../src/fieldmatch/config_example.yaml).
It contains every dataset option accepted by the current reader registry, plus all
model, campaign and comparison settings. From an installed library:

```bash
fieldmatch config-example --output config_reference.yaml
```

This writes a new file and refuses to overwrite an existing one. Copy the relevant
blocks into your study; the catalogue's paths are placeholders. Remove unused
readers/comparisons before running. For real source variable names, use
`fieldmatch vars campaign.yaml DATASET --all`. Describe reports the configuration;
scan reads the data inventory. Neither makes incompatible physical quantities equivalent.

## Common rules

All datasets require `kind` and `path`. A path is one glob or a list of globs relative
to data_root. Reader options belong directly under the dataset, alongside kind/path.
Unknown keys are rejected. Model `rename` and `coords` are not observation-reader
options. Latitude/longitude settings apply only to the fixed-position buoy reader;
satellite locations come from their files.

`extra_vars` defaults to none and accepts a string or list. It copies source fields
under `x_` names; it does not change the default Hs/wind retrieval or apply its QC to
the extra fields. A missing requested field emits a warning and is recorded. A field
on another time axis raises an error instead of being resampled. For Sentinel-6,
`ku:swh_ocean` becomes `x_ku_swh_ocean`; unqualified names come from data_01.

## Editable observation options

| kind | Option | Default | Values / meaning |
|---|---|---|---|
| altimeter_cmems | extra_vars | none | CMEMS L3 fields on time |
| altimeter_s3 | extra_vars | none | SRAL fields on time_01 (1 Hz) |
| altimeter_s3 | retracker | sar | sar or plrm; changes the source retrieval |
| altimeter_s3 | min_dist_coast_km | 30 | Coastal exclusion distance in km; 0 disables it |
| altimeter_s3 | open_ocean_only | true | Apply surface-type selection when available |
| altimeter_s6 | extra_vars | none | data_01/time fields; ku: and c: group prefixes supported |
| altimeter_s6 | retracker | mle | mle or nr; nr requires Ku band |
| altimeter_s6 | band | ku | ku or c |
| altimeter_s6 | min_dist_coast_km | 30 | Coastal exclusion distance in km; 0 disables it |
| altimeter_s6 | open_ocean_only | true | Apply surface-type selection when available |
| sentinel1 | extra_vars | none | Fields on owiAzSize × owiRaSize |
| sentinel1 | qc | true | Wind-quality and surface-mask checks; false disables both |
| ascat | extra_vars | none | Fields on NUMROWS × NUMCELLS |
| buoy_ispra | lat | required | Fixed latitude in degrees, [-90,90] |
| buoy_ispra | lon | required | Fixed longitude in degrees, [-180,180] |

Use nonnegative finite coastal distances. Surface filtering and distance filtering
are separate decisions. Missing requested distance/surface fields are explicitly
recorded as filters not applied, not treated as successful screening.

## Fixed behavior: not editable YAML keys

- **CMEMS:** uses VAVH for hs, VAVH_UNFILTERED for hs_unfiltered and WIND_SPEED for wind.
  The product is edited upstream; no local coastal-distance guarantee is added.
- **Sentinel-3:** uses the selected Ku retracker at 1 Hz. Quality flags are applied
  when available. There is no qc toggle and no automatic 20 Hz to 1 Hz resampling.
- **Sentinel-6:** quality flags apply to wave height and backscatter when present;
  no local quality-flag filter is applied to wind_speed_alt. Numerical retracking
  is Ku-only. Extras are copied from their requested groups independently.
- **Sentinel-1:** QC interprets product quality flags and owiMask. Setting qc to false
  also disables land/ice/no-data/RFI screening; it is not just a wind-quality switch.
- **ASCAT:** accepts wvc_quality_flag <65536, requires one time per swath row, and
  adds 180 degrees to wind direction to express the from-direction convention.
  No configurable qc switch is implemented.
- **ISPRA buoy:** known export headers are mapped internally (hm0 to hs, mdir to
  wave_dir, etc.). All-zero sensor columns may be dropped as absent sensors.
  There is no generic CSV column-map or extra_vars option.

These fixed rules can be changed in reader code when scientifically justified.
They should not be guessed as YAML keys. A new product layout may need a new reader.

## Models and comparison settings

GRIB and NetCDF accept the same six options: rename, coords, init, lead, lead_tol,
and overlap. Their defaults and examples are in the catalogue; scientific meanings
and all matching settings are in the [campaign reference](campaign-reference.md).
Model grids must be rectilinear with one-dimensional latitude and longitude.
No automatic unit conversion or arbitrary reader expression language is provided.
