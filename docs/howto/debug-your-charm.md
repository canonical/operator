(debug-your-charm)=
# How to debug your charm

> See first: {ref}`log-from-your-charm`, {external+juju:ref}`Juju | How to manage logs <manage-logs>`

When your charm isn't behaving as expected, Juju and the broader charming ecosystem provide several tools to help you investigate. This guide covers how to get a shell on a running unit, read charm logs, interactively debug hook execution, and use third-party tools to accelerate your debugging workflow.

(ssh-into-a-unit)=
## Get a shell on a running unit with `juju ssh`

The quickest way to poke around a live unit is to SSH into it with `juju ssh`. What you connect to depends on the substrate:

**Machine charms.** `juju ssh` connects you to the machine itself. You land in a shell as the `ubuntu` user, which has password-less `sudo`:

```shell
juju ssh myapp/0
```

**Kubernetes charms.** A K8s charm pod typically has multiple containers (the charm container and one or more workload containers). Use `--container` to choose which container to connect to:

```shell
juju ssh --container myworkload myapp/0
```

If you omit `--container`, `juju ssh` targets the charm container by default.

````{important}
**Juju 4: SSH keys are no longer added automatically.**

In Juju 3.x, your SSH public key is automatically added to every model you create. In Juju 4, this no longer happens -- you must add your key explicitly before `juju ssh` will work:

```shell
juju add-ssh-key "$(cat ~/.ssh/id_ed25519.pub)"
```

You can also import keys from GitHub or Launchpad:

```shell
juju import-ssh-key gh:<your-github-username>
```
````

> See more: {external+juju:ref}`Juju | juju ssh <command-juju-ssh>`

(debug-with-pebble)=
## Inspect the workload with Pebble (Kubernetes charms)

In Kubernetes charms, each workload container runs {external+pebble:doc}`Pebble <index>` as its init system. You can use Pebble commands to inspect and interact with the workload directly. First, SSH into the workload container:

```shell
juju ssh --container <container-name> <unit>
```

Then use the Pebble CLI (available at `/charm/bin/pebble`) to inspect the workload.

### Check service status

`pebble services` shows whether each service in the container is running:

```text
$ /charm/bin/pebble services
Service   Startup  Current  Since
workload  enabled  active   today at 02:05 UTC
```

A service in `backoff` or `error` state tells you the workload has been crashing.

### View service logs

`pebble logs` shows recent stdout and stderr from services. Use `-f` to follow in real time:

```shell
/charm/bin/pebble logs              # last 30 lines from all services
/charm/bin/pebble logs -f           # tail and follow
/charm/bin/pebble logs -n all       # show all buffered output
```

```{note}
Pebble keeps the most recent output from each service in a 100 KB ring buffer. Older output is discarded, so if you need persistent logs consider configuring a Pebble {external+pebble:doc}`log forwarding target <how-to/forward-logs-to-loki>`.
```

### Run commands in the container

`pebble exec` runs a one-off command inside the container. This is useful for checking files, environment variables, or connectivity:

```shell
/charm/bin/pebble exec -- ls /etc/myapp/
/charm/bin/pebble exec --context myworkload -- env   # inherit the service's environment
```

### View the effective Pebble plan

`pebble plan` prints the merged configuration that Pebble is currently using. This is helpful to verify that the layers your charm wrote are correct:

```text
$ /charm/bin/pebble plan
services:
    myworkload:
        summary: my workload service
        startup: enabled
        override: replace
        command: my-workload
```

### Check health checks

If the charm configures Pebble health checks, `pebble checks` shows their current status:

```shell
/charm/bin/pebble checks
```

> See more: {external+pebble:doc}`Pebble | CLI commands <reference/cli-commands>`

(read-charm-logs)=
## Read charm logs with `juju debug-log`

The `juju debug-log` command streams log messages from every agent in a model. It is the first tool to reach for when something goes wrong. By default it shows recent log lines and then tails new output. Common flags:

```shell
juju debug-log --replay                          # show full history, then tail
juju debug-log --replay --no-tail                # show full history, then exit
juju debug-log --level WARNING                   # only warnings and above
juju debug-log --include unit-myapp-0            # only logs from myapp/0
juju debug-log --include-module unit.myapp/0.juju-log  # only charm-level logs
```

Multiple `--include` or `--exclude` flags are combined with 'OR' within each category, and the categories (entity, module, label) are joined with 'AND'. This lets you build precise filters. For example, to see only charm logs and uniter operations at DEBUG level:

