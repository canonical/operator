(trace-the-charm-code)=
# Trace the charm code

## Tracing from scratch

FIXME: copy from tracing/api.py

## Migrating from charm\_tracing

- depend on `ops[tracing]`
- remove direct dependencies on `opentelemetry-api, -sdk, etc.`
- remove charm\_tracing charm lib, if it's installed
- remove `@trace_charm` decorator
- include `ops._tracing.Tracing()` in your charm's `__init__`
- instrument key functions in the charm

NOTE: charm\_tracing auto-instruments all public function on the class. `ops[tracing]` doesn't do that.

```py
# FIXME example
```
