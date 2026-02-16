(pebble-metrics)=
# How to manage Pebble metrics

Pebble provides [metrics](https://documentation.ubuntu.com/pebble/reference/api/#/metrics/get_v1_metrics) for services and health checks in OpenMetrics format. Access to the Pebble metrics endpoint requires HTTP basic authentication with a username and password.

Charms should use {external+juju:ref}`Juju secrets <secret>` to manage sensitive information such as authentication credentials.

This guide demonstrates how to:

- Create a Juju user secret that stores the username and password. Users who deploy the charm will also need to do this.
- Add a configuration option to pass the secret ID to the charm.
- In the charm code, get the username and password from the secret, then create a {external+pebble:doc}`Pebble identity <reference/identities>` to allow access to the metrics endpoint using the username and password.
- Access the metrics endpoint after deploying the charm. Users who deploy the charm will also be able to do this.

## Create a Juju user secret

Run {external+juju:ref}`juju add-secret <command-juju-add-secret>` to create a Juju user secret:

```bash
juju add-secret metrics-user-password username=test password=test
```

```{caution}

- Use a random password generator to create a password. You can use your preferred password manager to generate one and store it securely in the password manager as the single source of truth.
- Do not use this password for anything else other than metrics, because it will be sent over unencrypted HTTP as basic authentication.

```

This command returns a secret ID, which you'll need in the following steps.

## Add a configuration option for the secret ID

To pass the secret ID to the charm, define a configuration option named `metrics-secret-id` in `charmcraft.yaml`:

```yaml
config:
  options:
    metrics-secret-id:
      description: Secret ID for the metrics username and password
      type: string
```

## Create a Pebble identity

The charm retrieves the ID of the secret that stores the username and password from the configuration option.

In the handler for the `config-changed` event, we'll retrieve the contents of the secret and create a Pebble identity. We'll also handle the `secret-changed` event, in case the charm user changes the contents of the secret.

After retrieving the contents of the secret, we'll use the [`replace_identities`](ops.pebble.Client.replace_identities) method to create a "basic" type identity in Pebble:

```python
from passlib.hash import sha512_crypt

class MyCharm(ops.CharmBase):
    ...

    def _on_config_changed(self, event: ops.ConfigChangedEvent) -> None:
        # The user must have:
        # - Created a secret with keys 'username' and 'password'
        # - Stored the secret ID in the 'metrics-secret-id' configuration option
        if not self.config.get('metrics-secret-id'):
            return
        secret_id = str(self.config["metrics-secret-id"])
        secret = self.model.get_secret(id=secret_id)
        content = secret.get_content()
        self._replace_identities(content["username"], content["password"])

    def _on_secret_changed(self, event: ops.SecretChangedEvent) -> None:
        if not self.config.get('metrics-secret-id'):
            return
        if event.secret.id == self.config['metrics-secret-id']:
            content = event.secret.peek_content()
            self._replace_identities(content["username"], content["password"])

    def _replace_identities(self, username: str, password: str) -> None:
        identities = {
            username: ops.pebble.Identity(
                access="metrics",
                basic=ops.pebble.BasicIdentity(password=sha512_crypt.hash(password))
            ),
        }
        self.container.pebble.replace_identities(identities)
        logger.debug("New metrics username: %s", username)

    ...
```

The password of the Pebble identity is stored as a hash, which we generate using [`sha512_crypt.hash()`](https://passlib.readthedocs.io/en/stable/lib/passlib.hash.sha512_crypt.html) from [`passlib.hash`](https://passlib.readthedocs.io/en/stable/lib/passlib.hash.html).

When Pebble receives a request to access the metrics endpoint, Pebble will verify that the basic authentication credentials in the request match the identity's username and password.

> See more:
> - {ref}`make-your-charm-configurable`
> - {ref}`manage-configuration`
> - {ref}`manage-secrets`

## Deploy the charm and grant access to the user secret

We'll use a configuration file to set `metrics-secret-id` to the secret ID.

First, create a configuration file named `metrics-config.yaml`:

```yaml
metrics-charm:
  metrics-secret-id: <secret-id-here>
```

Then, when deploying the charm, use the `--config` option to pass the configuration file:

```bash
juju deploy <charm-name> --config metrics-config.yaml
```

After deploying the charm, {external+juju:ref}`grant access <command-juju-grant-secret>` to the user secret:

```bash
juju grant-secret metrics-user-password <charm-name>
```

## Access the metrics endpoint

### Within the same Kubernetes cluster

Deploying the charm causes Juju to create a Kubernetes service named `<charm-name>-endpoints` within the Kubernetes cluster. Use this service to connect to Pebble within each workload container. Pebble's HTTP port for the first workload container is `38813`.

For example, if you deploy a charm named `my-charm` in the `test` namespace, access the metrics endpoint at:

```text
my-charm-endpoints.test.svc.cluster.local:38813/v1/metrics
```

You'll need to use HTTP basic authentication with the username and password that you specified in the `juju add-secret` command.

> See more: [Service discovery within a Kubernetes cluster](https://kubernetes.io/docs/concepts/services-networking/dns-pod-service/)

### Through an Ingress

To access the metrics endpoint from outside the Kubernetes cluster, use an [Ingress](https://kubernetes.io/docs/concepts/services-networking/ingress/).

Use the service `<charm-name>` service in the Ingress (which is also created by Juju) instead of the `<charm-name>-endpoints` service, as the latter is a [headless service](https://kubernetes.io/docs/concepts/services-networking/service/#headless-services) and doesn't have a ClusterIP.

- To expose the Pebble HTTP port, use [`set_ports`](ops.Unit.set_ports) in your charm code:

```python
    self.unit.set_ports(38813)
```

- To create an Ingress, use the following Ingress resource example (assuming the charm and service name is `my-charm`):

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: metrics
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /$1
spec:
  rules:
  - http:
      paths:
      - path: /my-charm/(.*)
        pathType: Prefix
        backend:
          service:
            name: my-charm
            port:
              number: 38813
```

Access the metrics endpoint with HTTP basic authentication at `HOSTNAME/my-charm/v1/metrics`.
