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

## Publicly listed charms

Reviewing charms encourages the involvement of the community. The community refers to individuals and organisations creating or contributing to charms, Juju and the wider charming ecosystem.

### Key considerations

The process for making a charm discoverable on Charmhub involves a light review of the charm and its metadata. The goals of that process include:

1. The process is streamlined: The party requesting the review provides structured evidence as input to the review process.
2. A review is transparent for the community. Review and the review comments are public.
3. Everyone can participate in the review, for example, participate in a discussion in a GitHub issue. A review may benefit from the expertise of a reviewer in the relevant field. Thus, the review process is flexible and open to involving multiple persons.
4. The review covers the effective automation of tests for automated approvals of subsequent releases.

### Roles and concepts

|Role or item|Description|
| --- | --- |
|Author|Author of the charm or person representing the organisation. The person submitting the charm for review is called the author in this documentation.|
|Publisher|The responsible person or organisation for publishing the charm.|
|Review group|A group of contact persons watching for review requests to arrive and requesting modifications or assigning a review to a suitable reviewer. This is currently the Canonical Charm Tech team.|
|Reviewer|Person conducting the review.|
|Listing|After the reviewer has reviewed the charm successfully, it can be switched to 'listing'. Listing means that the charm will be part of the search result when querying the web pages and API of Charmhub.io, and is in the Charmhub sitemap (so will be found by third-party search engines). Without 'listing', the charm will be available under its URL but is not listed in searches.|

## Signs of mature charms

Once your charm is discoverable, you'll want to continue working on it to get it to be a noteworthy addition to the charming ecosystem. Exactly what that entails will depend on the workload being charmed, but there are some specific standards that Juju users are looking for.

### The charm has sensible defaults

A user can deploy the charm with a sensible default configuration. Optimised deployments will require configurations, but a charm should be opinionated and start out with reasonable defaults, and without the Juju user needing to specify configuration in deploy, whenever possible.

For example, if the workload requires initial passwords to be set, auto-generate them and provide them to the Juju user via an action or secret. Host names and load balancer addresses are examples that often cannot be set with a sensible default: cover these in the documentation and indicate clearly in the status messages when they are not set and how the user should fix that.

### The charm is compatible with the ecosystem

TODO: Likely this whole section gets lifted out into James's documentation.

Ensure that newly proposed public interfaces have been reviewed and approved to ensure:

- The interface is ready for adoption by other charmers. In most cases this will mean providing a library to help other charms provide or require a relation using the interface.
- There are no conflicts with existing interfaces of published charms.
- Interface names and structure are consistent with the charming ecosystem.
- Tests cover integration with the applications consuming or providing the relations.

> See more:
>  - [charmlibs](https://documentation.ubuntu.com/charmlibs/)

### The charm respects `juju model-config`

Avoid duplicating configuration options that are best controlled at a model level:

- `juju-http-proxy`, `juju-https-proxy`, and `juju-no-proxy` should influence the charm's behavior when the charm or charm workload makes any HTTP request.

### The charm upgrades the application safely

The charm supports upgrading the workload and the application. An upgrade task preserves data and settings of both.

```{tip}
Support upgrades sequentially, so that users of the charm can regularly apply upgrades in the sequence of released revisions.
```

### The charm supports scaling up and down

If the application permits or supports it, the charm does not only scale up but also supports scaling down. Scale-up and scale-down can involve the number of deployment units and the allocated resources (such as storage or computing).

### The charm is integrated with observability

Use the [Canonical Observability Stack (COS)](https://documentation.ubuntu.com/observability/) for covering observability in charms.
