"""pytest configuration for testing the README"""

import ops

import scenario


def pytest_markdown_docs_globals():
    class MyCharm(ops.CharmBase):
        META = {"name": "mycharm", "storage": {"foo": {"type": "filesystem"}}}

    class SimpleCharm(ops.CharmBase):
        META = {"name": "simplecharm"}

        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on.start, self._on_start)

        def _on_start(self, _: ops.StartEvent):
            pass

    class HistoryCharm(ops.CharmBase):
        META = {"name": "historycharm"}

        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on.start, self._on_start)

        def _on_start(self, _: ops.StartEvent):
            self.unit.set_workload_version("1")
            self.unit.set_workload_version("1.2")
            self.unit.set_workload_version("1.5")
            self.unit.set_workload_version("2.0")

    class PortCharm(ops.CharmBase):
        META = {"name": "portcharm"}

        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on.start, self._on_start)
            framework.observe(self.on.stop, self._on_stop)

        def _on_start(self, _: ops.StartEvent):
            self.unit.open_port(protocol="tcp", port=42)

        def _on_stop(self, _: ops.StopEvent):
            self.unit.close_port(protocol="tcp", port=42)

    return {
        "ops": ops,
        "scenario": scenario,
        "MyCharm": MyCharm,
        "HistoryCharm": HistoryCharm,
        "PortCharm": PortCharm,
        "SimpleCharm": SimpleCharm,
    }
