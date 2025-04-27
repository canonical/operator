# How to Manage Metrics

Pebble provides services and health check [metrics](https://documentation.ubuntu.com/pebble/reference/api/#/metrics/get_v1_metrics) in OpenMetrics format. Access this endpoint requires HTTP basic authentication with a "basic" type [identity](https://documentation.ubuntu.com/pebble/reference/identities/).

Charms should use {external+juju:ref}`Juju secrets <secret>` to manage sensitive information such as authentication credentials.

This guide demonstrates how to:

- As an admin, create a Juju user secret that stores the username and password.
- Add a configuration to pass the secret ID to a charm.
- In the charm code, get the username and password from the secret, then create a {external+pebble:doc}`Pebble identity <reference/identities>` to allow access to the metrics endpoint using the username and password.
- As a user, access the metrics endpoint after deploying the charm.

## Create a Juju user secret

Use {external+juju:ref}`Juju secret <secret>` to manage sensitive information like HTTP basic authentication credentials. Run the following command to create a Juju user secret:

```bash
juju add-secret metrics-user-password username=test password=test
```

See more:

- {external+juju:ref}`juju add-secret <command-juju-add-secret>`.

## Pass the secret ID to the charm via configurations

The `juju add-secret` command returns the secret ID. Pass this ID to the charm using configurations. For example, define an option named `metrics-secret-id` in `charmcraft.yaml`:

```yaml
config:
  options:
    metrics-secret-id:
      default: <secret-id-here>
      description: Default secret ID for the metrics username and password
      type: string
```

## Create a "basic" type Pebble identity

The charm code will use the configuration option to determine the ID of the secret that stores the username and password.

In the handler for the `config-changed` event, retrieve the contents of the secret and create a Pebble identity. We should also handle the `secret-changed` event, in case admin users change the contents of the secret.

With the secret content, we can create a "basic" type identity in Pebble using the [`pebble.Client.replace_identities`](ops.pebble.Client.replace_identities) method:

```python
from passlib.hash import sha512_crypt

class MyCharm(ops.CharmBase):
  ...

  def _on_config_changed(self, event: ops.ConfigChangedEvent) -> None:
    # The user must have:
    # - Created a secret with keys 'username' and 'password'
    # - Stored the secret ID in the 'metrics-secret-id' configuration option
    secret_id = str(self.config["metrics-secret-id"])
    secret = self.model.get_secret(id=secret_id)
    content = secret.get_content()
    username, password = content["username"], content["password"]
    self._replace_identities(username, password)

  def _on_secret_changed(self, event: ops.SecretChangedEvent) -> None:
    content = event.secret.peek_content()
    username, password = content["username"], content["password"]
    self._replace_identities(username, password)

  def _replace_identities(self, username: str, password: str) -> None:
    identities = {
      username: ops.pebble.Identity(
        access="metrics", basic=ops.pebble.BasicIdentity(password=sha512_crypt.hash(password))
      ),
    }
    self.container.pebble.replace_identities(identities)
    logger.debug("New metrics username: %s", username)

  ...
```

Note that the identity's password is stored as a hash. Hash the password using `sha512-crypt`. Import `sha512_crypt` from `passlib.hash` and generate the hash with `sha512_crypt.hash()`.

When Pebble receives a request to access the metrics endpoint, Pebble will verify that the basic authentication credentials in the request match the identity's username and password.

See more:

- {ref}`make-your-charm-configurable`
- {ref}`manage-configurations`
- {ref}`manage-secrets`

## Grant access to the user secret

After deploying the charm, grant access to the user secret:

```bash
juju grant-secret metrics-user-password <charm-name>
```

See more: 

- {external+juju:ref}`juju grant-secret <command-juju-grant-secret>`.
- {external+juju:ref}`Juju | config <command-juju-config>`

## Access the metrics endpoint

### Within the same Kubernetes cluster

When you deploy the charm, Juju automatically creates a Kubernetes service named `<charm-name>-endpoints` within the Kubernetes cluster. Use this service to connect to Pebble within each workload container. The HTTP port for Pebble in the first workload container is `38813`.

For example, if the charm is named `my-charm` and deployed in the namespace `test`, access the metrics endpoint at `my-charm-endpoints.test.svc.cluster.local:38813/v1/metrics`. You'll need to use HTTP basic authentication with the username and password that you specified in the `juju add-secret` command.

See more:

- [Service discovery within a Kubernetes cluster](https://kubernetes.io/docs/concepts/services-networking/dns-pod-service/)

### Through an Ingress

To access the metrics endpoint from outside the Kubernetes cluster, use an Ingress.

Don't use an Ingress with the `<charm-name>-endpoints` service because it is a [headless service](https://kubernetes.io/docs/concepts/services-networking/service/#headless-services) and doesn't have a ClusterIP. Instead, use the other automatically-created service, `<charm-name>`.

- To expose the Pebble HTTP port, use [`ops.Unit.set_ports`](ops.Unit.set_ports) in your charm code:

```python
  self.unit.set_ports(38813)
```

- To create an Ingress, use the following example (assuming the charm and service name is `my-charm`):

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
