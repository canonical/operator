# Copyright 2020 Canonical Ltd.
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

"""The Charmed Operator Framework.

The Charmed Operator Framework allows the development of operators in a simple
and straightforward way, using standard Python structures to allow for clean,
maintainable, and reusable code.

A Kubernetes operator is a container that drives lifecycle management,
configuration, integration and daily actions for an application. Operators
simplify software management and operations. They capture reusable app domain
knowledge from experts in a software component that can be shared.

The Charmed Operator Framework extends the "operator pattern" to enable Charmed
Operators, packaged as and often referred to as "charms". Charms are not just
for Kubernetes but also operators for traditional Linux or Windows application
management. Operators use an Operator Lifecycle Manager (OLM), like Juju, to
coordinate their work in a cluster. The system uses Golang for concurrent event
processing under the hood, but enables the operators to be written in Python.

Operators should do one thing and do it well. Each operator drives a single
application or service and can be composed with other operators to deliver a
complex application or service. An operator handles instantiation, scaling,
configuration, optimisation, networking, service mesh, observability,
and day-2 operations specific to that application.

Full developer documentation is available at https://juju.is/docs/sdk.
"""

# Import here the bare minimum to break the circular import between modules
from . import charm  # type: ignore # noqa
from .version import version as __version__  # type: ignore # noqa
