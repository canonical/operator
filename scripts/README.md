# Repository scripts

Standalone scripts that support the repository itself rather than shipping as
part of `ops`: CI helpers, release tooling, and similar. They are plain
scripts, not a package, so tests in `scripts/test/` import them by bare module
name (`pythonpath = ["scripts"]` in `pyproject.toml`).

Those tests are collected by the normal `tox -e unit` run. That is the point of
this directory: pytest skips dot-directories, so anything under `.github/`
never runs in CI.
