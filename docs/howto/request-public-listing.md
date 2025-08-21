(request-public-listing)=
# Make your charm discoverable

> See first: [Charm maturity](#charm-maturity)

Once your charm is ready for wide production use, get it publicly listed on [Charmhub](https://charmhub.io), so that it is visible in searches done by Juju users and other charm developers.

Anyone can upload a charm to Charmhub, which allows deploying the charm and viewing its information on Charmhub if you know the name of the charm. To have a charm publicly listed, meaning it will be found in searches on Charmhub and general web searches leading to Charmhub, it must pass through a lightweight review process. The goals of the review are:

1. Be transparent about the capabilities and qualities of a charm.
2. Ensure a common level of quality.

```{caution}
A listing review is **not** code review. The reviewer may be looking at some of the charm code, and may have comments on it, but the listing review is not a review of the architecture or design of the charm, and is not a line-by-line review of the charm code. Do architecture, design, and code review earlier in the charm development process -- reach out in the [Charm Development](https://matrix.to/#/#charmhub-charmdev:ubuntu.com) Matrix channel if you would like assistance.
```

## Self-evaluate your charm against the public listing criteria

Carry out your own review of your charm and its metadata. In particular, make sure that:

* The charm does what it is meant to do. If it is straightforward to deploy the charm and use the workload, then ensure there is a tutorial that covers this. If the charm deployment is complex (for example, requires specialised hardware or an entire solution of charms), create a video that demonstrates both deploying the charm and some example use of the workload.
* The charm's page on Charmhub provides a quality impression. This requires providing suitable metadata in `charmcraft.yaml` and reasonable documentation (more on documentation below).
* The charm has an icon, in the correct format.
* Some form of CI workflow exists that automatically releases the charm to an unstable channel on commits to the default branch.
* The charm has integration tests that run on every change to the default branch, and are passing. At minimum, the tests verify that the charm can be deployed and ends up in a success state, and that the charm can be integrated with at least one example for each 'provides' and 'requires' specified (including optional integrations, but excluding tracing) ending up in a success state. The tests should be run with `charmcraft test`.

With respect to test coverage of the charm, note that:

* Unit tests are recommended, but *not* required.
* A minimal set of integration tests is required, as outlined in the checklist.
* There is no minimum for test coverage. We suggest that tests cover at least all configuration options and actions, as well as the observed Juju events, but this is not a requirement for listing.
* Charms may have additional tests in an external location, particularly if the charm has specific resource requirements (such as specific hardware). If this is the case, please mention it in the review request, ideally providing some mechanism for viewing the tests and their results.

Ensure your charm's documentation focuses on the charm itself. For workload-specific or Juju-related content, link to the appropriate upstream documentation. A smaller charm can have single-page documentation for its description. A bigger charm should include a full [Diátaxis](https://diataxis.fr) navigation tree. Ensure that the charm has documentation that covers:
* How to use the charm, including configuration, limitations, and deviations in behaviour from the 'non-charmed' version of the application.
* How to modify the charm
* A concise summary of the charm in the `charmcraft.yaml` 'summary' field, and a more detailed description in the `charmcraft.yaml` 'description' field.

The charm should follow documented [best practices](#best-practices).

## Review prerequisites

Once your charm is close to review readiness, it's worth evaluating it yourself before requesting a review, to be confident in a positive result. To see the list of requirements and have some automatically checked, in the root of your charm folder in your repository run the command:

```bash
uvx --with=package-name something-or-other-here
```

This will provide you with information about the full listing criteria, and, for those that can be checked automatically, whether the charm currently passes.

## Request a review

```{note}
Each review covers exactly one charm. If your charm is designed to only work with other charms in a solution, open multiple review requests and note in them that they are connected.
```

### Open an issue

Open a [listing request issue](https://github.com/canonical/charmhub-listing-review/issues/new). You will be asked for some basic information:

1. The name of the charm.
2. A URL to a Git source code repository.
3. Information for the reviewer to verify that the charm behaves as expected.
4. URLs for CI workflows and specific documentation.

Creating your issue will trigger automation that will assign the review to a team, and add a comment that explains the review process and includes a checklist of the review criteria.

```{tip}
Avoid editing the issue description. The automation uses the data in the description to perform automated checks, which speeds up the review process. If you need to provide additional information to the reviewer, or want to respond to review comments, add a new comment on this issue.
```

You should see that some of the items in the checklist are already ticked - these are ones that the system is able to check automatically. Congratulations - you're part of the way through the review already!

Over the next few days, the reviewer will check the remaining items, and post the results as a new comment on the issue. GitHub subscribed you to the issue when you created it, so you'll receive notifications when there is new activity.

## Address any remaining issues

If there are items in the checklist that are not yet ticked, address those through conversations with the reviewer in issue comments, and by making adjustments to the charm metadata and code. Once there are no items left to resolve, the review is complete, and the store team will be automatically notified that the charm should be listed publicly. This typically happens within a day or two.
