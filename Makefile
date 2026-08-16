# We're using Make as a command runner, so always make (avoids need for .PHONY).
MAKEFLAGS += --always-make

help:  # Display help
	@echo "Usage: make [target] [ARGS='additional args']\n\nTargets:"
	@awk -F'#' '/^[a-z0-9-]+:/ { sub(":.*", "", $$1); print " ", $$1, "#", $$2 }' Makefile | column -t -s '#'

all: format lint unit  # Run all quick, local commands

benchmark:  # Run benchmark tests
	uv run --group unit --group benchmark \
		pytest -v --tb native \
		test/benchmark \
		testing/tests/benchmark \
		$(ARGS)

coverage:  # Run unit tests with coverage
	COVERAGE_CORE=sysmon uv run --group unit --group coverage \
		coverage run --source=ops,testing/src/scenario \
		--branch -m pytest \
		--ignore=test/smoke \
		--ignore=test/integration \
		--ignore=test/benchmark \
		--ignore=testing/tests/benchmark \
		--ignore=tracing/test \
		--ignore=examples \
		-v --tb native \
		-W "ignore:Harness is deprecated:PendingDeprecationWarning" \
		$(ARGS)
	uv run --group coverage coverage report
	mv .coverage .coverage-ops

coverage-html:  # Generate HTML coverage report
	uv run --group coverage coverage html

coverage-report:  # Combine ops and tracing coverage reports
	mkdir -p .report
	uv run --group coverage coverage combine -a .coverage-ops
	uv run --group coverage coverage combine -a .coverage-tracing
	uv run --group coverage coverage xml -o .report/coverage.xml
	uv run --group coverage coverage report

coverage-tracing:  # Run tracing tests with coverage
	cd tracing && \
	COVERAGE_CORE=sysmon uv run --group unit --group coverage \
	coverage run --source=. --branch -m pytest \
	-v --tb native \
	-W "ignore:Harness is deprecated:PendingDeprecationWarning" \
	$(ARGS)
	mv tracing/.coverage .coverage-tracing

docs:  # Build documentation
	MAKEFLAGS='' $(MAKE) -C docs html

draft-release:  # Create a draft GitHub release
	uv run --group release python release.py $(ARGS)

fix:  # Auto-fix lint issues
	uv run --group lint ruff check --preview --fix
	uv run --group lint ruff format --preview

format:  # Format the Python code
	uv run --group lint ruff format --preview

integration:  # Run integration tests
	uv run --group integration \
		pytest -vvv --tb native \
		$(if $(ARGS),$(ARGS),test/integration/)

lint:  # Lint, spell check and static type checking
	uv run --group lint --group unit ruff check --preview
	uv run --group lint --group unit ruff format --preview --check
	uv run --group lint --group unit codespell $(ARGS)
	uv run --group lint --group unit pyright $(ARGS)

pebble:  # Run real Pebble tests
	umask 0; pebble run --http=':4000' --create-dirs >/dev/null 2>&1 & sleep 1
	PEBBLE=/tmp/pebble RUN_REAL_PEBBLE_TESTS=1 \
	uv run --group unit \
		pytest -v --tb native test/test_real_pebble.py $(ARGS)
	killall -y 3m pebble

post-release:  # Perform post-release actions
	uv run --group release python release.py --post-release $(ARGS)

smoke:  # Run smoke tests against a Juju controller
	find test/charms/test_smoke \
		\( -name '*.whl' -o -name '*.tar.gz' -o -name pyproject.toml -o -name uv.lock \) \
		| xargs -r rm -vf
	uv build --out-dir=test/charms/test_smoke --wheel .
	cp test/charms/test_smoke/reference-pyproject.toml \
		test/charms/test_smoke/pyproject.toml
	uv --project test/charms/test_smoke \
		add test/charms/test_smoke/ops-3.*.whl
	uv run --group integration \
		pytest -v --tb native --log-cli-level=INFO -s \
		$(ARGS) test/smoke

unit:  # Run unit tests, eg: make unit ARGS='-k test_status'
	uv run --group unit --group xdist \
		pytest -p no:benchmark \
		--doctest-modules -n auto \
		--ignore=docs \
		--ignore=release.py \
		--ignore=test/smoke \
		--ignore=test/integration \
		--ignore=test/benchmark \
		--ignore=testing/tests/benchmark \
		--ignore=tracing/test \
		--ignore=examples \
		--ignore=test/charms \
		-v --tb native \
		-W error \
		-W "ignore:Harness is deprecated:PendingDeprecationWarning" \
		$(ARGS)
