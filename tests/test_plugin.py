import sys

pytest_plugins = "pytester"
sys.path.append(".")


def test_emitted_events_fixture(pytester):
    """Make sure that pytest accepts our fixture."""

    # create a temporary pytest test module
    pytester.makepyfile(
        """
        from scenario import State
        def test_sth(emitted_events):
            assert emitted_events == []
    """
    )

    # run pytest with the following cmd args
    result = pytester.runpytest("-v")

    # fnmatch_lines does an assertion internally
    result.stdout.fnmatch_lines(
        [
            "*::test_sth PASSED*",
        ]
    )

    # make sure that we get a '0' exit code for the testsuite
    assert result.ret == 0


def test_context(pytester):
    """Make sure that pytest accepts our fixture."""

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
            context.run('start', State())
    """
    )

    # run pytest with the following cmd args
    result = pytester.runpytest("-v")

    # fnmatch_lines does an assertion internally
    result.stdout.fnmatch_lines(
        [
            "*::test_sth PASSED*",
        ]
    )

    # make sure that we get a '0' exit code for the testsuite
    assert result.ret == 0
