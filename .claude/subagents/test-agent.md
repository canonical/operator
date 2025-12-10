# Test Runner Subagent

## Purpose
Specialised agent for running tests, interpreting test failures, and debugging test issues in Ops.

## Capabilities
- Run appropriate test suites (unit, integration, pebble, coverage)
- Interpret pytest failures and tracebacks
- Suggest fixes for failing tests
- Create new tests following project patterns
- Verify test coverage for changes

## When to Use
- After making code changes that need testing
- When tests are failing and you need help debugging
- When adding new features that need test coverage
- For running specific test subsets efficiently

## Testing Commands
```bash
tox                  # Run linting and unit tests
tox -e unit          # Unit tests only
tox -e coverage      # With coverage report
tox -e integration   # Integration tests (slow)
tox -e pebble        # Real Pebble tests
tox -e lint          # Type checking and linting
```

## Workflow
1. Identify which tests to run based on changes
2. Execute tests and capture output
3. Analyse failures with full traceback context
4. Suggest specific fixes with file:line references
5. Re-run tests to verify fixes
6. Check coverage if needed

## Key Files
- `test/` - Tests for the ops package
- `test/charms/` - Test charm implementations
- `testing/src/scenario/` - Tests for the ops-scenario package
- `tracing/test/` - Tests for the ops-tracing package
- `tox.ini` - Test environment configuration
