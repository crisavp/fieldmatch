# Adding an observation reader

Readers isolate product-specific file structure and quality conventions from
the collocation algorithm. Downstream code sees only one canonical structure.

## Canonical contract

A reader accepts one path plus its declared options and returns either:

- an `xarray.Dataset` with dimension `obs`; or
- `None` when the file contains no usable observations.

The dataset must have one-dimensional `time`, `lat` and `lon` coordinates on
`obs`. Longitude must be normalized to `[-180, 180]`. Data variables use
canonical names such as `hs`, `wind_speed`, `wind_dir`, `mwd`, `mwp` and `tp`.

Readers must record enough provenance to explain the transformation:

- `reader`;
- `<name>_source` for each standardized variable and coordinate;
- `<name>_filter` where quality control is relevant;
- `n_read`, `n_rejected_qual` and `n_rejected_coastal` as applicable;
- a clear `land_mask` description, including when no mask was available.

Use `_cloud()` to construct the canonical dataset and `_finish()` for common
geolocation cleanup. Use `_collect_extras()` for user-requested pass-through
variables rather than implementing another namespace.

## Register the reader

Reader implementation, accepted campaign options and source layout belong in
one `ReaderSpec` in `src/fieldmatch/readers.py`:

```python
def read_my_product(file, accepted_quality=("good",), extra_vars=None):
    with xr.open_dataset(file) as source:
        quality_values, quality_names = _select_flag_meanings(
            source["quality_flag"], accepted_quality, "accepted_quality")
        keep = np.isin(source["quality_flag"].values, quality_values)
        values = {"hs": source["source_wave_height"].values}
        values["hs"] = np.where(keep, values["hs"], np.nan)
        provenance = {
            "reader": "my_product",
            "hs_source": "source_wave_height",
            "hs_filter": f"quality_flag in {quality_values} ({quality_names})",
            "lat_source": "latitude",
            "lon_source": "longitude",
            "time_source": "time",
            "land_mask": "none (not supplied by product)",
            "n_read": int(source.sizes["record"]),
            "n_rejected_qual": int(np.count_nonzero(~keep)),
            "n_rejected_coastal": 0,
        }
        values, provenance = _collect_extras(
            source, extra_vars, "record", values, provenance
        )
        return _cloud(
            source["time"].values,
            source["latitude"].values,
            source["longitude"].values,
            values,
            provenance=provenance,
        )


READERS = {
    # existing readers...
    "my_product": ReaderSpec(
        read_my_product,
        frozenset({"accepted_quality", "extra_vars"}),
        dim="record",
    ),
}
```

Do not add a second option/layout registry. Campaign validation, `read_obs`
dispatch and `fieldmatch vars` all derive their behavior from `READERS`.

## Scientific rules

- Never map a raw variable to a canonical name merely because units match;
  verify the product definition and direction convention.
- `wind_dir` is meteorological “from”, degrees clockwise from north.
- Preserve integer flags and useful source metadata for `extra_vars`.
- Do not reshape a variable from a different sampling axis into the reader's
  records. Refuse it with the source and required dimensions named.
- Prefer accepted flag meanings over numeric codes or a generic quality boolean;
  validate them against the product metadata and record the effective values.
- Missing flags must be recorded as unfiltered, not silently treated as good.

## Required tests

Add focused tests under `tests/readers/`. At minimum cover:

1. canonical dimensions, coordinates and standardized variable names;
2. longitude normalization and invalid geolocation removal;
3. quality-good, quality-bad and missing-quality cases;
4. empty input or no usable observations;
5. each accepted reader option and rejection of invalid values;
6. `extra_vars`, including dtype/metadata and wrong-axis rejection;
7. provenance sources, filters and rejection counts;
8. a format-specific edge case likely to regress.

Use small synthetic files first. Add a tiny anonymized real-product fixture
when licensing permits, and document its origin in `tests/fixtures/README.md`.
See [testing.md](testing.md) for test conventions and commands.

## Quantity and record metadata (0.2)

Preserve source units through masking. `_cloud` supplements known canonical
quantity definitions only when provider units are absent; incompatible units
are not converted. Keep the original flattened record index before filtering.
`read_obs` combines that index with reader kind and content hash to create
stable observation IDs. `_open_sea_cloud` preserves indices across coastal
filtering. New readers that drop rows earlier must pass `record_index` explicitly.
