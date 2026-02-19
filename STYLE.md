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

### Provide return type annotations

Function and method signatures should include a type annotation for the returned value, other than for `__init__` or in test code.

**Do:**

```python
def method1(arg1: type1, arg2: type2) -> None:
    ...

def method2() -> str:
    ...
    return 'Hello world!'

class C:
    def __init__(self, x: type1):
        ...

def test_method1():
    assert ...
```

## Docs and docstrings

### Avoid the negative, state conditions in the positive

State conditions positively: what should happen, rather than what shouldn't. Focus on desired behaviour, and frame instructions and conditions around the expected or successful outcome, not failure cases.

Example:

- Avoid: "If the command doesn't exit within 1 second, the start is considered successful." (Negative)
- Prefer: "If the command stays running for the 1-second window, the start is considered successful." (Positive)

Only use negative phrasing when:

- The failure case is the primary concern (for example, error handling).
- The positive phrasing is awkward or less clear.

### Avoid passive, be active

Use the active voice as much as possible, especially in direct instructions to the reader.

We should only use the passive voice when we don't know or care about who performed the action.

Example:

- Avoid: "A minimal check is created using the default values"
- Prefer: "Create a minimal check, using the default values"

Writing "We create ..." rather than "Create ..." in explanatory documentation is also fine.

### Avoid subjective, be objective

Avoid using words like "easy", "simple", or "just", which are subjective and assume the reader's skill level. Instead, describe the action directly by stating what to do and focusing on concrete steps.

Examples:

- Avoid: "This can be done easily using ..."
- Prefer: "You can do this using ..."

- Avoid: "This can be easily configured by ..."
- Prefer: "We can configure this using ..."

- Avoid: "Simply run the command ..."
- Prefer: "Run the command ..."

### Be concise and avoid repetition

For example, avoid long introductions. In tutorials, how-to guides, and reference documentation, get the reader to the core of the content as quickly as possible.

Trim repetitive titles: Avoid repeating the name if the surrounding content already provides context.

For example, in a document called "How to use Pebble", the section names can simply be "API", "CLI commands", and "Features", instead of "Pebble API", "Pebble CLI commands", and "Pebble features".

### Order: alphanumeric or logical

We can either use an alphanumeric order, or a logical order, depending on the context.

Alphanumeric order is better in the case of a reference doc or a list (for example, an Enum).

Example (Enum):

- Avoid: start, stop, restart, replan, autostart
- Prefer: autostart, replan, restart, start, stop

Example (A list of commands):

Avoid (arbitrary order):

- `pebble ls`
- `pebble mkdir`
- `pebble rm`
- `pebble push`
- `pebble pull`

Prefer (alphabetical order):

- `pebble ls`
- `pebble mkdir`
- `pebble pull`
- `pebble push`
- `pebble rm`

Exceptions:

- If there's a strong logical progression (for example, "low", "medium", "high"; or a list of things that you should read in that particular order).
- If there is already an exception in the current documentation, follow existing conventions.

### Use British English

[Canonical's documentation style](https://docs.ubuntu.com/styleguide/en/) uses British spelling, which we try to follow here. For example: "colour" rather than "color", "labelled" rather than "labeled", "serialise" rather than "serialize", and so on.

It's a bit less clear when we're dealing with code and APIs, as those normally use US English, for example, `pytest.mark.parametrize`, and `color: #fff`.

### Spell out abbreviations

Abbreviations and acronyms in docstrings should usually be spelled out:

- "for example" rather than "e.g."
- "that is" rather than "i.e."
- "and so on" rather than "etc"
- "unit testing" rather than UT, and so on

However, it's okay to use acronyms that are very well known in our domain, like HTTP or JSON or RPC.

### Use sentence case in headings

`## Use sentence case for headings`, instead of `## Use Title Case for Headings`.

### Be consistent

Choice of words: For example, if the whole document uses "mandatory", you probably shouldn't use "required" in a newly added paragraph. For another example, if the whole document uses "list foo" when adding new content, don't use "get a list of bar".

### Use "true"/"false" consistently in docstrings

When describing boolean parameters in docstrings:

- Use lowercase "true"/"false" (no backticks) for truth-y/falsy concepts: "if true, create parent directories".
- Use double-backtick-quoted `` ``True`` ``/`` ``False`` `` when referring to the Python objects themselves: "pass ``True`` to enable".
- Do not use bare "True"/"False" (capitalised without backticks).

### Be precise

Be precise in names and verbs. Use precise verbs to describe the behaviour. For example, the appropriate description of `/v1/services` is "list services", while "get a service" is probably a better fit for `/v1/services/{name}`.

Split distinct ideas: Use separate sentences or clauses, and avoid cramming. Don't merge unrelated details into a single phrase (for example, parameter format and default behaviour).

Example:

- Avoid: "The names of the services to get, a comma-separated string. If empty, get all services."
- Prefer: "The names of the services to get. Specify multiple times for multiple values. If omitted, the method returns all services." (In three short precise sentences we've covered what the parameter does, usage details, and behavioral details.)

Example:

- Avoid: "For reference information about the API, see [API and clients] and [API]." (It's hard to tell the difference between these two.)
- Prefer: "For an explanation of API access levels, see [API and clients]. For the full API reference, see [API reference]." (Clear.)

### Don't over-promote

Avoid overstatement: Only use adjectives like "comprehensive", "powerful", or "robust" when the feature truly meets the description.

Example:

- Avoid: "Pebble provides a comprehensive health check feature"
- Prefer: "Pebble provides a health check feature"

Let features speak for themselves, describe actual capabilities and use measurable terms when possible (for example, "supports 3 types of checks" instead of "versatile checking")

Future-proofing: Qualify with "currently" when describing evolving features. For example: "Currently, the only supported log target type is Grafana Loki".

### Avoid implementation-specific terminology

Focus on behaviour, not internal implementation: Describe what it does rather than how a particular implementation works.

Example:

- Avoid: "The `Change` ID will be empty when the check is stopped." (Implementation-specific.)
- Prefer: "The `Status` will be 'inactive' when the check is stopped." (General.)

### Articles

Choose between the "a" or "the" articles carefully.

When describing a generic parameter:

- Avoid: "The format of the duration string is a sequence of decimal numbers."
- Prefer: "The format of a duration string is a sequence of decimal numbers."

When describing a generic behaviour:

- Avoid: "Restart the service when the health check fails."
- Prefer: "Restart a service when the health check fails." (No specific service is implied.)


### Code blocks

- Consistency: the styles of code blocks and terminal output samples should be the same, at least within the same document.
- Preferred style: Use triple-backtick followed by language when showing code. Use `{terminal}` (`.rst` style) when showing commands or terminal output. Avoid using triple-backtick followed by language or `{code-block}` for commands or terminal output, unless it's consistent with the existing content in the same document.
- Highlighting: Use `:emphasize-lines: 8-10` with `{code-block}` for highlighting lines in relatively long code blocks when necessary. Don't add an inconsistent `{code-block}` just so that you can highlight lines in commands or terminal output. Instead, use `{terminal}` along with helpful words and comments.

For more information, see [MyST Code and Code-blocks](https://mystmd.org/guide/code).

### YAML

- Use quotes for strings: This is especially important if a string contains special characters or starts with a number.
- Indentation: Always use spaces and be consistent with the number of spaces throughout the same file (two, unless the file already uses a different number).
- Use comments: Comments will help you and others understand what that data is used for.
