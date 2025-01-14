### Usage

Run Jaeger all-in-one to collect traces on your machine:

```command
> docker run --rm --name jaeger \
        -p 16686:16686 \
        -p 4317:4317 \
        -p 4318:4318 \
        -p 5778:5778 \
        -p 9411:9411 \
        jaegertracing/jaeger:2.2.0
```

After which, you should be able to:
- generate some traces (see below)
- open `http://<ip address>:16686/` in your browser, perhaps http://localhost:16686/
- select the correct **Service** (application name)
- click Search at the bottom of the form

Notes:
- the Jaeger container keeps traces in memory, data is lost when container is restarted.
- a Service can only be selected in the UI if some data for that service has been sent.

### Instrument a charm 

A k8s charm can access the host by its IP address, thus:

```py
    def __init__(self, framework: ops.Framework):
        ...
        self.framework.observe(self.on.setup_tracing, self._on_setup_tracing)

    def _on_setup_tracing(self, event: ops.SetupTracingEvent) -> None:
        event.set_destination(url='http://<ip address>:4318/v1/traces')  # you machine ip address
```
