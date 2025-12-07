# Copyright 2025 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# To learn more about testing, see https://documentation.ubuntu.com/ops/latest/explanation/testing/

import pytest
from ops import testing

from charm import PORT, TinyproxyCharm


class MockTinyproxy:
    """Mock object that represents tinyproxy."""

    def __init__(
        self,
        config: None | tuple[int, str] = None,
        installed: bool = False,
        reloaded_config: bool = False,
        running: bool = False,
    ):
        self.config = config
        self.installed = installed
        self.reloaded_config = reloaded_config
        self.running = running

    def ensure_config(self, port: int, slug: str) -> bool:
        old_config = self.config
        self.config = (port, slug)
        return self.config != old_config

    def get_version(self) -> str:
        return "1.0.0"

    def install(self) -> None:
        self.installed = True

    def is_installed(self) -> bool:
        return self.installed

    def is_running(self) -> bool:
        return self.running

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def reload_config(self) -> None:
        self.reloaded_config = True

    def uninstall(self) -> None:
        self.installed = False


def test_install(monkeypatch: pytest.MonkeyPatch):
    """Test that the charm correctly handles the install event."""
    # A state-transition test has three broad steps:
    # Step 1. Arrange the input state.
    tinyproxy = MockTinyproxy()
    monkeypatch.setattr("charm.tinyproxy", tinyproxy)
    ctx = testing.Context(TinyproxyCharm)
    state_in = testing.State()
    # Step 2. Simulate an event, in this case an install event.
    state_out = ctx.run(ctx.on.install(), state_in)
    # Step 3. Check the output state.
    assert state_out.workload_version is not None
    assert state_out.unit_status == testing.MaintenanceStatus("Waiting for tinyproxy to start")
    assert tinyproxy.is_installed()


# For convenience, define a reusable fixture that provides a MockTinyproxy object
# and patches the helper module in the charm.
@pytest.fixture
def tinyproxy_installed(monkeypatch: pytest.MonkeyPatch):
    tinyproxy = MockTinyproxy(installed=True)
    monkeypatch.setattr("charm.tinyproxy", tinyproxy)
    return tinyproxy


def test_start(tinyproxy_installed: MockTinyproxy):
    """Test that the charm correctly handles the start event."""
    ctx = testing.Context(TinyproxyCharm)
    state_out = ctx.run(ctx.on.start(), testing.State())
    assert state_out.unit_status == testing.ActiveStatus()
    assert tinyproxy_installed.is_running()
    assert tinyproxy_installed.config == (PORT, "example")


# Define another fixture, this time representing an installed, configured, and running tinyproxy.
@pytest.fixture
def tinyproxy_configured(monkeypatch: pytest.MonkeyPatch):
    tinyproxy = MockTinyproxy(config=(PORT, "example"), installed=True, running=True)
    monkeypatch.setattr("charm.tinyproxy", tinyproxy)
    return tinyproxy


def test_config_changed(tinyproxy_configured: MockTinyproxy):
    """Test that the charm correctly handles the config-changed event."""
    ctx = testing.Context(TinyproxyCharm)
    state_in = testing.State(config={"slug": "foo"})
    state_out = ctx.run(ctx.on.config_changed(), state_in)
    assert state_out.unit_status == testing.ActiveStatus()
    assert tinyproxy_configured.is_running()
    assert tinyproxy_configured.config == (PORT, "foo")
    assert tinyproxy_configured.reloaded_config


@pytest.mark.parametrize("invalid_slug", ["", "foo_bar", "foo/bar"])
def test_start_invalid_config(tinyproxy_installed: MockTinyproxy, invalid_slug: str):
    """Test that the charm fails to start if the config is invalid."""
    ctx = testing.Context(TinyproxyCharm)
    state_in = testing.State(config={"slug": invalid_slug})
    state_out = ctx.run(ctx.on.start(), state_in)
    assert state_out.unit_status == testing.BlockedStatus(
        f"Invalid slug: '{invalid_slug}'. Slug must match the regex [a-z0-9-]+"
    )
    assert not tinyproxy_installed.is_running()
    assert tinyproxy_installed.config is None


@pytest.mark.parametrize("invalid_slug", ["", "foo_bar", "foo/bar"])
def test_config_changed_invalid_config(tinyproxy_configured: MockTinyproxy, invalid_slug: str):
    """Test that the charm fails to change config if the config is invalid."""
    ctx = testing.Context(TinyproxyCharm)
    state_in = testing.State(config={"slug": invalid_slug})
    state_out = ctx.run(ctx.on.config_changed(), state_in)
    assert state_out.unit_status == testing.BlockedStatus(
        f"Invalid slug: '{invalid_slug}'. Slug must match the regex [a-z0-9-]+"
    )
    assert tinyproxy_configured.is_running()  # tinyproxy should still be running...
    assert tinyproxy_configured.config == (PORT, "example")  # ...with the original config.
    assert not tinyproxy_configured.reloaded_config


def test_stop(tinyproxy_configured: MockTinyproxy):
    """Test that the charm correctly handles the stop event."""
    ctx = testing.Context(TinyproxyCharm)
    state_out = ctx.run(ctx.on.stop(), testing.State())
    assert state_out.unit_status == testing.MaintenanceStatus("Waiting for tinyproxy to start")
    assert not tinyproxy_configured.is_running()


def test_remove(tinyproxy_installed: MockTinyproxy):
    """Test that the charm correctly handles the remove event."""
    ctx = testing.Context(TinyproxyCharm)
    state_out = ctx.run(ctx.on.remove(), testing.State())
    assert state_out.unit_status == testing.MaintenanceStatus(
        "Waiting for tinyproxy to be installed"
    )
    assert not tinyproxy_installed.is_installed()
