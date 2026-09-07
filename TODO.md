# FieldMatch — open decisions

The campaign refactor and archive separation are implemented. Remaining work
is intentionally limited to decisions that need real user feedback or data.

1. Confirm the preferred exchange format with Luigi Cavaleri. CSV is currently
   the default (comma delimiter, header row, ISO timestamps, explicit `NaN`);
   NetCDF is available with `--format netcdf` or `--format both`. If his Fortran
   workflow needs fixed-width text, a different delimiter, or a small reader
   example, define that contract before adding another writer.
2. Add small anonymized fixtures for each supported product revision as they
   become available. Existing tests cover normalization and scientific edge
   cases, but real vendor-file fixtures are the best protection against format
   drift.
3. Before public distribution, check package-name availability and add normal
   release metadata (license, authors, repository URL, changelog policy).

The previous audit and completed implementation notes are retained in
`HISTORY.md`.
