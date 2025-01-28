### Usage

Recommended for traces of moderate and high complexity:

```command
dima@colima-ahh /c/operator (feat-otel)> docker run --rm --name jaeger \
                                               -p 16686:16686 \
                                               -p 4317:4317 \
                                               -p 4318:4318 \
                                               -p 5778:5778 \
                                               -p 9411:9411 \
                                               jaegertracing/jaeger:2.2.0
```

After which, you should be able to:
- open http://192.168.107.4:16686/ in your browser
- select the correct **Service** (`testapp-charm` at current branch state)
- click Search at the bottom of the form

Note: the `jaeger` container keeps traces in memory, and your Service can't be selected
until it has sent some data to `jaeger`.

Alternatively, text-based:

```command
dima@colima-ahh /c/operator (feat-otel)> docker run -it --rm \
                                               -v (pwd)/dont-merge/otel-collector-config.yaml:/etc/otel-collector-config.yaml \
                                               -p 4317:4317 \
                                               -p 4318:4318 \
                                               otel/opentelemetry-collector:latest \
                                               --config=/etc/otel-collector-config.yaml
```

and then

```command
dima@colima-ahh /c/operator (feat-otel)> uv venv --seed .ahh-venv
Using CPython 3.13.0
Creating virtual environment with seed packages at: .ahh-venv

dima@colima-ahh /c/operator (feat-otel)> . .ahh-venv/bin/activate.fish
(.ahh-venv) dima@colima-ahh /c/operator (feat-otel)>

(.ahh-venv) dima@colima-ahh /c/operator (feat-otel)> uv pip install -e .[tracing] -U
Using Python 3.13.0 environment at .ahh-venv
Resolved 21 packages in 907ms
Prepared 18 packages in 72ms
...

(.ahh-venv) dima@colima-ahh /c/operator (feat-otel)> python dont-merge/send-traces.py
Span created and exported to the collector!
```

### Hacking

Or, trying to run code outside of a charm.

Somehow I'm not getting anything, because the `juju-log` hook tool is missing.

Let's fix that.

```command
> ln -s (which echo) juju-log
```

Generate some tracing data:

```command
(venv) > JUJU_UNIT_NAME=testapp/42 JUJU_CHARM_DIR=dont-merge/ PATH=$PATH:. JUJU_VERSION=3.5.4 ./dont-merge/start
```

OTEL collector debug output would look like this:

```
2025-01-15T08:46:23.229Z	info	Traces	{"kind": "exporter", "data_type": "traces", "name": "debug", "resource spans": 1, "spans": 1}
2025-01-15T08:46:23.229Z	info	ResourceSpans #0
Resource SchemaURL:
Resource attributes:
     -> telemetry.sdk.language: Str(python)
     -> telemetry.sdk.name: Str(opentelemetry)
     -> telemetry.sdk.version: Str(1.29.0)
     -> service.name: Str(testapp-charm)
     -> compose_service: Str(testapp-charm)
     -> charm_type: Str(CharmBase)
     -> juju_unit: Str(testapp/42)
     -> juju_application: Str(testapp)
     -> juju_model: Str()
     -> juju_model_uuid: Str()
ScopeSpans #0
ScopeSpans SchemaURL:
InstrumentationScope ops
Span #0
    Trace ID       : 8c3f292c89f29c59f1b37fe59ba0abbc
    Parent ID      :
    ID             : e0253a03ef694a4f
    Name           : ops.main
    Kind           : Internal
    Start time     : 2025-01-15 08:46:23.175916835 +0000 UTC
    End time       : 2025-01-15 08:46:23.182329655 +0000 UTC
    Status code    : Error
    Status message : RuntimeError: command not found: is-leader
Events:
SpanEvent #0
     -> Name: exception
     -> Timestamp: 2025-01-15 08:46:23.182316071 +0000 UTC
     -> DroppedAttributesCount: 0
     -> Attributes::
          -> exception.type: Str(RuntimeError)
          -> exception.message: Str(command not found: is-leader)
          -> exception.stacktrace: Str(Traceback (most recent call last):
             ...
          -> exception.escaped: Str(False)
	{"kind": "exporter", "data_type": "traces", "name": "debug"}
```
