(trace-the-charm-code)=
# Trace the charm code

Intro: ``ops[tracing]`` provides the first party charm tracing lib [details].

TODO: refer to ``tracing/ops_tracing/__init__.py`` for the canonical example.

Overview on this page: add tracing to your charm, create custom spans and events for the
semantically meaningful elements in your charm code.

## Tracing from scratch

- add `ops[tracing]` to your charm's dependencies
- declare the tracing and optionally ca relations in ``charmcraft.yaml``
- instantiate ``ops.tracing.Tracing(...)`` object in your charm class ``__init__``

Overview of what's available at this point.

## Custom spans and events

- add `openetelemetry-api >= 1.30.0` to you charm's dependencies
- create a ``tracer`` object
- start custom spans
- create custom events

## Migrating from charm\_tracing charm lib

- remove direct dependencies on ``opentelemetry-sdk``, etc.
- remove the ``charm\_tracing`` charm lib
- remove ``@trace_charm`` decorator and its helpers [fill this in]
- depend on ``ops[tracing]``
- include ``ops.tracing.Tracing()`` in your charm's ``__init__``
- instrument key functions in the charm

Note that the ``charm\_tracing`` charm lib auto-instruments all public function on the class
it's applied to. The ``ops[tracing]`` approach doesn't do that.

## Tracing for machine charms

[figure this out]

## Lower levels of abstraction

Preface: if the first-party charm tracing lib is somehow not suitable.

When ``ops[tracing]`` is added to your charm's dependencies.

Outline: get the destination URL, call ``ops.tracing.set_destination(...)``.

Notes: the ``url`` is a full URL, not a base URL; CA is a multi-line string.

Details: that the URL is saved in the local database, only needs to be updated on change.
