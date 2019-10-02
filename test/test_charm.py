#!/usr/bin/python3

import unittest
import tempfile
import shutil

from pathlib import Path

from juju.charm import CharmBase
from juju.framework import Framework


class TestCharm(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def create_framework(self):
        return Framework(self.tmpdir / "framework.data")

    def test_basic(self):

        class MyCharm(CharmBase):

            def __init__(self, framework, key):
                super().__init__(framework, key)
                
                self.started = False
                framework.observe(self.on.start, self)

            def on_start(self, event):
                self.started = True

        framework = self.create_framework()
        charm = MyCharm(framework, None)
        charm.on.start.emit()

        self.assertEqual(charm.started, True)


if __name__ == "__main__":
    unittest.main()
