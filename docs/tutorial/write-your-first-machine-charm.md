(write-your-first-machine-charm)=
# Write your first machine charm

In this tutorial you will write a machine charm for Juju using {external+charmcraft:doc}`Charmcraft <index>` and Ops.

<!-- TODO (tam)
Add this link above:

{external+juju:ref}`machine charm <machine-charm>` for Juju 

When it's available in Juju.
-->

**What you'll need:**
- A workstation, e.g., a laptop, with amd64 architecture and which has sufficient resources to launch a virtual machine with 4 CPUs, 8 GB RAM, and 50 GB disk space
- Familiarity with Linux
- Familiarity with Juju.
- Familiarity with object-oriented programming in Python

**What you'll do:**

Study your application. Use Charmcraft and Ops to build a basic charm and test-deploy it with Juju and a localhost LXD-based cloud. Repeat the steps to evolve the charm so it can become increasingly more sophisticated.



```{note}

Should you get stuck at any point: Don't hesitate to get in touch on [Matrix](https://matrix.to/#/#charmhub-charmdev:ubuntu.com) or [Discourse](https://discourse.charmhub.io/).

```

## Study your application

In this tutorial we will be writing a charm for Microsample (`microsample`) -- a small educational application that delivers a Flask microservice.

The application has been packaged and published as a snap ([https://snapcraft.io/microsample](https://snapcraft.io/microsample)). We will write our charm such that `juju deploy` will install it from this snap. This will make workload installation straightforward and upgrades automatic (as they will happen automatically through `snapd`).

The application snap has been released into multiple channels -- `edge`, `beta`, `candidate`, and `stable`. We will write our charm such that a user can choose the channel they prefer by running `juju deploy microsample channel=<value>`.

The application has other features that we can exploit, but for now this is enough to get us started with a simple charm.


## Set up your development environment

> See more: {external+juju:ref}`Juju | Manage your deployment environment > Automatically <manage-your-deployment-environment>` for instructions on how to set up your development environment so that it's ready for you to test-deploy your charm. At the charm directory step, call it `microsample-vm`. At the cloud step, choose LXD.

```{important}

-  Going forward:
    - Use your host machine (on Linux, `cd ~/microsample-vm`) to create and edit your charm files. This will allow you to use your favorite local editor.
    - Use the Multipass VM shell (on Linux, `ubuntu@charm-dev:~$ cd ~/microsample-vm`) to run Charmcraft and Juju commands.


- At any point:
    - To exit the shell, press `mod key + C` or type `exit`.
    - To stop the VM after exiting the VM shell, run `multipass stop charm-dev`.
    - To restart the VM and re-open a shell into it, type `multipass shell charm-dev`.

```


## Enable `juju deploy microsample-vm`


Let's charm our `microsample` application into a `microsample-vm` charm such that a user can successfully install it on any machine cloud simply by running `juju deploy microsample-vm`!

In your Multipass VM shell, enter your charm directory, run `charmcraft init --profile machine` to initialise the file tree structure for your machine charm, and inspect the result. Sample session:

```text
# Enter your charm directory:
ubuntu@charm-dev:~$ cd microsample-vm/

# Initialise the charm tree structure:
ubuntu@charm-dev:~/microsample-vm$ charmcraft init --profile machine
Charmed operator package file and directory tree initialised.

Now edit the following package files to provide fundamental charm metadata
and other information:

charmcraft.yaml
src/charm.py
README.md

# Inspect the result:
ubuntu@charm-dev:~/microsample-vm$ ls -R
.:
CONTRIBUTING.md  README.md        pyproject.toml    src    tox.ini
LICENSE          charmcraft.yaml  requirements.txt  tests

./src:
charm.py

./tests:
integration  unit

./tests/integration:
test_charm.py

./tests/unit:
test_charm.py

```

> See more: {external+charmcraft:ref}`Charmcraft | Manage charms <manage-charms>`, {external+charmcraft:ref}`Charmcraft | Files <files>`

In your local editor, open the `charmcraft.yaml` file and customise its contents as below (you only have to edit the `title`, `summary`, and `description`):

```yaml
# (Required)
name: microsample-vm

# (Required)
type: charm

# (Recommended)
title: Microsample VM Charm

# (Required)
summary: A charm that deploys the microsample snap and allows for a configuration of the snap channel via juju config.

# (Required)
description: |
  A machine charm for the Microsample application, built on top of the `microsample` snap.

  The charm allows you to deploy the application via `juju deploy`.
  It also defines a channel config that allows you to choose which snap channel to install from during deployment.

  This charm makes it easy to deploy the Microsample application on any machine cloud.

  The primary value of this charm is educational -- beginner machine charms can study it to learn how to build a machine charm.

# (Required for 'charm' type)
bases:
  - build-on:
    - name: ubuntu
      channel: "22.04"
    run-on:
    - name: ubuntu
      channel: "22.04"

```
> See more: {external+charmcraft:ref}`Charmcraft | File charmcraft.yaml <charmcraft-yaml-file>`

Now open the `src/charm.py` file and update it as below (you'll have to add an import statement for `os` and an observer and handler for the `install` event -- in the definition of which you'll be using `os` and `ops`).

```python
#!/usr/bin/env python3
import os
import logging
import ops

logger = logging.getLogger(__name__)

class MicrosampleVmCharm(ops.CharmBase):

    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.install, self._on_install)

    def _on_start(self, event: ops.StartEvent):
        """Handle start event."""
        self.unit.status = ops.ActiveStatus()

    def _on_install(self, event: ops.InstallEvent):
        """Handle install event."""
        self.unit.status = ops.MaintenanceStatus("Installing microsample snap")
        os.system(f"snap install microsample --channel edge")
        self.unit.status = ops.ActiveStatus("Ready")


if __name__ == "__main__":  # pragma: nocover
    ops.main(MicrosampleVmCharm)  # type: ignore
```

> See more: {external+charmcraft:ref}`Charmcraft | File src/charm.py <src-charm-py-file>`,  {ref}`run-workloads-with-a-charm-machines`

Next, in your Multipass VM shell, inside your project directory, run `charmcraft pack` to pack the charm. It may take a few minutes the first time around but, when it's done, your charm project should contain a `.charm` file. Sample session:


```text
# Pack the charm into a '.charm' file:
ubuntu@charm-dev:~/microsample-vm$ charmcraft pack
Created 'microsample-vm_ubuntu-22.04-amd64.charm'.
Charms packed:
    microsample-vm_ubuntu-22.04-amd64.charm

# Inspect the results -- your charm's root directory should contain a .charm file:
ubuntu@charm-dev:~/microsample-vm$ ls
CONTRIBUTING.md  charmcraft.yaml                          requirements.txt  tox.ini
LICENSE          microsample-vm_ubuntu-22.04-amd64.charm  src
README.md        pyproject.toml                           tests
```

> See more: {external+charmcraft:ref}`Charmcraft | Manage charms > Pack <pack-a-charm>`

Now, open a new shell into your Multipass VM and use it to configure the Juju log verbosity levels and to start a live debug session:

```text
# Set your logging verbosity level to `DEBUG`:
ubuntu@charm-dev:~$  juju model-config logging-config="<root>=WARNING;unit=DEBUG"

# Start a live debug session:
ubuntu@charm-dev:~$  juju debug-log
```

In your old VM shell, use Juju to deploy your charm. If all has gone well, you should see your App and Unit -- Workload status show as `active`:

```text
# Deploy the Microsample VM charm as the 'microsample' application:
ubuntu@charm-dev:~/microsample-vm$ juju deploy ./microsample-vm_ubuntu-22.04-amd64.charm microsample
Located local charm "microsample-vm", revision 0
Deploying "microsample" from local charm "microsample-vm", revision 0 on ubuntu@22.04/stable

# Check the deployment status
# (use --watch 1s to update it automatically at 1s intervals):
ubuntu@charm-dev:~/microsample-vm$ juju status
Model        Controller  Cloud/Region         Version  SLA          Timestamp
welcome-lxd  lxd         localhost/localhost  3.1.6    unsupported  12:49:26+01:00

App          Version  Status  Scale  Charm           Channel  Rev  Exposed  Message
microsample           active      1  microsample-vm             0  no

Unit            Workload  Agent  Machine  Public address  Ports  Message
microsample/0*  active    idle   1        10.122.219.101

Machine  State    Address         Inst id        Base          AZ  Message
1        started  10.122.219.101  juju-f25b73-1  ubuntu@22.04      Running


```

Finally, test that the service works by executing `curl` on your application unit:

```text
ubuntu@charm-dev:~/microsample-vm$  juju exec --unit microsample/0 -- "curl -s http://localhost:8080"
Online
```

```{note}

1. Fix the code in `src/charm.py`.
2. Rebuild the charm: `charmcraft pack`
3. Refresh the application from the repacked charm: `juju refresh microsample --path=./microsample-vm_ubuntu-22.04-amd64.charm --force-units`
4. Let the model know the issue is resolved (fixed): `juju resolved microsample/0`.

```

<!--Might be nice to get people to observe the hooks too:
```
unit-microsample-vm-0
root@microsample-vm-0:/var/lib/juju/agents# cd unit-microsample-vm-0/
root@microsample-vm-0:/var/lib/juju/agents/unit-microsample-vm-0# ls
agent.conf  charm  run.socket  state
root@microsample-vm-0:/var/lib/juju/agents/unit-microsample-vm-0# cd charm
root@microsample-vm-0:/var/lib/juju/agents/unit-microsample-vm-0/charm# ls
LICENSE  README.md  dispatch  hooks  manifest.yaml  metadata.yaml  revision  src  venv
root@microsample-vm-0:/var/lib/juju/agents/unit-microsample-vm-0/charm# cd hooks
root@microsample-vm-0:/var/lib/juju/agents/unit-microsample-vm-0/charm/hooks# ls
install  start  upgrade-charm
root@microsample-vm-0:/var/lib/juju/agents/unit-microsample-vm-0/charm/hooks#
```
-->



```{note}

The template content from `charmcraft init` was sufficient for the charm to pack and deploy successfully.  However, our goal here was to make it run successfully, that is, to actually install the `microsample` application on our LXD cloud. With the edits above, this goal has been achieved.

```


## Enable `juju deploy microsample-vm --config channel=<channel>`

Let's now evolve our charm so that a user can successfully choose which version of `microsample` they want installed by running `juju config microsample-vm channel=<their preferred channel>`!

In your local editor, in your `charmcraft.yaml` file, define the configuration option as below:

```yaml
config:
  options:
    channel:
      description: |
        Channel for the microsample snap.
      default: "edge"
      type: string
```


> See more: {external+charmcraft:ref}`Charmcraft | File charmcraft.yaml | Key config <charmcraft-yaml-key-config>`

Then, in the `src/charm.py` file, update the `_on_install` function to make use of the new configuration option, as below:

```python
def _on_install(self, event: ops.InstallEvent):
    """Handle install event."""
    self.unit.status = ops.MaintenanceStatus("Installing microsample snap")
    channel = self.config.get('channel')
    if channel in ('beta', 'edge', 'candidate', 'stable'):
        os.system(f"snap install microsample --{channel}")
        self.unit.status = ops.ActiveStatus("Ready")
    else:
        self.unit.status = ops.BlockedStatus("Invalid channel configured.")
```

Now, in your Multipass VM shell, inside your project directory, pack the charm, refresh it in the Juju model, and inspect the results:

```text

# Pack the charm:
ubuntu@charm-dev:~/microsample-vm$ charmcraft pack
Created 'microsample-vm_ubuntu-22.04-amd64.charm'.
Charms packed:
    microsample-vm_ubuntu-22.04-amd64.charm

# Refresh the application from the repacked charm:
ubuntu@charm-dev:~/microsample-vm$ juju refresh microsample --path=./microsample-vm_ubuntu-22.04-amd64.charm
Added local charm "microsample-vm", revision 1, to the model

# Verify that the new configuration option is available:
ubuntu@charm-dev:~/microsample-vm$ juju config microsample
application: microsample
application-config:
  trust:
    default: false
    description: Does this application have access to trusted credentials
    source: default
    type: bool
    value: false
charm: microsample-vm
settings:
  channel:
    default: edge
    description: |
      Channel for the microsample snap.
    source: default
    type: string
    value: edge

```

Back to the `src/charm.py` file, in the `__init__` function of your charm, observe the `config-changed` event and pair it with an event handler:

```text
self.framework.observe(self.on.config_changed, self._on_config_changed)
```


Next, in the body of the charm definition, define the event handler, as below:

```python
def _on_config_changed(self, event: ops.ConfigChangedEvent):
    channel = self.config.get('channel')
    if channel in ('beta', 'edge', 'candidate', 'stable'):
        os.system(f"snap refresh microsample --{channel}")
        self.unit.status = ops.ActiveStatus("Ready at '%s'" % channel)
    else:
        self.unit.status = ops.BlockedStatus("Invalid channel configured.")
```

Now, in your Multipass VM shell, inside your project directory, pack the charm, refresh it in the Juju model, and inspect the results:

```text
# Pack the charm:
ubuntu@charm-dev:~/microsample-vm$ charmcraft pack
Created 'microsample-vm_ubuntu-22.04-amd64.charm'.
Charms packed:
    microsample-vm_ubuntu-22.04-amd64.charm

# Refresh the application:
ubuntu@charm-dev:~/microsample-vm$ juju refresh microsample --path=./microsample-vm_ubuntu-22.04-amd64.charm
Added local charm "microsample-vm", revision 2, to the model

# Change the 'channel' config to 'beta':
ubuntu@charm-dev:~/microsample-vm$ juju config microsample channel=beta

# Inspect the Message column
# ('Ready at beta' is what we expect to see if the snap channel has been changed to 'beta'):
ubuntu@charm-dev:~/microsample-vm$ juju status
Model        Controller  Cloud/Region         Version  SLA          Timestamp
welcome-lxd  lxd         localhost/localhost  3.1.6    unsupported  13:54:53+01:00

App          Version  Status  Scale  Charm           Channel  Rev  Exposed  Message
microsample           active      1  microsample-vm             2  no       Ready at 'beta'

Unit            Workload  Agent  Machine  Public address  Ports  Message
microsample/0*  active    idle   1        10.122.219.101         Ready at 'beta'

Machine  State    Address         Inst id        Base          AZ  Message
1        started  10.122.219.101  juju-f25b73-1  ubuntu@22.04      Running
```

Congratulations, your charm users can now deploy the application from a specific channel!

> See more: {ref}`manage-configurations`


## Enable `juju status` with `App Version`

Let's evolve our charm so that a user can see which version of the application has been installed simply by running `juju status`!

In your local editor, update the `requirements.txt` file as below (you'll have to add the `requests` and `requests-unixsocket` lines):

```text
ops ~= 2.5
requests==2.28.1
requests-unixsocket==0.3.0
```

<!--
> See more: [Charmcraft | File `requirements.txt` <file-requirementstxt>`](), [PyPI > Library `requests`](https://pypi.org/project/requests/), [PyPI > Library `requests-unixsocket`](https://pypi.org/project/requests-unixsocket/)
-->

Then, in your `src/charm.py` file, import the `requests_unixsocket` package, update the `_on_config_changed` function to set the workload version to the output of a function `_getWorkloadVersion`, and define the function to retrieve the Microsample workload version from the `snapd` API via a Unix socket, as below:

```python
#!/usr/bin/env python3
# Copyright 2023 Ubuntu
# See LICENSE file for licensing details.

"""Charm the application."""

import os
import logging
import ops
import requests_unixsocket

logger = logging.getLogger(__name__)


class MicrosampleVmCharm(ops.CharmBase):
    """Charm the application."""

    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.config_changed, self._on_config_changed)

    def _on_start(self, event: ops.StartEvent):
        """Handle start event."""
        self.unit.status = ops.ActiveStatus()

    def _on_install(self, event: ops.InstallEvent):
        """Handle install event."""
        self.unit.status = ops.MaintenanceStatus("Installing microsample snap")
        channel = self.config.get('channel')
        if channel in ('beta', 'edge', 'candidate', 'stable'):
            os.system(f"snap install microsample --{channel}")
            self.unit.status = ops.ActiveStatus("Ready")
        else:
            self.unit.status = ops.BlockedStatus("Invalid channel configured.")

    def _on_config_changed(self, event: ops.ConfigChangedEvent):
        channel = self.config.get('channel')
        if channel in ('beta', 'edge', 'candidate', 'stable'):
            os.system(f"snap refresh microsample --{channel}")
            workload_version = self._getWorkloadVersion()
            self.unit.set_workload_version(workload_version)
            self.unit.status = ops.ActiveStatus("Ready at '%s'" % channel)
        else:
            self.unit.status = ops.BlockedStatus("Invalid channel configured.")

    def _getWorkloadVersion(self):
        """Get the microsample workload version from the snapd API via unix-socket"""
        snap_name = "microsample"
        snapd_url = f"http+unix://%2Frun%2Fsnapd.socket/v2/snaps/{snap_name}"
        session = requests_unixsocket.Session()
        # Use the requests library to send a GET request over the Unix domain socket
        response = session.get(snapd_url)
        # Check if the request was successful
        if response.status_code == 200:
            data = response.json()
            workload_version = data["result"]["version"]
        else:
            workload_version = "unknown"
            print(f"Failed to retrieve Snap apps. Status code: {response.status_code}")

        # Return the workload version
        return workload_version

if __name__ == "__main__":  # pragma: nocover
    ops.main(MicrosampleVmCharm)  # type: ignore
```

<!--NOT SURE IF WE NEED TO LINK TO THESE AGAIN
> See more: [File `src/charm.py` <file-srccharmpy>`, {ref}`Ops <ops-ops>`,  {ref}`Event `config-changed` <event-config-changed>`
-->

Finally, in your Multipass VM shell, pack the charm, refresh it in Juju, and check the Juju status -- it should now show the version of your workload.

```text
# Pack the charm:
ubuntu@charm-dev:~/microsample-vm$ charmcraft pack
Created 'microsample-vm_ubuntu-22.04-amd64.charm'.
Charms packed:
    microsample-vm_ubuntu-22.04-amd64.charm

# Refresh the application:
ubuntu@charm-dev:~/microsample-vm$ juju refresh microsample --path=./microsample-vm_ubuntu-22.04-amd64.charm
Added local charm "microsample-vm", revision 3, to the model

# Verify that the App Version now shows the version:
ubuntu@charm-dev:~/microsample-vm$ juju status
Model        Controller  Cloud/Region         Version  SLA          Timestamp
welcome-lxd  lxd         localhost/localhost  3.1.6    unsupported  14:04:39+01:00

App          Version        Status  Scale  Charm           Channel  Rev  Exposed  Message
microsample  0+git.49ff7aa  active      1  microsample-vm             3  no       Ready at 'beta'

Unit            Workload  Agent  Machine  Public address  Ports  Message
microsample/0*  active    idle   1        10.122.219.101         Ready at 'beta'

Machine  State    Address         Inst id        Base          AZ  Message
1        started  10.122.219.101  juju-f25b73-1  ubuntu@22.04      Running
```

Congratulations, your charm user can view the version of the workload deployed from your charm!



## Tear things down

> See [Juju | Tear down your development environment automatically](https://juju.is/docs/juju/set-up--tear-down-your-test-environment#tear-down-automatically)



(tutorial-machines-next-steps)=
## Next steps

By the end of this tutorial you will have built a machine charm and evolved it in a number of typical ways. But there is a lot more to explore:

| If you are wondering... | visit...             |
|-------------------------|----------------------|
| "How do I...?"          | {ref}`how-to-guides` |
| "What is...?"           | {ref}`reference`     |
| "Why...?", "So what?"   | {ref}`explanation`   |


