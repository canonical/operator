# Agent Instructions for Ops

## Project Overview
Ops is the official Python framework for developing Kubernetes and machine charms within the Juju ecosystem. It provides an event-driven abstraction layer for charm developers.

This workspace is a monorepo containing:
- **`ops/`** - Core framework providing the event system, charm base classes, and model abstractions. Note that the tests are in a top-level folder `test`
- **`testing/`** - The `ops-scenario` state transition testing framework (accessed as `ops.testing`). This uses src-layout.
- **`tracing/`** - The `ops-tracing` observability integration. The tests are in a subfolder called `test`.
- **`docs/`** - Common documentation, predominantly Markdown.

This is a mature, production framework used by thousands of charms. Changes require careful consideration of backward compatibility and testing.

## Key Files Reference

| File | Purpose |
|------|---------|
| `ops/charm.py` | CharmBase, event types, metadata parsing |
| `ops/framework.py` | Core event system, Handle, Object, Framework |
| `ops/model.py` | Juju model abstractions |
| `ops/pebble.py` | Pebble API for container workload management |
| `ops/__init__.py` | Public API exports |
| `STYLE.md` | Team Python style guide |
| `CONTRIBUTING.md` | PR and contribution process |
| `HACKING.md` | Detailed development setup and workflow |

## Important Notes

### Backward Compatibility
- **Always** preserve backward compatibility in public APIs
- **Document** all breaking changes in commit messages
- **Always** preserve existing behavior unless fixing a bug

### Test Organisation
- Tests for `ops/main.py` go in `test/test_main.py`
- Large test suites may get their own file: `test/test_main_foo.py`
- Scenario tests have a different structure - follow existing patterns

## When Making Changes

### Code Modifications
1. **Read existing code** before proposing changes - use Read tool to understand patterns
2. **Check tests** - examine `test/` for similar test patterns
3. **Verify changes** - execute `tox` after changes to ensure linting and unit tests pass

## Development Standards

### Language & Type Checking
- Follow conventions in STYLE.md
- Use Ruff for formatting (`tox -e format`)
- Python 3.10+ with **full type hints** required (check with `tox -e lint`)
- Use modern `x: int | None` annotations, not old-style `x: Optional[int]`
- Always provide a return type, other than for `__init__` and in test code

### Import Style
```python
# DO: Import modules, not objects (except typing)
import ops
import subprocess
from typing import Generator  # typing is an exception

class MyCharm(ops.CharmBase):
    def handler(self, event: ops.PebbleReadyEvent):
        subprocess.run(['echo', 'hello'])

# DON'T: Import objects directly
from ops import CharmBase, PebbleReadyEvent  # Avoid this
```

## Documentation Guidelines

Follow the Diátaxis framework for documentation structure:
- **Tutorials** (`docs/tutorial/`) - Learning-oriented
- **How-to guides** (`docs/howto/`) - Task-oriented
- **Reference** - Generated from docstrings
- **Explanation** (`docs/explanation/`) - Understanding-oriented

Comments are always full sentences that end with punctuation. Avoid using comments to explain *what* the code is *doing*, use them (sparingly, as required) to explain *why* the code is doing what it is doing.

### Docstring Style

Use Google-style docstrings for all public APIs, with proper formatting. The text is used to generate reference documentation with Sphinx so must be appropriate ReST.

```python
def my_function(param: str, count: int = 1) -> list[str]:
    """Brief one-line summary.

    Longer description providing more context. Focus on what the function
    does for users, not implementation details.

    Args:
        param: Description of the parameter.
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
- Use short sentences and simple phrasing
- Be consistent with choice of words
- Avoid words or phrases specific to US or UK English where possible, and use British English otherwise
- State conditions **positively**: What should happen, not what shouldn't
- Spell out abbreviations and avoid Latin: "for example" not "e.g."
- Use **sentence case** for headings

### Version Dependencies

Only document Juju version dependencies in docstrings:

```python
def new_feature():
    """Do something new.

    .. jujuadded:: 3.5
        Further functionality was added in Juju 3.6.
    """
```

Don't document Ops version changes in docstrings - that's in the changelog.

## Pull Request Guidelines

See CONTRIBUTING.md for more details.

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

The project does not use conventional commit "scopes".

### Before Submitting
1. Add tests for any new functionality
2. Update docstrings for any API changes
3. Ensure backward compatibility
4. Run `tox -e format` to format code
5. Run `tox -e lint` to check linting and types
6. Run `tox -e unit` to verify unit tests pass - avoid drops in coverage (`tox -e coverage`)
7. Run `make html` in the `docs` folder to ensure that the documentation can be generated
8. Search the explanation, how-to, and tutorial documentation in the `docs` folder for topics related to the changes, then suggest places that might need expanding/altering
9. If a virtual environment or sandbox is available, run `tox -e pebble` and `tox -e integration`
