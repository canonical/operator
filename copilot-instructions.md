# GitHub Copilot Instructions for Ops

## Code Completion Guidelines

### Type Hints
Always include complete type hints:
```python
from typing import Optional, Dict, List, Any

def handle_relation(self, event: RelationEvent) -> None:
    data: Dict[str, str] = event.relation.data[self.unit]
```

### Testing Pattern
Generate tests using `ops.testing.Context`:
```python
def test_my_feature(self):
    ctx = testing.Context(MyCharm)
    state = testing.State()
    out = ctx.run(ctx.on.config_changed(), state)
    assert out.unit_status == testing.ActiveStatus("ready")
```

### Docstrings
Use Google-style docstrings:
```python
def my_function(param: str, option: Optional[int] = None) -> bool:
    """Brief description.

    Longer description if needed.

    Args:
        param: Parameter description.
        option: Optional parameter description.

    Returns:
        Return value description.

    Raises:
        ValueError: When validation fails.
    """
```

### Imports
Order imports as:
1. Standard library
2. Third-party (PyYAML, websocket, etc.)
3. ops library
4. Relative imports

## Avoid
- Type: ignore comments (fix types instead)
- Global state outside Framework
