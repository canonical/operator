(pytest-operator)=
# `pytest-operator`

`pytest-operator` is a Python library that provides Juju plugins for the generic Python library `pytest` to facilitate the {ref}`integration testing <integration-testing>` of charms.

> See more: [`pytest-operator`](https://github.com/charmed-kubernetes/pytest-operator)

It builds a fixture called `ops_test` that helps you interact with Juju through constructs that wrap around [`python-libjuju` ](https://pypi.org/project/juju/).

> See more: 
> - [`pytest-operator` > `ops_test`](https://github.com/charmed-kubernetes/pytest-operator/blob/main/docs/reference.md#ops_test) 
> - [`pytest` > Fixtures](https://docs.pytest.org/en/6.2.x/fixture.html)

It also provides convenient markers and command line parameters (e.g., the `@pytest.mark.skip_if_deployed` marker in combination with the `--no-deploy` configuration helps you skip, e.g., a deployment test in the case where you already have a deployment).


> See more:
> - [`pytest-operator` > Markers](https://github.com/charmed-kubernetes/pytest-operator/blob/main/docs/reference.md#markers)
> - [`pytest-operator` > Command line parameters](https://github.com/charmed-kubernetes/pytest-operator/blob/main/docs/reference.md#command-line-parameters)
