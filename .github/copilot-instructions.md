# Copilot Instructions for Ops

## Project Overview

Ops is the official Python framework for developing Kubernetes and machine charms within the Juju ecosystem. It provides an event-driven abstraction layer that allows charm developers to respond to lifecycle events and manage applications.

This workspace is a monorepo containing:
- **`ops/`** - Core framework providing the event system, charm base classes, and model abstractions
- **`testing/`** - The `ops-scenario` state transition testing framework (accessed as `ops.testing`)
- **`tracing/`** - The `ops-tracing` observability integration

## Core Architecture

The framework follows a layered, event-driven architecture:

```
Charm (charm.py) - User code inherits from CharmBase
    ↓
Model (model.py) - Juju model abstractions (Unit, Application, Relation, etc.)
    ↓
Framework (framework.py) - Event system core (Observer pattern, Handle system)
    ↓
Storage (storage.py) - Persistence layer
```

Key concepts:
- **Event-driven**: Charms respond to Juju lifecycle events using `framework.observe(event, handler)`
- **Handles**: Hierarchical naming system for objects (`parent/kind[key]`)
- **State transitions**: Test charms using `ops.testing.Context` for arrange/act/assert testing
- **Immutability**: Prefer immutable state objects where possible

## Development Standards

### Language & Type Checking
- Python 3.10+ with **full type hints** required
- Strict Pyright type checking - no untyped code
- Use `typing_extensions` for advanced type features when needed
- All public APIs must be fully typed

### Code Style
- **Follow PEP 8** and conventions in `STYLE.md`
- Use **Ruff** for formatting and linting (`tox -e format` to format)
- **Google-style docstrings** for all public APIs
- Docstrings should be informative for **users**, not just developers

### Naming Conventions
```python
# Classes: PascalCase
class CharmBase: ...
class PebbleReadyEvent: ...

# Functions/methods: snake_case
def observe_event(): ...

# Constants: UPPER_CASE
MAX_RETRY_COUNT = 3

# Private: leading underscore
_internal_helper()
```

### Import Style
```python
# DO: Import modules, not objects (except typing)
import ops
import subprocess
from typing import Optional, Tuple  # typing is an exception

class MyCharm(ops.CharmBase):
    def handler(self, event: ops.PebbleReadyEvent):
        subprocess.run(['echo', 'hello'])

# DON'T: Import objects directly
from ops import CharmBase, PebbleReadyEvent  # Avoid this
```

Within the `ops` package, use relative imports:
```python
from . import charm
from .framework import Handle
```

### Code Patterns

**Compare enums by identity:**
```python
# DO
if status is pebble.ServiceStatus.ACTIVE:
    ...

# DON'T
if status == pebble.ServiceStatus.ACTIVE:
    ...
```

**Avoid nested comprehensions:**
```python
# DO - Use explicit loops for clarity
units = []
for app in model.apps:
    for unit in app.units:
        units.append(unit)

# DON'T
units = [unit for app in model.apps for unit in app.units]
```

## Testing Requirements

All new code **must** include tests:

1. **Unit tests** - Test individual components
2. **Scenario tests** - Preferred approach using `ops.testing.Context` for state transition testing

```python
from ops import testing
from charm import MyCharm

def test_install():
    # Arrange
    ctx = testing.Context(MyCharm)
    state_in = testing.State()

    # Act
    state_out = ctx.run(ctx.on.install(), state_in)

    # Assert
    assert state_out.unit_status == testing.MaintenanceStatus('Installing')
```

**Legacy Harness tests** are discouraged - prefer `ops.testing.Context` for new tests.

Run tests with:
```bash
tox -e unit              # Run all unit tests
tox -e unit -- test/test_charm.py  # Run specific file
tox -e coverage          # Run with coverage
tox -e lint              # Lint and type check
```

## Common Development Tasks

```bash
# Setup environment
uv sync --all-groups

# Format code (always run before committing)
tox -e format

# Run linting and type checks
tox -e lint

# Run unit tests
tox -e unit

# Build documentation locally
make -C docs html
make -C docs run  # Serve with auto-refresh

# Run Pebble integration tests (requires pebble installed)
tox -e pebble
```

## Documentation Guidelines

Follow the Diátaxis framework for documentation structure:
- **Tutorials** (`docs/tutorial/`) - Learning-oriented
- **How-to guides** (`docs/howto/`) - Task-oriented
- **Reference** - Generated from docstrings
- **Explanation** (`docs/explanation/`) - Understanding-oriented

### Docstring Style

Use Google-style docstrings with proper formatting:

```python
def my_function(param: str, count: int = 1) -> list[str]:
    """Brief one-line summary.

    Longer description providing more context. Focus on what the function
    does for users, not implementation details.

    Args:
        param: Description of the parameter. Use British spelling.
        count: Number of times to repeat. Defaults to 1.

    Returns:
        A list of processed strings.

    Raises:
        ValueError: If count is negative.

    Example:
        >>> my_function("hello", 2)
        ['hello', 'hello']
    """
```

**Documentation writing tips:**
- Use **active voice**: "Create a check" not "A check is created"
- Be **objective**: Avoid "simply", "easily", "just"
- Be **concise**: No long introductions, get to the point
- Use **British English**: "colour", "serialise", "labelled"
- State conditions **positively**: What should happen, not what shouldn't
- Spell out abbreviations: "for example" not "e.g."
- Use **sentence case** for headings

