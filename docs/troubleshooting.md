# Troubleshooting

## Installation and paths

- **Command/import missing:** activate the environment used to install FieldMatch.
  Check `python -c "import sys; print(sys.executable)"`; install with that Python's
  `python -m pip`. See [installation](installation.md).
- **GRIB C library cannot load:** use `fieldmatch doctor`. In conda, install cfgrib
  and eccodes from conda-forge; for pip environments, supply the native library or
  use the new-conda-environment route. The doctor checks the engine, not every file.
- **No files:** run the script's `inspect` action. Dataset paths resolve from the
  YAML's data_root, and data_root resolves from the YAML. An absolute data_root is
  simplest for a first setup. It must contain the directories used by the globs.
- **Script runs from one directory but not another:** use an absolute script path.
  Its `--config` is script-relative; `fieldmatch` CLI positional paths are ordinary
  shell-relative paths. Interactive config paths must be absolute.
- **Interactive config missing:** set `INTERACTIVE_CONFIG` in analyze.py and rerun
  the setup cell. The script intentionally does not guess a project directory.
- **VS Code uses another Python:** select the installed environment as the
  Interactive Window kernel. Install `.[interactive]` there. A working terminal
  environment does not automatically mean the editor selected the same kernel.
- **No GUI windows:** plain `plot` saves PNG/HTML without a display. `--show` needs a
  graphical Matplotlib backend. In VS Code use the interactive plot cell instead.

## Scientific configuration

Use `fieldmatch vars /absolute/path/to/config.yaml dataset` to inspect source
variables and `fieldmatch compare ... comparison --describe` for resolved choices.
Names are your YAML keys, not built-in product aliases.

| Problem | Interpretation / next step |
|---|---|
| `matching` or singular comparison `variable` rejected | Use matching_defaults and variables: {hs: {}}; settings go directly under the variable. |
| A declaration appears to vanish | Check duplicate YAML keys. Edit existing mappings; the current parser can silently replace duplicate keys. |
| Missing fields or incompatible quantity/units | Check definitions and rename mappings. Renaming metadata is not unit conversion; energy and other mean periods are not interchangeable. |
| Outside forecast coverage | Check initialization and valid times. Increasing tolerance is not a remedy for observations before the forecast starts. |
| Time gaps exceed tolerance | Inspect cadence and actual observation times. A wider tolerance changes the scientific sample and phase offsets. |
| No common grid times | Grid time matching is exact; same_init/same_lead add equality restrictions. Observation tolerance does not apply. |
| Spatial values missing | Inspect position, domain and contributing corners. There is no wet-neighbour search or extrapolation. |
| Conflicting forecast overlap | Select init/lead explicitly. shortest_lead is a deliberate freshest-forecast composite, not one forecast trajectory. |
| Direction missing | Opposing directions or a nearly zero wind vector may make direction undefined. Do not replace it with zero degrees. |

## Saved results and plotting

- **No complete result:** run comparisons first. A failed/running manifest means an
  existing output file must not be treated as a successful current result.
- **Stale after changing YAML:** rerun all comparisons. Current fingerprints cover
  the whole campaign. Use separate configs/output folders to preserve experiments.
  The script also checks the selected YAML against saved outputs, so a different
  config cannot silently reuse them.
- **Only cosmetic settings changed:** rerun `plot` or the interactive plot cell.
  Do not run the expensive comparison cell again unless scientific inputs changed.
- **Grid CSV cannot make a map:** it is a summary table. Use NetCDF for fields/mask.
- **Map time absent:** inspect grid.time.values and choose an exact timestamp.
- **Blank grid time:** inspect n_common and valid_area_fraction; a comparison may
  have some times with no common finite cells. Maps do not fill missing cells.
- **No common observation sample:** examine native coverage and the comparison
  groups. Distinct scientific experiments may need separate groups in your script.
- **Peak changed after matching:** inspect raw/native values. The largest accepted
  pair is not necessarily the largest observation or model output in the event.
- **Some plots use inappropriate limits:** edit FIELD_LIMITS/DIFFERENCE_LIMITS for
  your variable. Those example choices are visible Python settings, not physical
  unit conversion or automatic scientific recommendations.

For a reproducible issue, keep the YAML, version, resolved settings, error/manifest
and a small shareable input sample. State the expected physical comparison.
