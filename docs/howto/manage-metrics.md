# How to Manage Metrics

Pebble provides services and health check [metrics](https://documentation.ubuntu.com/pebble/reference/api/#/metrics/get_v1_metrics) in OpenMetrics format. Access this endpoint requires HTTP basic authentication with a "basic" type [identity](https://documentation.ubuntu.com/pebble/reference/identities/).

## Create a "basic" type identity

To create an identity in Pebble, use the [`pebble.Client.replace_identities`](ops.pebble.Client.replace_identities) method:

```python
from passlib.hash import sha512_crypt

class MyCharm(ops.CharmBase):
  def _replace_identities(self, username: str, password: str) -> None:
    identities = {
      username: ops.pebble.Identity(
        access="metrics", basic=ops.pebble.BasicIdentity(password=sha512_crypt.hash(password))
      ),
    }
    self.container.pebble.replace_identities(identities)
    logger.debug("New metrics username: %s", username)
```

Hash the password using `sha512-crypt`. Import `sha512_crypt` from `passlib.hash` and generate the hash with `sha512_crypt.hash()`.

## Create a Juju user secret

Use {external+juju:ref}`Juju secret <secret>` to manage sensitive information like HTTP basic authentication credentials. Run the following command to create a Juju user secret:

```bash
juju add-secret metrics-user-password username=test password=test
```

For more details, see:

- {external+juju:ref}`juju add-secret <command-juju-add-secret>`.

## Pass the secret ID to the charm via configurations

The `juju add-secret` command returns the secret ID. Pass this ID to the charm using configurations. For example, define an option named `metrics-secret-id` in `charmcraft.yaml`:

```yaml
config:
  options:
    metrics-secret-id:
      default: <your-secret-id-here>
      description: Default secret ID for the metrics username and password
      type: string
```

On the `config-changed` event, retrieve the secret content and use it to create a "basic" type identity:

```python
  def _on_config_changed(self, event: ops.ConfigChangedEvent) -> None:
    secret_id = str(self.config["metrics-secret-id"])
    secret = self.model.get_secret(id=secret_id)
    content = secret.get_content()
    username, password = content["username"], content["password"]
    self._replace_identities(username, password)
```

For more configuration details, see:

- {ref}`make-your-charm-configurable`
- {ref}`manage-configurations`.

Observe the `secret-changed` event to handle updates:

```python
  def _on_secret_changed(self, event: ops.SecretChangedEvent) -> None:
    content = event.secret.peek_content()
    username, password = content["username"], content["password"]
    self._replace_identities(username, password)
```

For more information on secrets, see {ref}`manage-secrets`.

## Grant access to the user secret

After deploying the charm, grant access to the user secret:

```bash
juju grant-secret metrics-user-password <charm-name>
```

For more details, see: {external+juju:ref}`juju grant-secret <command-juju-grant-secret>`.

## Access the metrics endpoint

### Within the same Kubernetes cluster

A Kubernetes service `<charm-name>-endpoints` is created by default, and the first workload container's Pebble HTTP port is `38813`.

For example, if the charm is named `my-charm` and deployed in the namespace `test`, access the metrics endpoint with HTTP basic authentication at `my-charm-endpoints.test.svc.cluster.local:38813/v1/metrics`.

Read more about service discovery within a Kubernetes cluster [here](https://kubernetes.io/docs/concepts/services-networking/dns-pod-service/).

### Via an Ingress

To expose the service externally, use an Ingress.

We should not use an Ingress with the `<charm-name>-endpoints` service because it is a [headless service](https://kubernetes.io/docs/concepts/services-networking/service/#headless-services) and doesn't have a ClusterIP.

We will use the other automatically created service `<charm-name>` instead, and expose the Pebble HTTP port on it with the following code:

```python
  self.unit.set_ports(38813)
```

Create an Ingress (assuming the charm and service name is "my-charm"):

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
