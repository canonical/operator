(set-up-your-development-environment)=
# Set up your development environment

> <small>{ref}`From zero to hero: Write your first Kubernetes charm <from-zero-to-hero-write-your-first-kubernetes-charm>`  > Set up your development environment</small>
>
> **See previous: {ref}`Study your application <study-your-application>`**

## Create a virtual machine

You'll deploy and test your charm inside an Ubuntu virtual machine that's running on your computer. Your virtual machine will provide an isolated environment that's safe for you to experiment in, without affecting your host machine. This is especially helpful for the charm's integration tests, which require a local Juju controller and Kubernetes cloud.

First, install Multipass for managing virtual machines. See the [installation instructions](https://canonical.com/multipass/install).

Next, open a terminal, then run:

```text
multipass launch --cpus 4 --memory 8G --disk 50G --name juju-sandbox-k8s
```

This creates a virtual machine called `juju-sandbox-k8s`.

Multipass allocates some of your computer's memory and disk space to your virtual machine. The options we've chosen for `multipass launch` ensure that your virtual machine will be powerful enough to run Juju and deploy medium-sized charms.

This step should take less than 10 minutes, but the time depends on your computer and network. When your virtual machine has been created, you'll see the message:

```text
Launched: juju-sandbox-k8s
```

Now run:

```text
multipass shell juju-sandbox-k8s
```

This switches the terminal so that you're working inside your virtual machine.

You'll see a message with information about your virtual machine. You'll also see a new prompt:

```text
ubuntu@juju-sandbox-k8s:~$
```

## Install Juju and charm development tools

Now that you have a virtual machine, you need to install the following tools on your virtual machine:

- **Charmcraft, Juju, and Canonical Kubernetes** - You'll use {external+charmcraft:doc}`Charmcraft <index>` to create the initial version of your charm and prepare your charm for deployment. When you deploy your charm, Juju will use Canonical Kubernetes to create a Kubernetes cloud for your charm.
- **uv** - Your charm will be a Python project. You'll use [uv](https://docs.astral.sh/uv/) to manage your charm's runtime and development dependencies.
- **tox** - You'll use [tox](https://tox.wiki/en/) to run your charm's checks and tests.

Instead of manually installing and configuring each tool, we recommend using [Concierge](https://github.com/canonical/concierge), Canonical's tool for setting up charm development environments.

In your virtual machine, run:

```text
sudo snap install --classic concierge
sudo concierge prepare -p k8s --extra-snaps astral-uv
```

This first installs Concierge, then uses Concierge to install and configure the other tools (except tox). The option `-p k8s` tells Concierge that we want tools for developing Kubernetes charms, with a local cloud managed by Canonical Kubernetes.

This step should take less than 15 minutes, but the time depends on your computer and network. When the tools have been installed, you'll see a message that ends with:

```text
msg="Bootstrapped Juju" provider=k8s
```

To install tox, run:

```text
uv tool install tox --with tox-uv
```

When tox has been installed, you'll see a confirmation and a warning:

```text
Installed 1 executable: tox
warning: `/home/ubuntu/.local/bin` is not on your PATH. To use installed tools,
run `export PATH="/home/ubuntu/.local/bin:$PATH"` or `uv tool update-shell`.
```

Instead of following the warning, exit your virtual machine:

```text
exit
```

The terminal switches back to your host machine. Your virtual machine is still running.

Next, stop your virtual machine:

```text
multipass stop juju-sandbox-k8s
```

Then use the Multipass {external+multipass:ref}`snapshot <reference-command-line-interface-snapshot>` command to take a snapshot of your virtual machine:

```text
multipass snapshot juju-sandbox-k8s
```

If you have any problems with your virtual machine during or after completing the tutorial, use the Multipass {external+multipass:ref}`restore <reference-command-line-interface-restore>` command to restore your virtual machine to this point.

## Create a project directory

Although you'll deploy and test your charm inside your virtual machine, you'll probably find it more convenient to write your charm using your usual text editor or IDE.

Outside your virtual machine, create a project directory:

```text
mkdir ~/k8s-tutorial
```

You'll write your charm in this directory.

Next, use the Multipass {external+multipass:ref}`mount <reference-command-line-interface-mount>` command to make the directory available inside your virtual machine:

```text
multipass mount --type native ~/k8s-tutorial juju-sandbox-k8s:~/fastapi-demo
```

Finally, start your virtual machine and switch to your virtual machine:

```text
multipass shell juju-sandbox-k8s
```

Congratulations, your development environment is ready!

> **See next: {ref}`Create a minimal Kubernetes charm <create-a-minimal-kubernetes-charm>`**