```shell
juju debug-log --debug \
  --include-module juju.worker.uniter.operation \
  --include-module unit.myapp/0.juju-log
```

````{tip}
Use `--limit N` to fetch the last *N* lines and exit immediately -- handy for scripting or quick checks:

```shell
juju debug-log --limit 100
```
````

The `--level` and `--debug` flags on `juju debug-log` only filter what is *displayed* -- they do not change what Juju actually records. To control which log levels are *stored*, use the `logging-config` model setting:

```shell
juju model-config logging-config="<root>=WARNING;unit=DEBUG"
```

This tells Juju to store DEBUG-level messages from charm units while keeping everything else at WARNING. For this to show up in your logs, you'll need to set `logging-config` *before* the event you're interested in runs.

```{tip}
If you raise the stored log level for debugging (e.g. to DEBUG or TRACE), remember to restore it to the default once you are done. Verbose logs consume storage in the Juju database and can affect controller performance.
```

> See more: {external+juju:ref}`Juju | juju debug-log <command-juju-debug-log>`, {external+juju:ref}`Juju | logging-config <model-config-logging-config>`

(use-jhack)=
## Use jhack for a faster debugging workflow

[jhack](https://github.com/canonical/jhack) is a toolkit that provides higher-level utilities on top of Juju. Several of its commands are particularly useful during charm development and debugging, but in general jhack is not intended for production use. You do not need to modify your charm to use jhack, just install it:

```shell
sudo snap install jhack
sudo snap connect jhack:dot-local-share-juju snapd
```

### Monitor events with `jhack tail`

`jhack tail` watches the Juju log and displays charm events in a colour-coded, formatted table. It is much easier to scan than raw `juju debug-log` output when you want to understand the flow of events:

```shell
jhack tail myapp
```

### Trigger events with `jhack fire`

`jhack fire` simulates a specific event on a live unit. This is useful for triggering an event on demand without waiting for Juju to emit it naturally:

```shell
jhack fire myapp/0 update-status
jhack fire myapp/0 config-changed
```

```{caution}
Firing events manually can desynchronise charm state from Juju state if your event handlers are not idempotent. Use this only in development and test environments.
```

### Push local changes with `jhack sync`

`jhack sync` watches local directories and automatically pushes file changes to remote charm units. Combined with `jhack fire`, this enables a rapid edit-trigger-observe loop:

```shell
jhack sync myapp/0 --source ./src --source ./lib
```

### Inspect state with `jhack script`

`jhack script` runs a custom Python script directly on a live unit. The script receives a charm instance and can inspect relations, config, and stored state without waiting for an event:

```python
# inspect_relations.py
def main(charm):
    for relation in charm.model.relations['database']:
        print(relation.data[relation.app])
```

```shell
jhack script myapp/0 ./inspect_relations.py
```

### Inspect relation data with `jhack show-relation`

`jhack show-relation` displays the relation databags for all units involved in a relation:

```shell
jhack show-relation myapp:database postgresql:database
```

> See more: [jhack](https://github.com/canonical/jhack)

(debug-hooks)=
## Interactively debug hooks with `juju debug-hooks`

The `juju debug-hooks` command opens a [`tmux`](https://github.com/tmux/tmux/wiki) session on a unit. When a matching hook fires, the session navigates to the charm directory with the full hook environment configured -- but the hook is **not** executed automatically. This gives you a chance to inspect the environment, modify files, and run the hook yourself.

```shell
juju debug-hooks myapp/0                       # intercept all hooks and actions
juju debug-hooks myapp/0 config-changed        # intercept only config-changed
```

*Once a hook fires*, the `tmux` session lands in the charm directory. From there you can:

- Inspect the environment variables that Juju provides (e.g. `JUJU_DISPATCH_PATH`).
- Examine or modify files under `src/`.
- Run `./dispatch` to execute the hook manually.
- Run `./dispatch` again after making changes, to iterate.
- Exit the `tmux` session to let the unit resume normal operation.

```{note}
While a hook is being debugged, the unit is paused. Other hooks queue up and execute in order once you exit. Keep your debugging sessions short to avoid blocking the unit for too long.
```

> See more: {external+juju:ref}`Juju | juju debug-hooks <command-juju-debug-hooks>`

(debug-code)=
## Step through charm code with `juju debug-code`

The `juju debug-code` command is similar to `debug-hooks`, but the hook **is** executed automatically. Juju sets the `JUJU_DEBUG_AT` environment variable, which Ops uses to activate breakpoints. When execution reaches a breakpoint, you are dropped into a {external+python:mod}`pdb` session where you can inspect variables and step through the code.

```shell
juju debug-code myapp/0                        # debug all hooks
juju debug-code myapp/0 config-changed         # debug a specific hook
```

### Use named breakpoints

In your charm code, call [](ops.Framework.breakpoint) to define breakpoints that you can selectively activate:

```python
class MyCharm(ops.CharmBase):
    def _on_config_changed(self, event: ops.ConfigChangedEvent):
        self.framework.breakpoint('config-start')  # 'config-start' is an arbitrary string you use with `--at`
        new_val = self.config['setting']
        # ... process the new value ...
        self.framework.breakpoint('config-end')
```

By default, `juju debug-code` sets `JUJU_DEBUG_AT=all`, activating every breakpoint. To activate only specific breakpoints, use `--at`:

```shell
juju debug-code --at=config-start myapp/0 config-changed
```

Python's built-in {external+python:func}`breakpoint` also works when `JUJU_DEBUG_AT` is set, so you can use either form.

> See more: {external+juju:ref}`Juju | juju debug-code <command-juju-debug-code>`

(remote-debugging-with-vs-code)=
## Remote debugging with VS Code

For a richer debugging experience, you can attach VS Code's debugger to a running charm using [`debugpy`](https://github.com/microsoft/debugpy). This gives you a full graphical debugger with breakpoints, variable inspection, watch expressions, and call stack navigation.

### Set up the charm

Add `debugpy` as a dependency of your charm. For example, with uv run `uv add debugpy` to add it to the `[project]` dependencies in `pyproject.toml`; with Poetry run `poetry add debugpy`; or with a plain `requirements.txt`, add a `debugpy` line. Remember to remove this when you're finished debugging.

Then, at the top of your `charm.py` module, add a `debugpy` listener that activates when you run `juju debug-code`:

```python
import os

if os.getenv('JUJU_DEBUG_AT'):
    import debugpy
    debugpy.listen(('0.0.0.0', 5678))
    debugpy.wait_for_client()
```

Repack and deploy the charm with `charmcraft pack`.

### Configure VS Code

Add the following launch configuration to `.vscode/launch.json` in your charm project:

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Attach to charm",
            "type": "python",
            "request": "attach",
            "connect": {
                "host": "<UNIT_IP>",
                "port": 5678
            },
            "pathMappings": [
                {
                    "localRoot": "${workspaceFolder}",
                    "remoteRoot": "."
                }
            ],
            "justMyCode": true
        }
    ]
}
```

Find the unit IP with:

```shell
juju show-unit myapp/0 | yq '.*.address'
```

### Start a debug session

1. Run `juju debug-code myapp/0` to tell Juju to set `JUJU_DEBUG_AT` on the next hook execution.
2. Trigger the hook you want to debug (or wait for it to fire naturally). The charm will start `debugpy` and block until a client connects.
3. In VS Code, set your breakpoints (note that you'll need to have a breakpoint in an event handler to get access to the Ops event object) and press **F5** (or click **Run > Start Debugging**).

````{tip}
**Debugging when Juju runs inside a Multipass VM**

If your Juju model is inside a Multipass VM (a common setup for local charm development), VS Code on your host machine cannot reach the charm unit's IP directly. Use an SSH port forward through the VM to bridge the gap:

```shell
# 1. Get the unit IP from inside the VM:
UNIT_IP=$(multipass exec <vm-name> -- juju show-unit myapp/0 --format json \
  | jq -r '.["myapp/0"]["public-address"]')

# 2. Get the VM's IP:
VM_IP=$(multipass info <vm-name> --format json | jq -r '.info["<vm-name>"].ipv4[0]')

# 3. If necessary, make sure that you are authorised to SSH into the VM, for example by adding your SSH public key to `~/.ssh/authorized_keys` on the VM.

# 4. Forward the debugpy port through the VM to your host:
ssh -N -L 5678:${UNIT_IP}:5678 ubuntu@${VM_IP}
```

Then, in your `launch.json`, set `"host"` to `"localhost"` instead of the unit IP. VS Code will connect to the forwarded port on your host, and the SSH tunnel will relay traffic to `debugpy` on the charm unit inside the VM.
````
