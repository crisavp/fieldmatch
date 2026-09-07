# Explicit model comparisons and reusable figures

For runnable steps from raw Harry data, use the [analysis guide](analysis-guide.md).
The snippets here illustrate the Python API; model datasets/result paths must
already exist.

FieldMatch 0.3 keeps scientific preparation in the core and plotting in an
optional module in the same package. Harry-specific experiment selection lives
in the example script and YAML, not in the core.

## Select the scientific comparison

```python
from fieldmatch.grids import compare_grids, grid_stats

result = compare_grids(analysis, era5, 'hs',
    reference_name='analysis', candidate_name='ERA5',
    space_method='bilinear', time_basis='valid_time')
summary = grid_stats(result)
```

Inputs are normalized xarray model datasets with increasing, unique time/lat/lon
coordinates, fields ordered (time, lat, lon), and compatible physical metadata.
Use `open_model` to normalize GRIB/NetCDF first. The first dataset defines the
reference grid. Fields on the second grid are sampled onto it; a finer target
grid does not create finer physical resolution. Both output fields use exactly
the common finite mask at each retained time. Missing contributing corners are
rejected, zero-weight corners ignored and spatial extrapolation prohibited.
Directions are circular; atmospheric wind derives from interpolated components
when u10/v10 are available. The same sampler serves observation matching.

Select `space_method='bilinear'` or `'nearest'` explicitly in Python. YAML grid
groups inherit the documented spatial defaults from `matching_defaults`.
`time_basis` is always explicit:

| Basis | Selection at exact common valid times |
|---|---|
| `valid_time` | No extra initialization/lead equality restriction; use for analysis/reference consistency |
| `same_init` | Both initializations must be present, finite and equal |
| `same_lead` | Both lead coordinates must be present, finite and equal |

These filters do not create a lead-time skill curve. At the same valid time,
equal lead normally implies equal initialization. To investigate different lead
windows, select those windows explicitly before comparison. A single forecast
should first be selected using the dataset's `init` or `lead` options.
Temporal interpolation and nearest-time matching are deliberately absent here.
No shared times or no shared finite cells produces an explicit error.

The grid may be irregularly spaced but must be rectilinear. Curvilinear,
unstructured and periodic/dateline-wrapping grids need explicit preprocessing.
There is no conservative regridding. Use this sampler for point-like bulk
fields such as Hs, not to claim conservation of integrated extensive quantities.
Area weights use spherical cells with edges halfway between coordinates,
extrapolated half a spacing at boundaries and clipped at the poles. The mask may
vary with time, so inspect `valid_area_fraction` before interpreting trends.
`mean_difference` is the arithmetic mean signed difference (wrapped for angles),
not a declaration that the reference is truth. Direction differences near
+/-180 degrees deserve distribution inspection rather than a mean alone.

## Keep plotting separate

```python
from fieldmatch.results import open_result
from fieldmatch.common import common_sample
from fieldmatch.plotting import comparison_panels, time_series, scatter, save_figure

grid = open_result('grid_comparison.nc')
fig, axes = comparison_panels(grid, '2026-01-20T18:00', clim=(0, 10), difference_limit=2)
save_figure(fig, 'model_panels.pdf')

pairs = {'Analysis': open_result('analysis_pairs.nc'),
         'ERA5': open_result('era5_pairs.nc')}
aligned, counts = common_sample(pairs)  # Explicit scientific sample selection.
fig, ax = time_series(aligned)
save_figure(fig, 'buoy.png')
```

`field_map` draws a reference, candidate or difference field. `comparison_panels`
shares limits between the two fields and uses symmetric limits for differences.
Maps require an exact saved timestamp. They use geographic axes and an aspect
correction at the mean latitude; they do not fetch coastlines or imply a global
map projection. Missing common cells remain blank.

`time_series` requires one station and identical observation IDs, positions,
values and times across models. It never intersects samples itself. Default
markers show matched values at observation times; connect=True draws straight
visual links and does not temporally interpolate model values. The underlying
model timestamps and offsets remain in the results. `scatter` plots saved finite
pairs. Both return ordinary Matplotlib objects for titles, layouts and styling.

`save_figure` writes a PNG/PDF/SVG (chosen by extension) plus a JSON sidecar with
comparison metadata, plot choices, final axes and hashes. A dataset loaded with
`open_result` carries the input result path and SHA256. In-memory datasets have
no file fingerprint until saved/reopened. Custom Matplotlib artists may need
extra captions; their complete implementation is not serialized by the sidecar.

The legacy `stats --scatter` command remains compatible. For new figures, use the
plotting module or the terminal study script. Install `.[plot]` for Matplotlib,
or `.[interactive]` for optional VS Code cells. Plotting libraries are not imported by
the numerical core.

## Plot function quick reference

| Function | Input and useful options | Returns |
|---|---|---|
| `field_map(ds, time, ...)` | Prepared grid result; `field` is reference/candidate/difference; `clim`, `cmap`, `title`, `ax` | `(fig, ax)` |
| `comparison_panels(ds, time, ...)` | Prepared grid result; `clim` shared between fields, `difference_limit`, `figsize` | `(fig, axes)` |
| `time_series(tables, ...)` | Label-to-pair-dataset mapping for one station on identical observations; `connect`, `title`, `ax` | `(fig, ax)` |
| `scatter(ds, ...)` | One prepared observation/model result; `title`, `ax` | `(fig, ax)` |
| `save_figure(fig, path, ...)` | File extension selects PNG/PDF/SVG; `dpi` defaults to 180 | Saved `Path` and adjacent JSON sidecar |

Use `ax.set(...)` and ordinary Matplotlib layouts for further customization. The
helpers infer the variable from the result metadata; choose correct physical
units and limits for the new variable. Extra analysis filters belong in your
script or interactive cells and are not fully reconstructed from a figure sidecar.
