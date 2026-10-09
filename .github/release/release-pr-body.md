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

## Next steps

This pull request starts as a draft, for whoever ran the workflow to tidy up before anyone else looks at it.

1. Edit the release title and notes below. A model drafted them: resolve every **Unsure:** note, and cut anything a reader doesn't need. Fix the changelog entry in `CHANGES.md` too, if it needs it.
2. Mark the pull request ready for review, and ask for a review.
3. Close and reopen the pull request so that the checks run (it was opened with the workflow's own token, so they don't start by themselves).
4. Once it's approved and the checks pass, merge it.
5. Run [Create the draft release](${repo_url}/actions/workflows/create-draft-release.yaml) with **@PR_NUMBER@** as the pull request number. It creates the draft release and opens the pull request that moves `${branch}` back to a development version.
6. Read the draft release, then publish it. ${latest_advice} Publishing creates the tag and uploads to PyPI.

The [contributing guide](${repo_url}/blob/main/CONTRIBUTING.md#publishing-a-release) has the details, and what's left to do by hand after publishing.

## Release title

<!-- release-title:start -->

${title}
<!-- release-title:end -->

## Release notes

<!-- release-notes:start -->

${notes}
<!-- release-notes:end -->
