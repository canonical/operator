(manage-the-charm-version)=
# How to manage the charm version

## Implement the feature

Charms can specify a version of the charm itself, so that a Juju admin can track
the installed version of the charm back to the source tree that it was built
from.

To set the version, in the root directory of your charm (at the same level as
the `charmcraft.yaml` file) add a file called `version` (no extension). The
content of the file is the version string, which is typically a
major.minor.patch style version that's manually updated, or a version control
hash identifier.

For example, using the hash of the latest HEAD commit as the version:

```shell
$ git rev-parse HEAD > version
$ ls
lib      src    tox.ini charmcraft.yaml  LICENSE  requirements.txt  tests  version
$ cat version
0522e1fd009dac78adb3d0652d91a1e8ff7982ae
```

Typically, your publishing or packing workflow takes care of updating this file, so
that it will automatically match the revision that you're creating and publishing.
Generally, using a version control revision is the best choice, as it unambiguously
identifies the code that was used to build the charm.

One way to achieve this is to modify your `charmcraft.yaml` file to include a parts build
override, such as:

```yaml
parts:
  charm:
    source: .
    plugin: uv
    build-packages: [git]
    build-snaps: [astral-uv]
    override-build: |
      craftctl default  # Run the default build steps.
      git describe --always > $CRAFT_PART_INSTALL/version
```

Juju admins using your charm can find this information with `juju status` in the
YAML or JSON formats in the `applications.<app name>.charm-version` field. If
there is no version, the key will not be present in the status output.

Note that this is distinct from the charm **revision**, which is set when
uploading a charm to CharmHub (or when deploying/refreshing for local charms).

> Examples: [`container-log-archive-charm` sets `version` to a version control hash](https://git.launchpad.net/container-log-archive-charm/tree/)

## Test the feature

Since the version isn't set by the charm code itself, you may want to test that
the version is correctly set with an integration test, and don't need to write
a unit test.

> See first: {ref}`write-integration-tests-for-a-charm`

To verify that setting the charm version works correctly in an integration test,
in your `tests/integration/test_charm.py` file, add a new test:

```py
def test_charm_version_is_set(juju: jubilant.Juju):
    """Verify that the charm version has been set."""
    version = juju.status().apps["your-app"].charm_version
    expected_version = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode("utf8")
    assert version == expected_version
```
