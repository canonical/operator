### Usage

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

And run ops like this:

```command
> JUJU_CHARM_DIR=dont-merge/ PATH=$PATH:. JUJU_VERSION=3.5.4 python -c 'import ops; ops.main(ops.CharmBase)'
```

Now, the backtrace ends up being sent to the OTEL collector.