### Version Dependencies

Only document Juju version dependencies in docstrings:

```python
def new_feature():
    """Do something new.

    .. jujuadded:: 3.5
        This feature requires Juju 3.5 or higher.
    """
```

Don't document Ops version changes in docstrings - that's in the changelog.

## Important Constraints

### Backward Compatibility
**CRITICAL**: Never break backward compatibility in public APIs without explicit approval. The framework is used by hundreds of charms.

- **Do not** modify `ops/__init__.py` exports without review
- **Do not** change signatures of public methods
- **Do not** remove or rename public classes/functions
- **Always** preserve existing behavior unless fixing a bug

### Public API Surface

The public API is defined by:
1. Exports in `ops/__init__.py`
2. Any class/function without a leading underscore in `ops/*.py`
3. Documented in reference documentation

### File Structure

```
ops/
  __init__.py      - Public API exports (CAREFUL: review before changing)
  charm.py         - CharmBase, events, metadata
  framework.py     - Event system core
  model.py         - Juju model abstractions
  pebble.py        - Container workload management
  testing.py       - Harness (legacy) testing API
  _private/        - Internal implementation details

test/
  test_*.py        - Unit tests matching source files
  charms/          - Test charms
  integration/     - Integration tests

testing/           - ops-scenario (ops.testing) implementation
  src/scenario/    - State transition testing framework
  tests/           - Tests for ops.testing

docs/              - User-facing documentation
```

### Test Organization

- Tests for `ops/main.py` go in `test/test_main.py`
- Large test suites may get their own file: `test/test_main_foo.py`
- Scenario tests have a different structure - follow existing patterns

## Common Patterns

### Creating a new event type:
```python
class MyCustomEvent(EventBase):
    """Emitted when something custom happens.

    Attributes:
        data: Custom data associated with the event.
    """

    def __init__(self, handle: Handle, data: str):
        super().__init__(handle)
        self.data = data

    def snapshot(self) -> dict[str, Any]:
        return {'data': self.data}

    def restore(self, snapshot: dict[str, Any]):
        self.data = snapshot['data']
```

### Observing events in a charm:
```python
class MyCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        # Observe events using framework.observe
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.config_changed, self._on_config_changed)

    def _on_install(self, event: ops.InstallEvent):
        """Handle the install event."""
        self.unit.status = ops.MaintenanceStatus('Installing...')
```

### Testing a charm with scenario:
```python
def test_relation_changed():
    ctx = testing.Context(MyCharm)
    relation = testing.Relation('db', remote_app_data={'host': 'postgres'})
    container = testing.Container('app', can_connect=True)
    state_in = testing.State(
        leader=True,
        relations={relation},
        containers={container},
    )

    state_out = ctx.run(ctx.on.relation_changed(relation), state_in)

    assert state_out.unit_status == testing.ActiveStatus()
```

## Pull Request Guidelines

Follow conventional commit style in PR titles:
- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `refactor:` - Code refactoring
- `test:` - Test additions or updates
- `chore:` - Maintenance tasks
- `ci:` - CI/CD changes

Examples:
- `feat: add support for Pebble notices`
- `fix: correct type hints for ConfigData`
- `docs: clarify usage of Container.push`

### Before Submitting
1. Run `tox -e format` to format code
2. Run `tox -e lint` to check linting and types
3. Run `tox -e unit` to verify all tests pass
4. Add tests for any new functionality
5. Update docstrings for any API changes
6. Ensure backward compatibility

## Key Files Reference

| File | Purpose |
|------|---------|
| `ops/charm.py` | CharmBase, event types, metadata parsing |
| `ops/framework.py` | Core event system, Handle, Object, Framework |
| `ops/model.py` | Model, Unit, Application, Relation, Container, etc. |
| `ops/pebble.py` | Pebble API for container workload management |
| `ops/testing.py` | Legacy Harness API (deprecated) |
| `ops/__init__.py` | **Public API exports - review carefully** |
| `testing/src/scenario/` | ops.testing (ops-scenario) implementation |
| `STYLE.md` | Team Python style guide |
| `CONTRIBUTING.md` | PR and contribution process |
| `HACKING.md` | Detailed development setup and workflow |

## Security & Compliance

- All code must pass security scanning before release
- Follow Canonical's security policies
- Report security issues via GitHub Security Advisories
- See `SECURITY.md` for vulnerability reporting

## Getting Help

- **Documentation**: https://documentation.ubuntu.com/ops/latest/
- **Matrix chat**: #charmhub-charmdev:ubuntu.com
- **Discourse forum**: https://discourse.charmhub.io/
- **GitHub issues**: https://github.com/canonical/operator/issues

## Quick Reference Card

```bash
# Format & check code
tox -e format && tox -e lint

# Run tests
tox -e unit

# Build docs
make -C docs run

# Use a local ops in a charm
# Option 1: Git branch in requirements.txt
git+https://github.com/{user}/operator@{branch}

# Option 2: Inject after packing (see HACKING.md)
```

**Remember**: Always preserve backward compatibility, write tests, use type hints, and keep docstrings user-focused.
