# Copyright 2019-2020 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Setup script for the Operator Framework."""

from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path
from setuptools import setup, find_packages


def _read_me() -> str:
    """Return the README content from the file."""
    with open("README.md", "rt", encoding="utf8") as fh:
        readme = fh.read()
    return readme


def _get_version() -> str:
    """Get the version via ops/version.py, without loading ops/__init__.py."""
    spec = spec_from_file_location('ops.version', 'ops/version.py')
    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    return module.version


version = _get_version()
version_path = Path("ops/version.py")
version_backup = Path("ops/version.py~")
if version_backup.exists():
    # unlink(missing_ok=True) is a 3.8-ish
    version_backup.unlink()
version_path.rename(version_backup)
try:
    with version_path.open("wt", encoding="utf8") as fh:
        fh.write('''\
# this is a generated file

version = {!r}
'''.format(version))

    setup(
        name="ops",
        version=version,
        description="The Python library behind great charms",
        long_description=_read_me(),
        long_description_content_type="text/markdown",
        license="Apache-2.0",
        url="https://github.com/canonical/operator",
        author="The Charmcraft team at Canonical Ltd.",
        author_email="charmcraft@lists.launchpad.net",
        packages=find_packages(include=('ops', 'ops.*')),
        classifiers=[
            "Programming Language :: Python :: 3",
            "License :: OSI Approved :: Apache Software License",
            "Development Status :: 4 - Beta",

            "Intended Audience :: Developers",
            "Intended Audience :: System Administrators",
            "Operating System :: MacOS :: MacOS X",
            "Operating System :: POSIX :: Linux",
            # include Windows once we're running tests there also
            # "Operating System :: Microsoft :: Windows",
        ],
        python_requires='>=3.5',
        install_requires=["PyYAML"],
    )

finally:
    version_path.unlink()
    version_backup.rename(version_path)
