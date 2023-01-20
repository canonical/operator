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

"""Setup script for Ops-Scenario."""

from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path
from setuptools import setup, find_packages


def _read_me() -> str:
    """Return the README content from the file."""
    with open("README.md", "rt", encoding="utf8") as fh:
        readme = fh.read()
    return readme


version = "0.2.1"

setup(
    name="scenario",
    version=version,
    description="Python library providing a Scenario-based "
                "testing API for Operator Framework charms.",
    long_description=_read_me(),
    long_description_content_type="text/markdown",
    license="Apache-2.0",
    url="https://github.com/PietroPasotti/ops-scenario",
    author="Pietro Pasotti.",
    author_email="pietro.pasotti@canonical.com",
    packages=[
        'scenario',
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "Intended Audience :: Developers",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: POSIX :: Linux",
    ],
    python_requires='>=3.8',
    install_requires=["asttokens",
                      "astunparse",
                      "ops"],
)
