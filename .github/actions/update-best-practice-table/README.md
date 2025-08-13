# Update best practices documentation

## GitHub Actions Usage

This action will regenerate the [best practices doc](../../../docs/reference/best-practices.md) by
scraping the operator and charmcraft repository `docs` folders. If there are changes, then the
action will open a pull request to have those changes added to the main branch.

## Local Usage

You'll need a clone of the `operator` repository (presumably the one you're running this command
from), and also the [canonical/charmcraft](https://github.com/canonical/charmcraft) repository,
ideally checked out to the branch that is used for the `stable` version of the Charmcraft docs.

```command
python3 .github/actions/update-best-practice-table/main.py --path-to-ops=. --path-to-charmcraft=../charmcraft > docs/reference/best-practices.md

# Check the modifications in the current branch.
git diff
```
