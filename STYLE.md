# Ops Python style guide

This is the Python style guide we use for the Ops project. It's also the style we're converging on for other projects maintained by the Charm Tech team.

We use Ruff for formatting, and run our code through the Pyright type checker. We try to follow [PEP 8](https://peps.python.org/pep-0008/), the official Python style guide. However, PEP 8 is fairly low-level, so in addition we've come up with the following style guidelines.

New code should follow these guidelines, unless there's a good reason not to. Sometimes existing code doesn't follow these, but we're happy for it to be updated to do so (either all at once, or as you change nearby code).

Of course, this is just a start! We add to this list as things come up in code review; this list reflects our team decisions.


**Table of contents:**

* [Code decisions](#code-decisions)
* [Docs and docstrings](#docs-and-docstrings)


## Code decisions

### Import modules, not objects

"Namespaces are one honking great idea -- let's do more of those!"

When reading code, it's significantly easier to tell where a name came from if it is prefixed with the package name.

An exception is names from `typing` -- type annotations get too verbose if these all have to be prefixed with `typing.`.

**Don't:**

```python
from ops import CharmBase, PebbleReadyEvent
from subprocess import run

class MyCharm(CharmBase):
    def _pebble_ready(self, event: PebbleReadyEvent):
        run(['echo', 'foo'])
```

**Do:**

```python
import ops
import subprocess

class MyCharm(ops.CharmBase):
    def _pebble_ready(self, event: ops.PebbleReadyEvent):
        subprocess.run(['echo', 'foo'])

# However, "from typing import Foo" is okay to avoid verbosity
from typing import Optional, Tuple
counts: Optional[Tuple[str, int]]
```


### Use relative imports inside a package

When writing code inside a package (a directory containing an `__init__.py` file), use relative imports with a `.` instead of absolute imports.
For example, within the `ops` package:

**Don't:**

```python
from ops import charm
```

**Do:**

```python
from . import charm

# Or, if you need to avoid adding the public name "charm" to the namespace:

from . import charm as _charm
```


### Avoid nested comprehensions and generator expressions

"Flat is better than nested."

**Don't:**

```python
units = [units for app in model.apps for unit in app.units]

for current in (
    status for status in pebble.ServiceStatus if status is not pebble.ServiceStatus.ACTIVE
):
    ...
```

**Do:**

```python
units = []
for app in model.apps:
    for unit in app.units:
        units.append(unit)

for status in pebble.ServiceStatus:
    if status is pebble.ServiceStatus.ACTIVE:
        continue
    ...
```


### Compare enum values by identity

The [Enum HOWTO](https://docs.python.org/3/howto/enum.html#comparisons) says that "enum values are compared by identity", so we've decided to follow that. Note that this decision applies to regular `enum.Enum` values, not to `enum.IntEnum` or `enum.StrEnum` (the latter is only available from Python 3.11).

**Don't:**

```python
if status == pebble.ServiceStatus.ACTIVE:
    print('Running')

if status != pebble.ServiceStatus.ACTIVE:
    print('Stopped')
```

**Do:**

```python
if status is pebble.ServiceStatus.ACTIVE:
    print('Running')

if status is not pebble.ServiceStatus.ACTIVE:
    print('Stopped')
```


## Docs and docstrings

### Use British English

[Canonical's documentation style](https://docs.ubuntu.com/styleguide/en/) uses British spelling, which we try to follow here. For example: "colour" rather than "color", "labelled" rather than "labeled", "serialise" rather than "serialize", and so on.

It's a bit less clear when we're dealing with code and APIs, as those normally use US English, for example, `pytest.mark.parametrize`, and `color: #fff`.


### Spell out abbreviations

Abbreviations and acronyms in docstrings should usually be spelled out, for example, "for example" rather than "e.g.", "that is" rather than "i.e.", "and so on" rather than "etc", and "unit testing" rather than UT.

However, it's okay to use acronyms that are very well known in our domain, like HTTP or JSON or RPC.
