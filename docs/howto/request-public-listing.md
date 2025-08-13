(request-public-listing)=
# How to request public listing on charmhub.io?

**TODO: this is mostly just a copy of the repo README, need to convert to a proper how-to.**

Reviewing charms encourages the involvement of the community. The community refers to individuals and organisations creating or contributing to charms, Juju and the wider charming ecosystem. The goals of the review are:

1. Be transparent about the capabilities and qualities of a charm.
2. Ensure a common level of quality.

A listing review is *not* code review. The reviewer may be looking at some of the charm code, and may have comments on it, but the listing review is not a review of the architecture or design of the charm, and is not a line-by-line review of the charm code.

## Key considerations

1. The process is streamlined: The party requesting the review provides structured evidence as input to the review process.
2. A review is transparent for the community. Review and the review comments are public.
3. Everyone can participate in the review, for example, participate in a discussion in a GitHub issue. A review may benefit from the expertise of a reviewer in the relevant field. Thus, the review process is flexible and open to involving multiple persons.
4. The review covers the effective automation of tests for automated approvals of subsequent releases.

## Steps of a review

The specification provides details and summaries of how the review works. However, the overall approach is straightforward:

1. The author requests a review for *one* charm at a time with all prerequisites using a [listing request issue](https://github.com/canonical/charmhub-listing-review/issues/new) in this repository.
2. The reviewer checks if the prerequisites are met and the pull request is ready.
3. The public review is carried out as a conversation on the pull request.
4. The review concludes if the charm is 'publication ready'.
5. If the review is at least 'publication-ready', the store team is asked to list the charm.

The result of the process is that:
* if the review is successful, the charm is switched to listed mode, or
* if the review is unsuccessful, the charm does not reach the required criteria and the charm remains unlisted, until the issues are resolved.

## Roles and concepts

|Role or item|Description|
| --- | --- |
|Author|Author of the charm or person representing the organisation. The person submitting the charm for review is called the author in this document.|
|Publisher|The responsible person or organisation for publishing the charm.|
|Review group|A group of contact persons watching for review requests to arrive and requesting modifications or assigning a review to a suitable reviewer. This is currently the Canonical Charm Tech team.|
|Reviewer|Person conducting the review.|
|Listing|After the reviewer has reviewed the charm successfully, it can be switched to 'listing'. Listing means that the charm will be part of the search result when querying the Web pages and API of Charmhub.io. Without 'listing', the charm will be available under its URL but is not listed in searches.|

The charm listing criteria consists of:

* A set of automated checks (for example: is there a license file?)
* A set of manual checks, which are shown in a checklist in the issue
* Reviewing the charm against current charming best practices, which are automatically collated from the charming ecosystem documentation and also included in a checklist in the issue

## Review prerequisites

The process has the following prerequisites to be delivered by the author. The issue template for a listing request will prompt the author for this information:

1. The charm source code is accessible for reviewers and an URL to a (git) source code repository is available.
2. Information for the reviewer to verify that the charm behaves as expected - in simple cases, a tutorial is a good method for this. In more complex cases, and particularly when specific resources are required, a demo call or video is a better choice.
3. URLs for CI workflows and specific documentation.
4. Publisher details.

# Criteria

With respect to test coverage of the charm, note that:

* Unit tests are recommended, but *not* required.
* A minimal set of integration tests is required, as outlined in the checklist.
* There is no minimum for test coverage. We suggest that tests cover at least all configuration options and actions, as well as the observed Juju events, but this is not a requirement for listing.
* Some charms may have additional tests in an external location, particularly if the charm has specific resource requirements (such as specific hardware).

## Listing requirements

* The charm does what it is meant to do, per the demo or tutorial.
* The charm's page on Charmhub provides a quality impression. The overall appearance looks good and the documentation looks reasonable.
* The charm has an icon.
* Automated releasing to unstable channels exists
* Integration tests exist, are run on every change to the default branch, and are passing. At minimum, the tests verify that the charm can be deployed and ends up in a success state, and that the charm can be integrated with at least one example for each 'provides' and 'requires' specified (including optional, excluding tracing) ending up in a success state. The tests should be run with `charmcraft test`

A charm's documentation should focus on the charm itself. For workload-specific or Juju-related content, link to the appropriate upstream documentation. A smaller charm can have single-page documentation for its description. A bigger charm should include a full Diátaxis navigation tree. Check that the charm has documentation that covers:
* How to use the charm, including configuration, limitations, and deviations in behaviour from the “non-charmed” version of the application.
* How to modify the charm
* A concise summary of the charm in the `charmcraft.yaml` 'summary' field, and a more detailed description in the `charmcraft.yaml` 'description' field.

The charm should follow the documented [best practices](#charm-maturity).

The following checks are not required for listing, but are recommended for all charms.

* A user can deploy the charm with a sensible default configuration.
* The charm exposes provides / requires interfaces for integration ready to be adopted by the ecosystem.
* The charm upgrades the application safely, preserving data and settings, and minimising downtime.
* The charm supports scaling up and down, if the application permits or supports it.
* The charm supports backup and restore, if the application permits or supports it.
* The charm is integrated with observability, including metrics, alerting, and logging.

# Get started

If you'd like to see the list of requirements and have some automatically checked, you can run the command:

```bash
uvx --with=package-name something-or-other-here
```

If the charm is ready for review, [open an issue in this repository](https://github.com/canonical/charmhub-listing-review/issues/new).
