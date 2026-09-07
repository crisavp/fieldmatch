# Command-line reference

Start with `fieldmatch --help`. Each command also accepts `--help`, for example
`fieldmatch run --help`. CAMPAIGN means the path to your YAML, not its campaign name.

| Command | Use |
|---|---|
| `doctor` | Check installation and data-reading engines. |
| `scan CAMPAIGN` | Inventory source files, coverage and available quantities. |
| `vars CAMPAIGN DATASET` | Examine standardized variables and source fields for one dataset key. `--all` includes nonstandard fields and alternative axes/cadences. |
| `run CAMPAIGN --describe` | Preview every declared comparison's resolved settings. Does not compute comparisons or write results. |
| `run CAMPAIGN` | Execute all named comparisons and variables in the YAML. |
| `compare CAMPAIGN NAME` | Execute only one named comparison. Also accepts `--describe`. |
| `collocate CAMPAIGN OBS MODEL -v hs` | Advanced direct obs/model matching when no named comparison is declared. |
| `stats RESULT` | Score saved observation pairs or summarize a saved grid comparison. |

The usual study needs scan, run and a plotting script. Other commands remain useful
for diagnosis, individual experiments and existing scripts; none are obsolete.

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
- `--overlap error` or `--overlap shortest_lead`: reject multiple forecasts for one
  valid time, or explicitly choose the shortest available forecast lead.
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

Describe uses labelled terminal blocks like scan. It resolves configuration but
does not inspect raw data, guarantee coverage or create JSON files. Result and
figure JSON files are automatic [provenance records](output-formats.md#why-are-there-json-files).
