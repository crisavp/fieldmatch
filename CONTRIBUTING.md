# Contributing to FieldMatch

## Development setup

```bash
conda env create -f environment.yml
conda activate fieldmatch
python -m pip install -e .
pytest -q
```

Install `.[plot]` only when changing or checking the optional scatter output.

## Change workflow

1. Identify the boundary being changed: reader, model normalization,
   collocation, statistics, CLI/output lifecycle or documentation.
2. Add or update the smallest regression test that demonstrates the intended
   behavior.
3. Implement the change without introducing product-specific logic downstream
   of its reader.
4. Run the focused test directory, then the complete suite.
5. Update the campaign reference, output contract or examples when the public
   interface changes.

Scientific behavior changes must describe the former and new conventions and
pin the new result with a hand-checkable test. Never silently change a quality
filter, direction convention, time tolerance or forecast selection rule.

## Readers

Follow [docs/adding-readers.md](docs/adding-readers.md). A new reader is not
complete until it has one `ReaderSpec`, provenance, option validation and its
reader tests. Do not add parallel registries in the campaign or inspection
modules.

## Tests

Follow [docs/testing.md](docs/testing.md). Keep tests independent of personal
data paths and external services. Generated synthetic fixtures belong in test
code; redistributable vendor samples belong in `tests/fixtures/` with a short
provenance/license note.

## Scope

FieldMatch accepts finite campaign comparisons and produces pair/statistics
outputs. Incremental archive maintenance, download orchestration and additional
plot families are out of scope. Proposals that expand the public workflow
should explain why they cannot remain a separate tool.
