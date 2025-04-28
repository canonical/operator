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


class DatabagBase:
    """Base class for strongly typed relation databags.

    Use :class:`DatabagBase` as a base class for your databag class. For example::

        @dataclasses.dataclass
        class MyDatabag(DatabagBase):
            foo: str
            bar: int
            baz: list[str] = dataclasses.field(default_factory=list)

    .. note::

        This is a dataclass, but can be any object that inherits from
        ``ops.DatabagBase``, and can be initialised with the raw Juju databag
        content passed as keyword arguments. Any errors should be indicated by
        raising ``ValueError`` (or a ``ValueError`` subclass) in initialisation.

    Use this in your charm class like so::

        class MyCharm(CharmBase):
            ...
            def _on_relation_event(self, event: ops.RelationEvent):
                relation = event.relation
                data = relation.load_data(MyDatabag, self.app)

    If the data provided by Juju is not valid, the charm will exit after setting
    a waiting status with an error message based on the ``str()`` of the
    exception raised. Charms may catch :class:`InvalidSchemaError` to provide
    custom handling.

    At the end of the hook, the updated values are automatically sent through to
    Juju. The databag class is responsible for ensuring that the data is valid.
    """

    # This class does not currently provide any functionality - any class that
    # has an appropriate __init__ could be passed to load_data() and would work.
    # However, we may want to add some built-in functionality to the base class
    # in the future - for example, to provide some default validation when the
    # class is a dataclass rather than a pydantic model, or to make it easier to
    # select which fields are serialised. Requiring users to inherit from this
    # class makes it easier to add that functionality in the future.
