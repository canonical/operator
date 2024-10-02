import sys

pytest_plugins = "pytester"
sys.path.append(".")


def test_plugin_ctx_run(pytester):
    # create a temporary pytest test module
    pytester.makepyfile(
        """
        import pytest
        from scenario import State
        from scenario import Context
        import ops

        class MyCharm(ops.CharmBase):
            pass

        @pytest.fixture
        def context():
            return Context(charm_type=MyCharm, meta={"name": "foo"})

        def test_sth(context):
            context.run(context.on.start(), State())
    """
    )

    # run pytest with the following cmd args
    result = pytester.runpytest("-v")

    # fnmatch_lines does an assertion internally
    result.stdout.fnmatch_lines([
        "*::test_sth PASSED*",
    ])

    # make sure that we get a '0' exit code for the testsuite
    assert result.ret == 0
