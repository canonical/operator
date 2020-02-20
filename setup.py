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

from setuptools import setup

with open("README.md", "r") as fh:
    long_description = fh.read()

setup(
    name="ops",
    version="0.0.1",
    description="The Python library behind great charms",
    long_description=long_description,
    long_description_content_type="text/markdown",
    license="Apache-2.0",
    url="https://github.com/canonical/operator",
    packages=["ops"],
    classifiers=[
        "Development Status :: 4 - Beta",

        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",

        "License :: OSI Approved :: Apache Software License",
    ],
)
