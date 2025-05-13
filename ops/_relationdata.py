# Copyright 2025 Canonical Ltd.
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

"""Support for strongly typed charm interfaces."""

from __future__ import annotations


class RelationDataBase:
    """Base class for strongly typed relation data.

    Use ``RelationDataBase`` as a base class for your data class. For example::

        @dataclasses.dataclass
        class UUCPData(RelationDataBase):
            protocol: str
            identification: str
            retry_limit: int

    .. note::

        The class will be initialised with the raw Juju databag content passed
        as keyword arguments. Any errors should be indicated by raising
        ``ValueError`` (or a ``ValueError`` subclass) in initialisation.

    Use this in your charm class like so::

        class MyCharm(CharmBase):
            ...
            def _on_relation_event(self, event: ops.RelationEvent):
                relation = event.relation
                data = relation.load(UUCPData, self.app)
    """

    # This class does not currently provide any functionality - any class that
    # has an appropriate __init__ could be passed to load_data() and would work.
    # However, we may want to add some built-in functionality to the base class
    # in the future - for example, to provide some default validation when the
    # class is a dataclass rather than a pydantic model, or to make it easier to
    # select which fields are serialised. Requiring users to inherit from this
    # class makes it easier to add that functionality in the future.
