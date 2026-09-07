# Testing FieldMatch

Tests are grouped by the boundary they protect:

```text
tests/
├── unit/          numerical collocation, forecast and statistics behavior
├── readers/       product normalization, QC and reader contracts
├── integration/   campaign files, CLI, manifests and output lifecycle
└── fixtures/      documented, small sample products when needed
```

## Run the suite

From an activated development environment:

```bash
pytest -q
```

Run one boundary while developing:

```bash
pytest -q tests/readers
pytest -q tests/unit/test_collocation.py
pytest -q tests/integration -k csv
```

## Test style

- Test public behavior or a scientifically meaningful internal contract.
- Give tests descriptive names that state the expected result.
- Build the smallest hand-checkable arrays that demonstrate the behavior.
- Use `tmp_path` for generated NetCDF, CSV, YAML and output files.
- Use `pytest.warns` or `pytest.raises` to pin intentional warnings/failures.
- Compare floating-point results with `pytest.approx` or `numpy.testing`.
- Assert provenance and rejection counts when testing filtering.
- Never depend on the user's archive, network, absolute paths or execution
  order.

## Reader tests

Synthetic xarray datasets written to `tmp_path` are preferred for ordinary
reader behavior. A reader test should make the source convention visible in
the fixture construction so expected values can be verified by inspection.

Real vendor fixtures are useful for group layout, encoding and metadata drift.
They must be small, anonymized where necessary, legally redistributable and
described in `tests/fixtures/README.md`. Do not commit a full granule merely to
exercise three records.

## Numerical tests

Use tiny regular grids with known interpolation results. Direction tests must
include wraparound near north. Forecast tests should distinguish valid time,
initialization and lead, and should include duplicated valid times where the
shortest-lead selection matters.

## Integration tests

Invoke the Typer application with `typer.testing.CliRunner`. A workflow test
should create its campaign and source files under `tmp_path`, invoke the CLI,
then verify output content and lifecycle—not just exit code. Important cases
include:

- default CSV and explicit NetCDF/both;
- statistics consuming a portable CSV;
- no plot unless `--scatter` is requested;
- atomic output and manifest completion;
- a failed rerun making an older output unacceptable.

Before submitting a change, run the complete suite plus:

```bash
fieldmatch doctor
python -m pip wheel --no-deps --no-build-isolation . -w /tmp/fieldmatch-wheel
```
