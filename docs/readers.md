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

`retain_qc: true` preserves a small canonical set of the product's most useful
quality evidence under `x_` names (quality, surface/mask, rain/ice and coastal
distance where available). It defaults to false so ordinary pair tables stay
compact. The provider fields and their `flag_values`/`flag_meanings` metadata are
preserved; the library does not collapse unlike mission flags into one score.
`fieldmatch scan` inventories the available meanings, product values and counts
whether or not those fields are retained in pair output. This makes the accepted
meanings selectable by name rather than requiring users to know numeric codes.

`extra_vars` defaults to none and accepts a string or list. It copies source fields
under `x_` names; it does not change the default Hs/wind retrieval or apply its QC to
the extra fields. A missing requested field emits a warning and is recorded. A field
on another time axis raises an error instead of being resampled. For Sentinel-6,
`ku:swh_ocean` becomes `x_ku_swh_ocean`; unqualified names come from data_01.

## Editable observation options

| kind | Option | Default | Values / meaning |
|---|---|---|---|
| altimeter_cmems | retain_qc | false | Preserve the upstream-unfiltered Hs as `x_hs_unfiltered` |
| altimeter_cmems | extra_vars | none | CMEMS L3 fields on time |
| altimeter_s3 | retain_qc | false | Preserve available quality, coast, surface, rain and ice fields |
| altimeter_s3 | extra_vars | none | SRAL fields on time_01 (1 Hz) |
| altimeter_s3 | retracker | sar | sar or plrm; changes the source retrieval |
| altimeter_s3 | min_dist_coast_km | 30 | Coastal exclusion distance in km; 0 disables it |
| altimeter_s3 | open_ocean_only | true | Apply surface-type selection when available |
| altimeter_s6 | extra_vars | none | data_01/time fields; ku: and c: group prefixes supported |
| altimeter_s6 | retain_qc | false | Preserve Hs/sigma0 quality plus coast, surface, rain and ice fields |
| altimeter_s6 | retracker | mle | mle or nr; nr requires Ku band |
| altimeter_s6 | band | ku | ku or c |
| altimeter_s6 | min_dist_coast_km | 30 | Coastal exclusion distance in km; 0 disables it |
| altimeter_s6 | open_ocean_only | true | Apply surface-type selection when available |
| sentinel1 | extra_vars | none | Fields on owiAzSize × owiRaSize |
| sentinel1 | retain_qc | false | Preserve wind quality, surface mask and inversion quality |
| sentinel1 | wind_quality | [acceptable, good] | Accepted `owiWindQuality` meanings shown by scan |
| sentinel1 | surface_mask | [valid] | Accepted `owiMask` meanings shown by scan |
| ascat | extra_vars | none | Fields on NUMROWS × NUMCELLS |
| ascat | retain_qc | false | Preserve `wvc_quality_flag` as `x_wind_quality` |
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
- **Sentinel-1:** `wind_quality` and `surface_mask` select accepted CF meanings;
  the reader translates them to the numeric codes declared by each product. This
  avoids the processor-version-dependent meaning of hard-coded values. OWI surface
  mask bits can occur in combination and are evaluated as bits, not enum values. A requested
  meaning absent from one processor version is reported and ignored when another
  requested meaning remains available; a selection with no available meaning fails.
- **ASCAT:** accepts wvc_quality_flag <65536, requires one time per swath row, and
  adds 180 degrees to wind direction to express the from-direction convention.
  No configurable qc switch is implemented.
- **ISPRA buoy:** known export headers are mapped internally (hm0 to hs, mdir to
  wave_dir, etc.). All-zero sensor columns may be dropped as absent sensors.
  There is no generic CSV column-map or extra_vars option.

These fixed rules can be changed in reader code when scientifically justified.
They should not be guessed as YAML keys. A new product layout may need a new reader.
Retained QC permits stricter subsets after matching; it cannot restore a value
that the provider or the configured reader already made missing. Use explicit
permissive accepted-meaning lists when the purpose is to compare defensible QC subsets.

## Models and comparison settings

GRIB and NetCDF accept the same six options: rename, coords, init, init_cycle,
lead, and lead_tol. Their defaults and examples are in the catalogue; scientific meanings
and all matching settings are in the [campaign reference](campaign-reference.md).
Model grids must be rectilinear with one-dimensional latitude and longitude.
No automatic unit conversion or arbitrary reader expression language is provided.
