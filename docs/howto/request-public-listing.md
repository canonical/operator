(request-public-listing)=
# Make your charm discoverable

> See first: [](#charm-maturity)

Once your charm is ready for wide production use, get it publicly listed on [Charmhub](https://charmhub.io), so that it is visible in searches done by Juju users and other charm developers.

While anyone can upload a charm to Charmhub, before a charm is publicly listed it must pass through a lightweight review process. The goals of the review are:

1. Be transparent about the capabilities and qualities of a charm.
2. Ensure a common level of quality.

A listing review is **not** code review. The reviewer may be looking at some of the charm code, and may have comments on it, but the listing review is not a review of the architecture or design of the charm, and is not a line-by-line review of the charm code. Do architecture, design, and code review earlier in the charm development process -- reach out in the [Charm Development](https://matrix.to/#/#charmhub-charmdev:ubuntu.com) Matrix channel if you would like assistance.

## Steps of a review

The overall approach is straightforward:

1. The author requests a review for *one* charm at a time with all prerequisites using a [listing request issue](https://github.com/canonical/charmhub-listing-review/issues/new).
2. The reviewer checks if the prerequisites are met and the issue is ready.
3. The public review is carried out as a conversation on the issue.
4. The review concludes if the charm is 'publication ready', and if so the store team is notified to publicly list the charm.

The result of the process is that:
* if the review is successful, the charm is switched to listed mode, or
* if the review is unsuccessful, the charm does not reach the required criteria and the charm remains unlisted, until the issues are resolved.

## Review prerequisites

The listing request issue will prompt the author to provide information about the charm:

1. The name of the charm.
2. A URL to a Git source code repository.
3. Information for the reviewer to verify that the charm behaves as expected.
4. URLs for CI workflows and specific documentation.

Once your charm is close to review readiness, it's worth evaluating it yourself before requesting a review, to be confident in a positive result. To see the list of requirements and have some automatically checked, in the root of your charm folder in your repository run the command:

```bash
uvx --with=package-name something-or-other-here
```

## Criteria

The charm listing criteria consists of:

* A set of automated checks (for example: is there a license file?);
* A set of manual checks, which are shown in a checklist in the issue; and
* Reviewing the charm against current charming best practices, which are automatically collated from the charming ecosystem documentation and also included in a checklist in the issue.

With respect to test coverage of the charm, note that:

* Unit tests are recommended, but *not* required.
* A minimal set of integration tests is required, as outlined in the checklist.
* There is no minimum for test coverage. We suggest that tests cover at least all configuration options and actions, as well as the observed Juju events, but this is not a requirement for listing.
* Charms may have additional tests in an external location, particularly if the charm has specific resource requirements (such as specific hardware). If this is the case, please mention it in the review request, ideally providing some mechanism for viewing the tests and their results.

## Listing requirements

* The charm does what it is meant to do. If it is straightforward to deploy the charm and use the workload, then provide a tutorial that covers this. If the charm deployment is complex (for example, requires specialised hardware or an entire solution of charms), provide a video that demonstrates both deploying the charm and some example use of the workload.
* The charm's page on Charmhub provides a quality impression. This requires providing suitable metadata in `charmcraft.yaml` and reasonable documentation (more on documentation below).
* The charm has an icon, in the correct format.
* Some form of CI workflow exists that automatically releases the charm to an unstable channel on commits to the default branch.
* The charm has integration tests that run on every change to the default branch, and are passing. At minimum, the tests verify that the charm can be deployed and ends up in a success state, and that the charm can be integrated with at least one example for each 'provides' and 'requires' specified (including optional integrations, but excluding tracing) ending up in a success state. The tests should be run with `charmcraft test`.

A charm's documentation should focus on the charm itself. For workload-specific or Juju-related content, link to the appropriate upstream documentation. A smaller charm can have single-page documentation for its description. A bigger charm should include a full [Diátaxis](https://diataxis.fr) navigation tree. Ensure that the charm has documentation that covers:
* How to use the charm, including configuration, limitations, and deviations in behaviour from the 'non-charmed' version of the application.
* How to modify the charm
* A concise summary of the charm in the `charmcraft.yaml` 'summary' field, and a more detailed description in the `charmcraft.yaml` 'description' field.

The charm should follow documented [best practices](#best-practices).

The following checks are not required for listing, but are recommended for all charms.

* A user can deploy the charm with a sensible default configuration.
* The charm exposes provides / requires interfaces for integration ready to be adopted by the ecosystem.
* The charm upgrades the application safely, preserving data and settings, and minimising downtime.
* The charm supports scaling up and down, if the application permits or supports it.
* The charm supports backup and restore, if the application permits or supports it.
* The charm is integrated with observability, including metrics, alerting, and logging.
