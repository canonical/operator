---
myst:
  html_meta:
    description: Guidance for integrating your charm with common services, including ingress, observability, databases, TLS, object storage, and identity.
---

(set-up-production-integrations)=
# How to set up production integrations

See first: {ref}`charm-maturity`.

A production-ready charm should fit into the Juju ecosystem, integrating with other applications. Therefore, it needs to be compatible with other charms. This guide summarises the integrations that production charms most often support.

These integrations are not mandatory for your charm to work. You need to decide which ones to use based on your charm's workload.

```{tip}
If your charm uses a Charmcraft 12-factor app extension, many integrations are set up for you. Check {external+charmcraft:ref}`Charmcraft | Manage relations for a 12-factor app charm <integrate-12-factor-charms>` for more information. To add custom integrations to a 12-factor app charm, follow [Add a custom integration to a 12-factor app charm](https://canonical.com/juju/docs/12-factor/latest/how-to/add-custom-relation/) instead of this page.
```

(set-up-production-integrations-best-practices)=
## Best practices

Juju integrates endpoints that use the same interface name. You should use existing interface names for any integration that your charm supports. To browse the available interface names and their supporting libraries, see {external+charmlibs:ref}`Charmlibs | Interface libraries <charm-libs-interface>` and the {external+charmlibs:ref}`interface specifications <reference-interfaces>`.

Writing integration tests is the best way to validate that your charm can integrate well with others. See {ref}`How to manage relations | Write integration tests <manage-relations-integration-tests>`.

If no existing interface fits your workload, you can design a new one. See {ref}`manage-interfaces`.

(set-up-production-integrations-ingress)=
## Ingress

Integrate your charm with an ingress provider when your workload serves HTTP or HTTPS, and users or applications outside the model need to reach it. Your charm declares a `requires` endpoint that uses the `ingress` interface, and consumes the ingress data from the provider.

Some providers:

