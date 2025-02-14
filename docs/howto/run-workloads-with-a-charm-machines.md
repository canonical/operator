(run-workloads-with-a-charm-machines)=
# How to run workloads with a charm - machines

There are several ways your charm might start a workload, depending on the type of charm you’re authoring. 

For a machine charm, it is likely that packages will need to be fetched, installed and started to provide the desired charm functionality. This can be achieved by interacting with the system’s package manager, ensuring that package and service status is maintained by reacting to events accordingly.

It is important to consider which events to respond to in the context of your charm. A simple example might be:

```python
# ...
from subprocess import check_call, CalledProcessError
# ...
class MachineCharm(ops.CharmBase):
    #...

    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)
        # ...

    def _on_install(self, event: ops.InstallEvent) -> None:
      """Handle the install event"""
      try:
        # Install the openssh-server package using apt-get
        check_call(["apt-get", "install", "-y", "openssh-server"])
      except ops.CalledProcessError as e:
        # If the command returns a non-zero return code, put the charm in blocked state
        logger.debug("Package install failed with return code %d", e.returncode)
        self.unit.status = ops.BlockedStatus("Failed to install packages")

    def _on_start(self, event: ops.StartEvent) -> None:
      """Handle the start event"""
      try:
        # Enable the ssh systemd unit, and start it
        check_call(["systemctl", "enable", "--now", "openssh-server"])
      except ops.CalledProcessError as e:
        # If the command returns a non-zero return code, put the charm in blocked state
        logger.debug("Starting systemd unit failed with return code %d", e.returncode)
        self.unit.status = ops.BlockedStatus("Failed to start/enable ssh service")
        return

      # Everything is awesome
      self.unit.status = ops.ActiveStatus()
```

If the machine is likely to be long-running and endure multiple upgrades throughout its life, it may be prudent to ensure the package is installed more regularly, and handle the case where it needs upgrading or reinstalling. Consider this excerpt from the [ubuntu-advantage charm code](https://git.launchpad.net/charm-ubuntu-advantage/tree/src/charm.py) (with some additional comments):

```python
class UbuntuAdvantageCharm(ops.CharmBase):
    """Charm to handle ubuntu-advantage installation and configuration"""
    _state = ops.StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        self._state.set_default(hashed_token=None, package_needs_installing=True, ppa=None)
        self.framework.observe(self.on.config_changed, self.config_changed)

    def config_changed(self, event):
        """Install and configure ubuntu-advantage tools and attachment"""
        logger.info("Beginning config_changed")
        self.unit.status = ops.MaintenanceStatus("Configuring")
        # Helper method to ensure a custom PPA from charm config is present on the system
        self._handle_ppa_state()
        # Helper method to ensure latest package is installed
        self._handle_package_state()
        # Handle some ubuntu-advantage specific configuration
        self._handle_token_state()
        # Set the unit status using a helper _handle_status_state
        if isinstance(self.unit.status, ops.BlockedStatus):
            return
        self._handle_status_state()
        logger.info("Finished config_changed")

```

In the example above, the package install status is ensured each time the charm's `config-changed` event fires, which should ensure correct state throughout the charm's deployed lifecycle.
