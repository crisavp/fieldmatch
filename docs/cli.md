# Command-line reference

Start with `fieldmatch --help`. Each command also accepts `--help`, for example
`fieldmatch run --help`. CAMPAIGN means the path to your YAML, not its campaign name.

| Command | Use |
|---|---|
| `config-example --output study.yaml` | Write the fully commented configuration catalogue, including every built-in reader. |
| `info RESULT` | Validate and explain a saved comparison or PNG; `--details` shows the complete provenance. |
| `doctor` | Check installation and data-reading engines. |
| `scan CAMPAIGN` | Inventory source files, forecast metadata/selection, coverage, quantities, and principal quality flags with values/counts. |
| `vars CAMPAIGN DATASET` | Examine standardized variables and source fields for one dataset key. `--all` includes nonstandard fields and alternative axes/cadences. |
| `run CAMPAIGN --describe` | Preview every declared comparison's resolved settings. Does not compute comparisons or write results. |
| `run CAMPAIGN` | Execute all named comparisons and variables in the YAML. |
| `compare CAMPAIGN NAME` | Execute only one named comparison. Also accepts `--describe`. |
| `collocate CAMPAIGN OBS MODEL -v hs` | Advanced direct obs/model matching when no named comparison is declared. |
| `stats RESULT` | Score saved observation pairs or summarize a saved grid comparison. |

The usual study needs scan, run and a plotting script. Other commands remain useful
for diagnosis, individual experiments and existing scripts; none are obsolete.

For models, scan labels the raw time representation as `forecast
(initialization + lead)`, `valid-time only`, or ambiguous. Forecast reports list
the available initialization range and UTC cycles, lead range/increments, raw
valid-time coverage, configured `init`/`init_cycle`/`lead` selection, and the
loaded valid-time coverage. This classification comes from file metadata;
filenames are not interpreted as forecast provenance.

For observations, scan lists the principal provider quality/context fields,
their named values and counts after dataset screening, the applied reader
filters, and whether those fields will be retained in pair output. It performs
this inventory even when `retain_qc` is false.

## Output formats

`run` defaults to `--format both` (CSV and NetCDF). `compare` defaults to CSV for
observation pairs and NetCDF for grids. `collocate` defaults to CSV. Use `--format
both` when you want portable tables and plotting-ready fields. For observation
pairs the formats contain the same accepted samples; grid CSV contains spatial
statistics, while NetCDF contains full fields. Each result has a JSON manifest.

## Advanced direct matching

Prefer named YAML comparisons for reproducible studies. `collocate` offers explicit
one-off choices; they are recorded in the result manifest:

- `--variable hs` (or `-v hs`): quantity to match. Repeat for independent quantities.
- `--tol-minutes 0`: exact observation/model times. Other values permit nearest-time
  matching within that many minutes. Omit to use configured/default behavior.
- `--lead 24` or `--lead 12-35`: forecast hours since initialization to select.
- `--lead-tol`: allowed fallback distance in hours when the requested lead is absent;
  zero means no fallback. This is different from observation-time tolerance.
- Distinct forecasts producing the same valid time are rejected; narrow the
  dataset's initialization or lead selectors to obtain a unique forecast view.
- `--obs-variable` and `--model-variable`: source-field names for one quantity.
  Dataset mappings and per-variable YAML declarations are clearer for larger studies.

## Statistics options

`stats RESULT` prints statistics. `--output scores.csv` also saves them.
`--by-lead` separates observation-pair scores by forecast age; `--lead-bin 24`
sets bins [0,24), [24,48), etc., in hours. Bin width is used only with `--by-lead`.
`--scatter` saves observation/model scatter PNGs beside the input and requires the
plotting extra. It cannot be combined with `--by-lead`. Grid statistics use the
saved exact times; neither option applies to grid comparisons.

## Preview versus provenance

Describe uses colored panels with aligned settings; colors follow terminal capabilities. It resolves configuration but
does not inspect raw data, guarantee coverage or create JSON files. Result and
figure JSON files are automatic [provenance records](output-formats.md#why-are-there-json-files).

## Why both collocate and compare?

For an observation/model pair they call the same scientific engine. `collocate`
takes dataset keys and explicit CLI options, without a named comparison block.
`compare` reads a named YAML block, including independent settings for each
variable, and supports both observation/model pairs and model/model grids.
`run` executes every named comparison. Prefer compare/run for a reusable study;
collocate remains an advanced one-off/API-compatible entry point.

A direct `collocate campaign.yaml buoy model -v hs` does **not** look up a named
comparison's per-variable settings. It uses matching_defaults plus explicit CLI
choices. Results are equivalent only if the effective settings and inputs match.
