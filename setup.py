# Copyright 2019 Canonical Ltd.
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

import ast
from setuptools import setup, find_packages


def _read_me() -> str:
    with open("README.md", "rt", encoding="utf8") as fh:
        readme = fh.read()
    return readme


def _get_version() -> str:
    # ops.__init__ needs to pull in ops.charm to work around a circular
    # import so we can't import it here as that pulls in yaml which isn't
    # necessarily there yet.
    version = 'unknown'
    with open("ops/__init__.py", "rt", encoding="utf8") as fh:
        source = fh.read()
    code = ast.parse(source)
    for node in code.body:
        if isinstance(node, ast.Assign):
            targets = [i.id for i in node.targets]
            if '__version__' in targets:
                if isinstance(node.value, ast.Str):
                    # Python < 3.8
                    version = node.value.s
                else:
                    version = node.value.value
                break
    return version


setup(
    name="ops",
    version=_get_version(),
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