* [Traefik](https://charmhub.io/traefik-k8s), [NGINX Ingress Integrator](https://charmhub.io/nginx-ingress-integrator), and [Istio Ingress](https://charmhub.io/istio-ingress-k8s) on Kubernetes.
* [Ingress Configurator](https://charmhub.io/ingress-configurator) on machines. It translates `ingress` to the `haproxy-route` interface of the [HAProxy](https://charmhub.io/haproxy) charm.

In most cases, your charm can use the [ingress library](https://github.com/canonical/traefik-k8s-operator/blob/main/lib/charms/traefik_k8s/v2/ingress.py). You can use alternative libraries, as long as they fulfil the {external+charmlibs:ref}`ingress v2 interface specification <interfaces-ingress-v2>`.

See more: [Jenkins](https://github.com/canonical/jenkins-k8s-operator/blob/main/src/charm.py).

(set-up-production-integrations-observability)=
## Observability

Integrate your charm with the [Canonical Observability Stack (COS)](https://documentation.ubuntu.com/observability/) to provide metrics, logs, alerts, and dashboards for your workload in production. Most charms with a workload need it. A charm that doesn't run a workload, such as an integrator charm, might not.

To integrate your charm with COS:

* On Kubernetes, your charm integrates with each COS component over its own interface. Declare a `provides` endpoint for each of `prometheus_scrape` (Prometheus) and `grafana_dashboard` (Grafana), and a `requires` endpoint for `loki_push_api` (Loki). See {ref}`Observe your charm with COS Lite tutorial <observe-your-charm-with-cos-lite>`. To trace your charm code and send the trace data to COS, see {ref}`trace-your-charm`.
* On machines, your charm declares a single `provides` endpoint that uses the `cos_agent` interface. Use the [`cos_agent` charm library](https://charmhub.io/grafana-agent/libraries/cos_agent) to implement it. The [OpenTelemetry Collector](https://charmhub.io/opentelemetry-collector) subordinate charm forwards everything to COS. See more: [COS | Instrument machine charms](https://documentation.ubuntu.com/observability/latest/how-to/integrate/instrument-machine-charms/).

See more: [Hydra](https://github.com/canonical/hydra-operator/blob/main/src/charm.py), [Valkey](https://github.com/canonical/valkey-operator/blob/9/edge/src/events/observability.py).

(set-up-production-integrations-databases)=
## Databases

Charms often need to connect to a database. Your charm declares a `requires` endpoint that uses the interface for your database. Each database technology has its own interface:

| Database | Interface | Provider charms |
|:--|:--|:--|
| PostgreSQL | `postgresql_client` | [`postgresql`](https://charmhub.io/postgresql), [`postgresql-k8s`](https://charmhub.io/postgresql-k8s) |
| MySQL | `mysql_client` | [`mysql`](https://charmhub.io/mysql), [`mysql-k8s`](https://charmhub.io/mysql-k8s) |
| MongoDB | `mongodb_client` | [`mongodb`](https://charmhub.io/mongodb), [`mongodb-k8s`](https://charmhub.io/mongodb-k8s) |

The [`dpcharmlibs-interfaces`](https://github.com/canonical/data-platform-charmlibs/blob/main/interfaces/README.md) library covers all of these interfaces. New charms should use this library. Some existing charms still use the older `data_platform_libs.v0.data_interfaces` charm library.

See more: [MediaWiki](https://github.com/canonical/mediawiki-k8s-operator/blob/main/src/relations/valkey.py) uses `dpcharmlibs-interfaces` for its Valkey relation (interface `valkey_client`). [Discourse](https://github.com/canonical/discourse-k8s-operator/blob/main/src/database.py) requires `postgresql_client` and [MediaWiki](https://github.com/canonical/mediawiki-k8s-operator/blob/main/src/relations/database.py) requires `mysql_client`, but both still use the older v0 library for these.

(set-up-production-integrations-tls)=
## TLS certificates

Integrate your charm with a certificate provider when your workload needs TLS certificates, for example to serve or query from HTTPS endpoints. Your charm declares a `requires` endpoint that uses the `tls-certificates` interface and receives certificates from the provider.

Some providers:

* [Self Signed Certificates](https://charmhub.io/self-signed-certificates)
* [Lego](https://charmhub.io/lego)
* [Manual TLS Certificates](https://charmhub.io/manual-tls-certificates)
* [Vault](https://charmhub.io/vault-k8s)

New charms should use the {external+charmlibs:ref}`charmlibs-interfaces-tls-certificates <charmlibs-interfaces-tls-certificates>` library. See also the {external+charmlibs:ref}`tls-certificates v1 interface specification <interfaces-tls-certificates-v1>`. Some existing charms still use the older `charms.tls_certificates_interface` charm library.

See more: [NGINX Ingress Integrator](https://github.com/canonical/nginx-ingress-integrator-operator/blob/main/src/charm.py), [Landscape](https://github.com/canonical/landscape-charm/blob/main/src/charm.py).

(set-up-production-integrations-object-storage)=
## Object storage

Integrate your charm with an object storage provider when your workload needs S3-compatible storage. Your charm declares a `requires` endpoint that uses the `s3` interface, and receives the endpoint, bucket, and credentials from the provider.

The main provider is [S3 Integrator](https://github.com/canonical/object-storage-integrator/blob/main/s3/README.md), which you configure with the details of an S3-compatible service. Its documentation explains how to set it up and which charm library to use.

See more: [MLflow](https://github.com/canonical/mlflow-operator/blob/main/src/charm.py), [Valkey](https://github.com/canonical/valkey-operator/blob/9/edge/src/events/backup.py).

(set-up-production-integrations-identity)=
## Identity

Use the [Canonical Identity Stack](https://canonical-identity.readthedocs-hosted.com/) for identity and access management of your charm. To compare the available solutions, see [Choosing an identity solution](https://canonical-identity.readthedocs-hosted.com/choosing-an-identity-solution/). Your charm declares a `requires` endpoint that uses the interface for the protocol that your workload supports:

| Protocol | Interface | Provider charms | Library |
|:--|:--|:--|:--|
| OAuth 2.0 and OpenID Connect (OIDC) | `oauth` | [`hydra`](https://canonical-identity.readthedocs-hosted.com/identity-platform/how-to/onboard-an-application-with-charmed-hydra/), [`authentik-server`](https://canonical-identity.readthedocs-hosted.com/authentik/how-to/protect-oidc-applications/) | {external+charmlibs:ref}`charmlibs-interfaces-oauth <charmlibs-interfaces-oauth>` |
| LDAP | `ldap` | [`glauth-k8s`](https://canonical-identity.readthedocs-hosted.com/identity-platform/tutorial/charms/glauth/), [`authentik-ldap-outpost`](https://canonical-identity.readthedocs-hosted.com/authentik/how-to/protect-ldap-applications/) | {external+charmlibs:ref}`charmlibs-interfaces-ldap <charmlibs-interfaces-ldap>` |
| SAML | `saml` | [`saml-integrator`](https://charmhub.io/saml-integrator) | [`saml` charm library](https://charmhub.io/saml-integrator/libraries/saml) |

See more: [SSSD](https://github.com/canonical/sssd-operator/blob/main/src/integrations/ldap.py) uses the LDAP library, and [Discourse](https://github.com/canonical/discourse-k8s-operator/blob/main/src/charm.py) uses the SAML library.
