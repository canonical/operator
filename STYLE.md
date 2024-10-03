
# Ops Python style guide

This is the Python style guide we use for the Ops project. However, it's also the style we're converging on for other projects maintained by the Charm Tech team.

We use Ruff for formatting, and run our code through the Pyright type checker. We also try to follow [PEP 8](https://peps.python.org/pep-0008/), the official Python style guide. However, PEP 8 is fairly low-level, so in addition we've come up with the following style guidelines.

Of course, this is just a start! We add to this list as things come up in code review and we make a team decision.


**Table of contents:**

* [Simplicity](#simplicity)
* [Specific decisions](#specific-decisions)
* [Docs and docstrings](#docs-and-docstrings)


## Simplicity

### Avoid nested comprehensions

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

active_statuses = [status for status in pebble.ServiceStatus if status != pebble.ServiceStatus.ACTIVE]
for current in active_statuses:
	...
```

## Specific decisions

### Compare enum values by equality

This is six of one, half a dozen of the other, but we've decided that saying `if color == Color.RED` is nicer than `if color is Color.RED` as `==` is more typical for integer- and string-like values, and if you do use an `IntEnum` or `StrEnum` you should use `==` anyway.

Note that the [Enum HOWTO](https://docs.python.org/3/howto/enum.html#comparisons) first says they should be compared by identity, but then shows that equality is defined too, and so kind of adds to the confusion. See also this [StackOverflow question](https://stackoverflow.com/questions/25858497/should-enum-instances-be-compared-by-identity-or-equality) and [some discussion/disagreement](https://github.com/pylint-dev/pylint/issues/5356).

**Don't:**

```python
if status is pebble.ServiceStatus.ACTIVE:
	print('Running')

if status is not pebble.ServiceStatus.ACTIVE:
	print('Stopped')
```

**Do:**

```python
if status == pebble.ServiceStatus.ACTIVE:
	print('Running')

if status != pebble.ServiceStatus.ACTIVE:
	print('Stopped')
```


## Docs and docstrings

### Spell out abbreviations

Prefer spelling out abbreviations and acronyms in docstrings, for example, "for example" rather than "e.g.", "that is" rather than "i.e.", and "unit testing" rather than UT.
