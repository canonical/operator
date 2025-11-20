# Agent Instructions for Ops

## Project Overview
Ops is the official Python framework for developing Kubernetes and machine charms within the Juju ecosystem. It provides an event-driven abstraction layer for charm developers.

## Tech Stack
- Python 3.10+ with full type hints (strict Pyright)
- Event-driven architecture (Observer pattern)
- Testing: pytest, ops-scenario for state transition testing
- Workspace monorepo: ops (core), testing, tracing

## Code Standards

### Style & Formatting
- Follow PEP 8 and conventions in STYLE.md
- Use Ruff for linting and formatting (`tox -e format`)
- Google-style docstrings for all public APIs
- Full type hints required (check with `tox -e lint`)

### Naming Conventions
- Classes: PascalCase (e.g., `CharmBase`, `PebbleReadyEvent`)
- Functions/methods: snake_case
- Constants: UPPER_CASE
- Private modules/attrs: leading underscore

### Architecture
- Event-driven: use `framework.observe(event, handler)` pattern
- Layered: Charm → Model → Framework → Storage
- State transitions: use `ops.testing.Context` for tests
- Immutability: prefer immutable state objects

## Testing Requirements
- All new code requires tests (unit + scenario tests)
- Use `ops.testing.Context` for charm testing
- Run tests with `tox` before submitting changes
- Maintain test coverage (check with `tox -e coverage`)

## Development Workflow
```bash
uv sync --all-groups  # Install dependencies
tox -e format         # Format code
tox -e lint           # Check linting include type checks
tox -e unit           # Run unit tests
```

## Key Files
- `ops/charm.py` - CharmBase, events, metadata
- `ops/framework.py` - Event system core
- `ops/model.py` - Juju model abstractions
- `ops/pebble.py` - Container workload management
- `testing/src/scenario/` - State transition testing framework

## Important Notes
- **Always** preserve backward compatibility in public APIs
- **Never** modify `ops/__init__.py` exports without review
- **Document** all breaking changes in commit messages
- See CONTRIBUTING.md for PR and commit conventions
