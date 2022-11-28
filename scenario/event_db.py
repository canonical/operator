import tempfile
import typing
from pathlib import Path

if typing.TYPE_CHECKING:
    from runtime.memo import Scene


class TemporaryEventDB:
    def __init__(self, scene: "Scene", tempdir=None):
        self.scene = scene
        self._tempdir = tempdir
        self._tempfile = None
        self.path = None

    def __enter__(self):
        from scenario.scenario import Playbook

        self._tempfile = tempfile.NamedTemporaryFile(dir=self._tempdir, delete=False)
        self.path = Path(self._tempfile.name).absolute()
        self.path.write_text(Playbook([self.scene]).to_json())
        return self.path

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.path.unlink()

        self._tempfile = None
        self.path = None
