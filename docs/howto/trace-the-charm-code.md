(trace-the-charm-code)=
# Trace the charm code

## Tracing from scratch

FIXME: write this up

- depend on `ops[tracing]`
- remove charm\_tracing charm lib, if it's installed
- observe the `SetupTracingEvent`

```py
class YourCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.framework.observe(self.on.setup_tracing, self._on_setup_tracing)
        ...

    def _on_setup_tracing(self, event: ops.SetupTracingEvent) -> None:
        # FIXME must get this from some relation
        event.set_destination(url='http://localhost:4318/v1/traces')
```

## Migrating from charm\_tracing

- depend on `ops[tracing]`
- remove charm\_tracing charm lib, if it's installed
- remove `@trace_charm` decorator
- observe the `SetupTracingEvent`
- instrument key functions in the charm

NOTE: charm\_tracing auto-instruments all public function on the class. `ops[tracing]` doesn't do that.

```py
# FIXME example
```
