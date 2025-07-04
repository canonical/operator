# Gosherve Demo Charm

## Contents

- [Overview](#overview)
- [Quickstart](#quickstart)
- [Development Setup](#development-setup)
- [Build and Deploy Locally](#build-and-deploy-locally)
- [Testing](#testing)
- [Get Help & Community](#get-help--community)
- [More Information/Related](#more-informationrelated)

## Overview

This [charm](https://charmhub.io/hello-kubecon) was originally a demonstration
of a charm implementing the (at the time new) Kubernetes sidecar pattern used
during [Operator Day 2021](https://www.linkedin.com/events/6788422954821656577/).

Since then, the state of the charming world moved on, and the original
[repository](https://github.com/jnsgruk/hello-kubecon) was archived. The charm
in this folder is a version of that one, with some [modernisation](CHANGES.md).

The charm is written using [Ops](https://github.com/canonical/operator).
It deploys [gosherve](https://github.com/jnsgruk/gosherve), relying upon the
charm container to populate a shared volume with a simple
[landing-page](https://github.com/canonical-web-and-design/kubecon-2021/) style
website and configure the app before it is started.

The original version of the finished charm is published
[on Charmhub](https://charmhub.io/hello-kubecon), and you can also read the
[original slides](./slides/Operator%20Day%202021%20-%20Live%20Demo%20Slides.pdf),
but note that these are both somewhat out of date now, and using the
[updated slide content](./slides/gosherve-demo-slides.md) may be more useful.

The charm will:

- Deploy a container running [gosherve](https://github.com/jnsgruk/gosherve)
- Fetch a website [from GitHub](https://jnsgr.uk/demo-site-repo)
- Place the downloaded file in a storage volume
- Expose a `redirect-map` config item to configure
  [gosherve](https://github.com/jnsgruk/gosherve) redirects
- Expose a `pull-site` action to pull the latest version of the test site
- Utilise an ingress relation using the
  [`traefik-k8s`](https://charmhub.io/traefik-k8s) library

## Quickstart

Assuming you already have Juju installed and bootstrapped on a cluster (if you
do not, see the next section):

```bash
# Create a juju model
juju add-model dev
# Deploy the charm
juju deploy gosherve-demo-k8s --resource gosherve-image=jnsgruk/gosherve:latest
# Deploy the ingress charm
juju deploy traefik-k8s --trust
juju config traefik-k8s external_hostname=juju.local
juju config traefik-k8s routing_mode=subdomain
# Relate our app to the ingress
juju integrate gosherve-demo-k8s traefik-k8s
# Wait for the deployment to complete
juju status --watch=1s
# Add an entry to /etc/hosts
echo "<traefik-k8s-address> dev-gosherve-demo.juju.local" | sudo tee -a /etc/hosts
```

You should be able to visit
[http://dev-gosherve-demo.juju.local](http://dev-gosherve-demo.juju.local) in
your browser.

## Development Setup

To set up a local test environment with [Canonical K8s](https://snapcraft.io/k8s):

```bash
# Install concierge
sudo snap install --classic concierge
# Prepare a dev environment
sudo concierge prepare -p dev
```

## Build and Deploy Locally

```bash
# Clone the charm code
git clone https://github.com/canonical/operator && cd examples/gosherve-demo
# Fetch the charmlibs
charmcraft fetch-libs
# Build the charm package
charmcraft pack
# Create a juju model
juju add-model dev
# Deploy!
juju deploy ./gosherve-demo-k8s_amd64.charm --resource gosherve-image=jnsgruk/gosherve:latest
# Deploy the ingress charm
juju deploy traefik-k8s --trust
juju config traefik-k8s external_hostname=juju.local
juju config traefik-k8s routing_mode=subdomain
# Relate our app to the ingress
juju integrate gosherve-demo-k8s traefik-k8s
# Wait for the deployment to complete
juju status --watch=1s
# Add an entry to /etc/hosts
echo "<traefik-k8s-address> dev-gosherve-demo.juju.local" | sudo tee -a /etc/hosts
```

You should be able to visit
[http://dev-gosherve-demo.juju.local](http://dev-gosherve-demo.juju.local) in
your browser.

## Testing

```bash
# Clone the charm code
git clone https://github.com/canonical/operator && cd examples/gosherve-demo
# Install uv, if you don't already have it
sudo snap install astral-uv --classic
# Install tox and tox-uv
uv tool install tox --with=tox-uv
# Run the linting, static checks, and unit tests
tox
# Run the integration tests (requires a bootstrapped Kubernetes Juju controller)
tox -e integration
```

## Get Help & Community

If you get stuck deploying this charm, or would like help with charming
generally, come and join the charming community!

- [Community Discourse](https://discourse.charmhub.io)
- [Community Chat](https://matrix.to/#/#charmhub-charmdev:ubuntu.com)

## More Information/Related

Below are some links related to this demonstration:

- [Ops Documentation](https://ops.readthedocs.io/en/latest/)
- [Ops Source](https://github.com/canonical/operator)
- [Juju](https://juju.is)
- [Juju Documentation](https://juju.is/docs/)
- [Charmhub](https://charmhub.io)
- [Pebble Documentation](https://documentation.ubuntu.com/pebble/)
- [Pebble Source](https://github.com/canonical/pebble)
