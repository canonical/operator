(charm-maturity)=
# Charm maturity

Like all software, charms continually evolve and should increase in maturity and quality over time. There are four major stages of charm maturity, which correlate with the availability of the charm.

## Phase 1: Early development and private deployment

Anyone can pack a charm from source and deploy it by passing the `.charm` file to `juju deploy`. This is frequently done during development and testing, but can also be used for private charms.

> See more: {external+juju:ref}`Juju | How to manage applications | Deploy an application <deploy-an-application>`

## Phase 2: Private listing on Charmhub

Anyone can publish a charm to Charmhub (you'll need to create an account, and there are some restrictions on charm names). Once this is done, anyone can see the Charmhub page for the charm, or deploy from Charmhub, as long as they know the charm name.

Privately-listed charms will not show up in searches on Charmhub, or general web searches.

> See more: {external+charmcraft:ref}`Charmcraft | How to manage charms | Public a charm <publish-a-charm>`

## Phase 3: Public listing on Charmhub

When an author is satisfied that the charm is suitable for wider production use, they can request public Charmhub listing. The charm will be lightly reviewed to ensure that it does what it says that it does and has suitable documentation & metadata. The review also covers the effective automation of tests for automated approvals of subsequent releases.

After passing review, the charm will show up in searches on Charmhub, and web searches leading to Charmhub.

> See more: [How to request Charmhub public listing](#make-your-charm-discoverable)

Reviewing charms encourages the involvement of the community. 'Community' refers to individuals and organisations creating or contributing to charms, Juju and the wider charming ecosystem. Reviews take place in public GitHub issues so that anyone from the community can participate.

### Roles

| Role | Description |
|------|-------------|
| Author | Author of the charm or person representing the organisation. The person submitting the charm for review is called the author in this documentation. |
| Publisher | The responsible person or organisation for publishing the charm. |
| Review group | A group of people who watch for review requests, then request changes or assign a suitable reviewer. This is currently the Canonical Charm Tech team. |
| Reviewer | Person conducting the review. |

## Phase 4: Ongoing maintenance and evolution

Public listing is not the end of a charm's growth. Truly mature charms offer more integration across the charming ecosystem and are most likely to get wide adoption. This section explains some standards that Juju users expect.

### The charm has sensible defaults

A user can deploy the charm with a sensible default configuration. Optimised deployments will require configuration, but a charm should be opinionated and start out with reasonable defaults.

For example, if the workload requires initial passwords to be set, auto-generate them and provide them to the Juju user. You could implement an action or a secret.

Sometimes, it's not possible to set a sensible default. For example, a host name or a load balancer address. Cover these in the charm's documentation and indicate clearly in status messages when they aren't set and how the user should fix that.

### The charm is compatible with the ecosystem

Submit any newly-proposed public interfaces for review, to ensure that:

- The interface is ready for adoption by other charmers. In most cases this will mean providing a library to help other charms provide or require a relation using the interface.
- There are no conflicts with existing interfaces of published charms.
- Interface names and structure are consistent with the charming ecosystem.
- Tests cover integration with the applications consuming or providing the relations.

> See more: [Charmlibs documentation](https://documentation.ubuntu.com/charmlibs/)

### The charm respects the Juju proxy options

`juju-http-proxy`, `juju-https-proxy`, and `juju-no-proxy` should influence the charm's behavior when the charm or charm workload makes any HTTP request.

For the corresponding environment variables that the charm should read, see {external+juju:ref}`Juju | List of model configuration keys <list-of-model-configuration-keys>`

### The charm upgrades the application safely

The charm supports upgrading the workload and the application. An upgrade task preserves data and settings of both.

### The charm supports scaling up and down

If the workload supports scaling, the charm can be scaled up or down. Scale-up and scale-down may change the number of deployed units and the allocated resources (such as storage or computing).

### The charm is integrated with observability

Use the [Canonical Observability Stack (COS)](https://documentation.ubuntu.com/observability/) for covering observability in charms.
