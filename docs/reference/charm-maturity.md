(charm-maturity)=
# Charm maturity

Like all software, charms continually evolve and should increase in maturity and quality over time. There are four major stages of charm maturity, which correlate with the availability of the charm:

1. **Early development and local deployment**. Anyone can pack a charm and `juju deploy` it passing in the `.charm` file. This is frequently done during development, but can also be used for private charms.
2. **Private listing on Charmhub**. Anyone can publish a charm to Charmhub (you'll need to create an account, and there are some restrictions on charm names). Once this is done, anyone can see the Charmhub page for the charm, or deploy from Charmhub, as long as they know the charm name. *These charms will not show up in searches on Charmhub, or general web searches*.
3. **Discoverable**. When an author is satisfied that the charm is suitable for wider production use, they can request public Charmhub listing. The charm will be lightly reviewed to ensure that it does what it says that it does, has suitable documentation, infrastructure and metadata, and so forth. After passing review, the charm will show up in searches on Charmhub.
4. **Ongoing improvement**. Public listing is not the end of a charm's growth. Truly mature charms offer more integration across the charming ecosystem (ingress, observability, identity, ...), gracefully handle scaling up and down, and more. These noteworthy charms are most likely to get wide adoption, and be featured in editorial content in the charming world.

> See more:
>  - {external+juju:ref}`How to manage applications | Deploy an application <deploy-an-application>`
>  - {external+charmcraft:ref}`How to manage charms | Public a charm <publish-a-charm>`
>  - [How to request Charmhub public listing](#request-public-listing)

## Best practices

Best practices for charm development and maintenance can be found across the charming ecosystem documentation. Those practices are summarised here for convenience, but we encourage reading the how-to guides and reference documentation whenever you are working on your charm to understand the full context of the best practice.

```{include} best-practices.md
```

## Signs of mature charms

Your charm looks right, right enough for you to share it with the world. What next? Time to make sure it also works right! This document spells out the second round of standards that you should try to meet – standards designed to ensure that your charm is good enough to be used in production, at least for some use cases.

### The charm has sensible defaults

A user can deploy the charm with a sensible default configuration.

The purpose is to provide a fast and reliable entry point for evaluation. Of course, optimised deployments will require configurations. Often applications require initial passwords to be set, which should be auto-generated and retrievable using an action or secrets. Hostnames and load balancer addresses are examples that often cannot be set with a sensible default. But they should be covered in the documentation and indicated clearly in the status messages on deployment when not properly set.

### The charm is compatible with the ecosystem

The charm can expose provides/requires interfaces for integration ready to be adopted by the ecosystem.

Newly proposed relations have been reviewed and approved by experts to ensure:

- The relation is ready for adoption by other charmers from a development best practice point of view.
- No conflicts with existing relations of published charms.
- Relation naming and structuring are consistent with existing relations.
- Tests cover integration with the applications consuming the relations.

A Github project structures and defines the implementation of relations.

No new relation should conflict with the ones covered by the relation integration set published on Github .

### The charm respects juju model-config

Most developers are keenly aware of their own charm’s configs, without being aware that juju model-config is another point of administrative control.

Avoid duplicating configuration options that are best controlled at a model level:

- juju-http-proxy, juju-https-proxy, juju-no-proxy should influence the charm’s behavior when the charm or charm workload makes any HTTP request.

A Github project provides a library to help charms direct url requests and subprocess calls through the model-configured proxy environment.

### The charm upgrades the application safely

The charm supports upgrading the workload and the application. An upgrade task preserves data and settings of both.

A best practice is to support upgrades sequentially, meaning that users of the charm can regularly apply upgrades in the sequence of released revisions.

### The charm supports scaling up and down

If the application permits or supports it, the charm does not only scale up but also supports scaling down. Scale-up and scale-down can involve the number of deployment units and the allocated resources (such as storage or computing).

### The charm is integrated with observability

Engineers and administrators who operate an application at a production-grade level need to capture and interpret the application’s state.

Integrating observability refers to providing:

- a metrics endpoint,
- alert rules,
- Grafana dashboards, and
- integration with a log sink (e.g. Loki ).

Consider the Canonical Observability Stack  (COS) for covering observability in charms. Several endpoints are available from the COS to integrate with charms:

- Provide metrics endpoints using the MetricsProviderEndpoint
- Provide alert rules to Prometheus
- Provide dashboards using the GrafanaDashboardProvider
- Require a logging endpoint using the LogProxyConsumer or LokiPushApiConsumer
