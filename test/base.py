import os
import shutil
import tempfile
from pathlib import Path
from unittest import TestCase


class BaseTestCase(TestCase):
    """Base class for our tests to house shared logic."""
    _using_fake_hook_tools = False
    _tmpdir = None

    @property
    def tmpdir(self):
        if not self._tmpdir:
            self._tmpdir = Path(tempfile.mkdtemp())
            self.addCleanup(shutil.rmtree, self._tmpdir)
        return self._tmpdir

    def patch_env(self, **kwargs):
        """Patch os.environ for a test, and ensure it gets restored.

        Can be called multiple times.
        """
        old_env = dict(os.environ)
        os.environ.update(kwargs)
        self.addCleanup(os.environ.update, old_env)

    def create_hook_tool(self, tool_name, output='', exit_code=0, impl=None):
        """Create a fake implementation for a hook tool.

        Ensures that the hook tool will be invoked and cleaned up after the test.
        """
        bindir = self.tmpdir / "bin"
        hook_tool = bindir / tool_name
        if not self._using_fake_hook_tools:
            bindir.mkdir()
            self.patch_env(PATH=f"{self.tmpdir}/bin:{os.environ['PATH']}")
            self._using_fake_hook_tools = True
        if impl:
            hook_tool.write_text(f"#!/bin/bash\n{impl}")
        else:
            hook_tool.write_text(f"#!/bin/bash\n"
                                 f"echo '{output}'\n"
                                 f"exit {exit_code}\n")
        hook_tool.chmod(0o777)
