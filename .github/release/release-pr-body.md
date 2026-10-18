<!--
The propose-release workflow fills this in as the description of the
version-bump pull request. The markers are how the create-draft-release
workflow lifts the title's summary and the notes back out of the description
when it creates the draft release, so anything written outside them is for
reviewers and goes no further. They are HTML comments, which a reader of the
pull request doesn't see, so each pair also gets a visible heading just
outside it.
-->
Prepares the ${version} release from `${branch}`.

* `CHANGES.md` has a new entry for ${version}.
* The version strings are updated across ops, ops-scenario, ops-tracing and the tool-versions table.
* [Commits since ${previous}](${repo_url}/compare/${previous}...${branch})

The GitHub release is titled `${version}: ` followed by the summary under "Release title", and its body is the notes under "Release notes". Edit both here: this description is where they are read from. Each is wrapped in hidden markers, which you will see when you edit; keep them.

Once this is merged, run [Create the draft release](${repo_url}/actions/workflows/create-draft-release.yaml) with this pull request's number.

## Release title

<!-- release-title:start -->

${title}
<!-- release-title:end -->

## Release notes

<!-- release-notes:start -->

${notes}
<!-- release-notes:end -->
