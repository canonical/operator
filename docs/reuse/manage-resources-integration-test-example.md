```python
import pathlib

import jubilant
import pytest
import yaml


METADATA = yaml.safe_load(pathlib.Path('./charmcraft.yaml').read_text())


@pytest.mark.juju_setup
def test_deploy(charm: pathlib.Path, juju: jubilant.Juju):
    resources = {
        name: res['upstream-source']
        for name, res in METADATA['resources'].items()
    }
    juju.deploy(charm, resources=resources)
    juju.wait(jubilant.all_active)
```
