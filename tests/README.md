# Automated tests

This directory contains import-safe automated regression tests only.

- Run the fast critical suite with `make test`.
- Run every automated test with `make test-all`.
- Keep test inputs under `tests/fixtures/`.
- Put scripts that call live services, print diagnostics, or create ad-hoc files
  under `tools/manual_checks/`; they must not be discovered automatically.

Tests resolve project assets from the repository root so moving the test suite
does not change the paths used by the application.
