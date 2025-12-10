# Copilot Instructions for Ops Library Code Review

These instructions are specifically for GitHub Copilot when reviewing code in the `ops` library repository. For more general instructions ignore this file and refer to [AGENTS.md](AGENTS.md).

Remember: The ops library is foundational infrastructure. Prioritise stability, clarity, and maintainability over cleverness.

## Code Review Focus Areas

### Python Style and Standards

For the most part, style and coding standards are enforced by ruff and do *not* need to be considered in code review. There are some additional recommendations in [STYLE.md](STYLE.md) that should be followed.

### Import modules, not objects

```python
import subprocess

import ops

class MyCharm(ops.CharmBase):
    def _pebble_ready(self, event: ops.PebbleReadyEvent) -> None:
        subprocess.run(['echo', 'foo'])

# However, "from typing import Foo" is okay to avoid verbosity
from typing import Optional, Tuple
counts: Optional[Tuple[str, int]]
```

Imports always appear at the top of the file, grouped in the following order with a blank line between each group, and using relative imports within the package:

```python
import sys

import yaml

from . import charm
```

### Docs and docstrings

#### Avoid the negative, state conditions in the positive

- Avoid: "If the command doesn't exit within 1 second, the start is considered successful." (Negative)
- Prefer: "If the command stays running for the 1-second window, the start is considered successful." (Positive)

#### Avoid passive, be active

- Avoid: "A minimal check is created using the default values"
- Prefer: "Create a minimal check, using the default values"

#### Avoid subjective, be objective

- Avoid: "This can be done easily using ..."
- Prefer: "You can do this using ..."

- Avoid: "This can be easily configured by ..."
- Prefer: "We can configure this using ..."

- Avoid: "Simply run the command ..."
- Prefer: "Run the command ..."

#### Use British English

For example: "colour" rather than "color", "labelled" rather than "labeled", "serialise" rather than "serialize".

#### Spell out abbreviations

- "for example" rather than "e.g."
- "that is" rather than "i.e."
- "and so on" rather than "etc"
- "unit testing" rather than UT, and so on

However, it's okay to use acronyms that are very well known in our domain, like HTTP or JSON or RPC.

#### Use sentence case in headings

- Prefer: `## Use sentence case for headings`
- Avoid: `## Use Title Case for Headings`.

#### YAML

- Use quotes for strings: This is especially important if a string contains special characters or starts with a number.
- Indentation: Always use spaces and be consistent with the number of spaces throughout the same file (two, unless the file already uses a different number).
- Use comments: Comments will help you and others understand what that data is used for.

## Common Review Patterns

What to Look For:

- **Missing or inadequate tests** for new functionality
- **Breaking changes** (almost never appropriate and should always be called out)
- **Performance regressions** in critical paths
- **Resource leaks** or missing cleanup
- **Security vulnerabilities** in input handling
- **Inconsistent error handling** patterns
