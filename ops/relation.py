# Copyright 2021 Canonical Ltd.
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

"""A management layer for charm relations."""

import json
import logging
import semantic_version as semver

from ops.charm import CharmEvents
from ops.framework import (
    Object, EventSource, EventBase, StoredState
)

logger = logging.getLogger(__name__)


class ProviderBase(Object):
    """Manages relations of service providers.

    A :class:`ProviderBase` object manages relations of a service provider
    charms, with charms that consume those services. When a consumer
    charm joins the relation a provider object informs it of the type
    and version of the service provided. Providers may also be
    instrumented to inform consumer charms of any relevant
    information, for example configuration settings. This is done
    using the `service` and `version` argument of the
    :class:`ProviderBase` constructor.

    Any charm that provides a service may choose to do so through the
    :class:`ProviderBase` object simply by instantiating it in the charm's
    `__init__` method, as follows

    Example::

        self.provider = Provider(self, relation_name, service, version)
        ...
        self.provider.ready()

    It is important to invoke `ready()` on the :class:`ProviderBase`
    object, in order to let the consumer charm know that the provider
    is serving requests. This is done by setting a Boolean flag
    `ready` in the data forwarded to the consumer charm. A provider
    charm may toggle this flag by invoking `unready()` when it
    is unable to service any requests for example prior to a series
    upgrade. After an upgrade the :class:`ProviderBase` object notifies
    consumer charms by re-sending type, version and any other data to
    the consumer. Even though :class:`ProviderBase` objects only handle
    relation joined and provider upgrade events, they may be
    sub-classed to extend their functionality in any way desired.

    Args:
        charm: :class:`ops.charm.CharmBase` derived object that is
            instantiating :class:`ProviderBase`. This is almost always
            `self`.
        name: string name of relation (as defined in `metadata.yaml`) that
            consumer charms will use to interact with provider charms.
        service: a string naming service being provided by this charm.
            For example for a MySQL charm service could be "mysql".
            This name must be consistent between :class:`ProviderBase`
            and :class:`ConsumerBase`
        version: a string providing version of service provided by the
            charm. This version string can be in any form that is
            compatible with the
            `semver <https://pypi.org/project/semver/>`_ Python package.
            It is important that the version is obtained by actually
            querrying the deployed application rather than being written
            into the code. This is because the same charm may be used
            to deploy different versions of a service (application).
    """
    _stored = StoredState()

    def __init__(self, charm, name, service, version=None):
        super().__init__(charm, name)

        self._stored.set_default(ready=False)
        self.name = name
        self.provides = {service: version}

        events = charm.on[name]
        self.framework.observe(events.relation_joined, self._on_consumer_joined)
        self.framework.observe(charm.on.upgrade_charm, self._on_upgrade)

    def _on_consumer_joined(self, event):
        """Handle consumer joined event.

        Args:
            event: event object
        """
        data = self._provider_data()

        if self.model.unit.is_leader():
            logger.debug("Providing for joined consumer : %s", data)
            event.relation.data[self.model.app]['provider_data'] = json.dumps(data)

    def _on_upgrade(self, event):
        """Handle a provider upgrade event.

        Args:
            event: event object
        """
        self._notify_consumers()

    def _notify_consumers(self):
        """Resend provider data to consumers."""
        data = self._provider_data()
        if self.model.unit.is_leader():
            logger.debug("Notifying Consumer : %s", data)
            for rel in self.framework.model.relations[self.name]:
                rel.data[self.model.app]['provider_data'] = json.dumps(data)

    def ready(self):
        """Set provider state to ready."""
        if not self.is_ready:
            logger.debug("Provider is ready")
            self._stored.ready = True
            self._notify_consumers()

    def unready(self):
        """Set provider state to unready."""
        logger.debug("Provider is not ready")
        self._stored.ready = False
        self._notify_consumers()

    def _provider_data(self):
        """Construct relation data packet for consumer."""
        data = dict()
        data['provides'] = self.provides.copy()
        data['ready'] = self._stored.ready
        return data

    @property
    def is_ready(self):
        """Query state of provider."""
        return self._stored.ready


class ProviderAvailable(EventBase):
    """Event triggered when a valid provider is found.

    When a consumer charm forms a relation with a provider charm,
    their :class:`ConsumerBase` and :class:`ProviderBase` object exchange
    information to ascertain compatibility. If the relation is found
    to be compatible then the :class:`ConsumerBase` object raises a
    :class:`ProviderAvailable` event to inform the consumer charm, that
    a relation with the provider charm has been successful.
    """
    def __init__(self, handle, data=None):
        super().__init__(handle)
        self.data = data

    def snapshot(self):
        """Save relation data."""
        return {"data": self.data}

    def restore(self, snapshot):
        """Restore relation data."""
        self.data = snapshot["data"]


class ProviderInvalid(EventBase):
    """Event triggered when a provider is not compatible.

    When a consumer charm forms a relation with a provider charm,
    their :class:`ConsumerBase` and :class:`ProviderBase` object exchange
    information to ascertain compatibility. If the relation is found
    not to be compatible then the :class:`ConsumerBase` object raises a
    :class:`ProviderInvalid` event to inform the consumer charm, that
    a relation with the provider charm has *not* been successful.
    """
    def __init__(self, handle, data=None):
        super().__init__(handle)
        self.data = data

    def snapshot(self):
        """Save relation data."""
        return {"data": self.data}

    def restore(self, snapshot):
        """Restore relation data."""
        self.data = snapshot["data"]


class ProviderUnready(EventBase):
    """Event triggered when a provider is not ready.

    If a provider charm is not ready to service requests, when a
    consumer charm forms a new relation with it, or is already related
    to it, then a :class:`ProviderUnready` event is raised. This
    presumes that the provider charm has set its `ready` status to
    `False` or is set to `False` by default.

    The :class:`ProviderUnready` event is raised regardless of whether
    the provider charm is compatible or not. Compatibility checks are
    done only if the provider charm is ready to service requests. This
    event may be raised multiple times during the lifecycle of a charm.
    """
    pass


class ProviderBroken(EventBase):
    """Event raised when provider consumer relation is dissolved.

    If the relation between a provider and consumer charm is removed,
    then a :class:`ProviderBroken` relation is raised.
    """
    pass


class TooManyProviders(EventBase):
    """Event raised when more than one provider is related in single mode.

    A consumer charm may allow relations with a single or multiple
    providers, for a specific relation name. This choice is specified
    by the `multi` argument of the :class:`ConsumerBase` constructor. In
    "single" mode if more than one provider charm is related to the
    consumer, this event is raised. In particular, the events are
    raised in response to a relation joined event for each additional
    unit of the same or any additional provider.
    """
    pass


class ConsumerEvents(CharmEvents):
    """Descriptor for consumer charm events."""
    available = EventSource(ProviderAvailable)
    invalid = EventSource(ProviderInvalid)
    unready = EventSource(ProviderUnready)
    broken = EventSource(ProviderBroken)
    too_many_providers = EventSource(TooManyProviders)


class ConsumerBase(Object):
    """Manages relations with a service provider.

    The :class:`ConsumerBase` object manages relations with service
    provider charms, by checking compatibility between consumer
    requirements and provider type and version specification. Any
    charm that uses services provided by other charms may manage its
    relation with the providers by instantiating a :class:`ConsumerBase`
    object for each such relation. A :class:`ConsumerBase` object may be
    instantiated in the `__init__` method of the consumer charm as
    follows

    Example::

        self.provider_name = ConsumerBase(self, relation_name, consumes)

    In managing the relation between provider and consumer, the
    :class:`ConsumerBase` object may raise any of the following events,
    that a consumer charm can choose to respond to

    - :class:`ProviderAvailable`
    - :class:`ProviderInvalid`
    - :class:`ProviderUnready`
    - :class:`ProviderBroken`
    - :class:`TooManyProviders`

    Note that these events may be raised multiple times during the
    lifetime of a charm. In particular every time there is a change to
    the relation data shared between provider and consumer, one of the
    first three events is raised.

    Args:
        charm: :class:`ops.charm.CharmBase` derived object that is
            instantiating the :class:`ConsumerBase` object. This is almost
            always `self`.
        name: string name of relation (as defined in `metadata.yaml`) that
            consumer charms will use to interact with provider charms.
        consumes: a dictionary containing acceptable provider
            specifications. The dictionary may contain key value
            pairs any one of which is an acceptable provider
            specifications. The keys in these specifications are the
            service names strings. And the values are version
            specification strings. Here service name and service
            version pertain to the software service required by the
            consumer charm. The version specification strings can by
            in any form that is compatible with the
            `semver <https://pypi.org/project/semver/>`_ Python
            package. A valid example of the `consumes` dictionary is
            Example::

            consumes = {'mysql': '>5.0.2', 'mariadb': '<=6.1.0'}

        multi: a Boolean flag that indicates if the :class:`ConsumerBase` derived
            object supports multiple relations with the same relation name. By
            default this is `False`.
    """
    on = ConsumerEvents()
    _stored = StoredState()

    def __init__(self, charm, name, consumes, multi=False):
        super().__init__(charm, name)

        self.name = name
        self.consumes = consumes
        self.multi_mode = multi
        self._stored.set_default(relation_id=None)

        events = charm.on[name]
        self.framework.observe(events.relation_joined, self._on_provider_joined)
        self.framework.observe(events.relation_changed, self._on_provider_changed)
        self.framework.observe(events.relation_broken, self._on_provider_broken)
        self.framework.observe(charm.on.upgrade_charm, self._validate_provider)

    @property
    def relation_id(self):
        """Identifier for relation with producer.

        Returns:
           an integer identifier of relation with :class:`ProviderBase`
           if :class:`ConsumerBase` was instantiated in single
           mode (`multi=False`) and a valid relation exists. If either
           of these two conditions is false `None` is returned.
        """
        return self._stored.relation_id if self._stored.relation_id else None

    def _on_provider_joined(self, event):
        """Check if a new or additional provider is acceptable.

        Consumer charms may choose to allow only one or multplie
        relations with a provider, for a specific relation name. This
        choice is made using the `multi` argument of the
        :class:`ConsumerBase`. On every relation joined event with a
        provider a check is done to see if the new or additional
        provider relation is acceptable. In single mode more than one
        provider is not acceptable and in this case a
        :class:`TooManyProviders` event is emitted.
        """
        rel_id = event.relation.id
        if not self._provider_acceptable(rel_id):
            self.on.too_many_providers.emit()

    def _on_provider_changed(self, event):
        """Validate provider on relation changed event.

        This method checks the provider for compatibility with the
        consumer every time a relation changed event is raised. The
        provider is also checked to ensure it is ready to service
        requests. In response to these checks any of the following
        events may be raised.

        - :class:`ProviderAvailable`
        - :class:`ProviderInvalid`
        - :class:`ProviderUnready`
        - :class:`TooManyProviders`

        Note that these events may be raised multiple times during the
        lifetime of a charm.

        Args:
            event: an event object. It is expected that the event object
                contains a key `provider_data` whose value is all the data
                forwarded by the :class:`ProviderBase` object.
        """
        rel_id = event.relation.id
        if not self._provider_acceptable(rel_id):
            self.on.too_many_providers.emit()
            return

        rdata = event.relation.data[event.app]
        logger.debug("Got data from provider : %s", rdata)
        provider_data = rdata.get('provider_data')
        consumed = self.consumes
        if provider_data:
            data = json.loads(provider_data)
            try:
                provides = data['provides']
            except KeyError:
                # provider has not set any specification
                # so no compatibility checks are done
                # and no events are raised
                logger.warning('Provider not specified')
                return
        else:
            logger.debug('No provider data')
            # provider has not given any information
            # so provider will not be made available (as yet)
            return

        ready = data.get('ready')
        if not ready:
            self.on.unready.emit()
            return

        requirements_met = self._meets_requirements(provides, consumed)

        if requirements_met:
            logger.debug('Got compatible provider : %s', provider_data)
            if not self.multi_mode and not self._stored.relation_id:
                self._stored.relation_id = rel_id
                logger.debug('Saved relation id : %s', rel_id)
            self.on.available.emit(data)
        else:
            logger.error('Incompatible provider : Need %s, Got %s',
                         consumed, provider_data)
            self.on.invalid.emit(provides)

    def _on_provider_broken(self, event):
        """Inform consumer charm that provider relation no longer exists.

        This method raises a :class:`ProviderBroken` event in response to
        a relation broken event.

        Args:
            event: an event object
        """
        logger.debug("Provider Broken : %s", event)
        if not self.multi_mode:
            self._stored.relation_id = None
        self.on.broken.emit()

    def _validate_provider(self, event):
        """Check provider and consumer compatibility.

        This method validates provider consumer compatibility using
        data that is already available in the application relation
        bucket.

        Args:
            event: an event object
        """
        logger.debug("Validating provider(s) : %s", event)
        consumed = self.consumes

        for relation in self.framework.model.relations[self.name]:
            rel_id = relation.id
            if not self._provider_acceptable(rel_id):
                continue

            data = self._provider_data(rel_id)
            if data:
                try:
                    provides = data['provides']
                except KeyError:
                    continue

            requirements_met = self._meets_requirements(provides, consumed)
            if requirements_met:
                self.on.available.emit(data)
            else:
                logger.error('Provider no longer compatible, Need %s, have %s',
                             consumed, data)
                self.on.invalid.emit(data)

    def _meets_requirements(self, provides, consumes):
        """Check if provider and consumer are compatible.

        Args:
            provides: a dictionary with a single key value pair. The key
                is a string naming the service provided. The value is a
                string given the version of the provided service.
            consumes: a dictionary with zero or more key value pairs. Each
                key is a string name of a service that is acceptable. The
                corresponding value is a string representing an acceptable
                version specification. The version specification can be in any
                format that is compatible with the
                `semver <https://pypi.org/project/semver/>`_ Python package.

        Returns:
            bool: True if the producer and consumer specification are
            compatible.
        """
        assert(len(provides) == 1)
        provided = tuple(provides.items())[0]
        for required in consumes.items():
            if self._is_compatible(provided, required):
                return True
        return False

    def _is_compatible(self, has, needs):
        """Is a provider and consumer specification compatible.

        Args:
            has: a tuple (pair) of strings. The first string is a
                string naming the service provided. The second is a
                string giving the version of the provided service.
            needs: a tuple (pair) of strings. The first string is a
                string naming an acceptable services type. The second is a
                string specifying acceptable versions for the service
                type. The version specification can be in any format that is
                compatible with the
                `semver <https://pypi.org/project/semver/>`_ Python package.

        Returns:
            bool: True if the provider and consumer specification are
               compatible.
        """
        # if consumer has no constraints
        # compatibility is true by default
        if not needs:
            return True

        # if consumer has constraints but provider
        # has no specification compatibility can not
        # be determined and is hence false by default
        if not has and needs:
            return False

        # By now we know both consumer and provider have a
        # constraint specification so we check if the
        # constraint type is the same
        has_type = self._normalized_type(has)
        needs_type = self._normalized_type(needs)
        if has_type != needs_type:
            return False

        # By now we know consumer and provider have the
        # same constraint type so we check if the constraints
        # are further qualified by version specifications

        # If consumer is not qualified, provider and
        # consumer are compatible by default
        if not self._has_version(needs):
            return True

        # If consumer is qualified but provider is not there
        # is no way to determine compatibility so it is False
        # by default
        if not self._has_version(has):
            return False

        # Both consumer and provider are qualified so we
        # check compatibility of version
        spec = semver.SimpleSpec(self._normalized_version(needs))
        got = semver.Version.coerce(self._normalized_version(has))

        return spec.match(got)

    def _has_version(self, constraint):
        """Does the constraint have a version qualification.

        Args:
            constraint: a tuple containing a service type (first member)
                and optionally a service version (second member)

        Returns:
            bool: True if a service version is present in constraint.
        """
        if len(constraint) == 2 and constraint[1] is not None:
            return True
        return False

    def _normalized_version(self, constraint):
        """Remove spaces from version strings.

        Args:
            constraint: a tuple containing two members. The second member being
                a `semver` version specification.

        Returns:
            str: a version specification that has spaces removed in
                order to make it compatible with the `semver` package
                utilities.
        """
        version = constraint[1]
        return "".join(version.split()) if ' ' in version else version

    def _normalized_type(self, constraint):
        """Extract and lowercase type from specification.

        Args:
            constraint: a tuple contain two members. The first member
                being the string name of the service type.

        Returns:
            str: all lowercase equivalent of spec string, in order to
                facilitate case insensitive comparison of service types.
        """
        return constraint[0].lower()

    def _provider_data(self, rel_id=None):
        """Get provider relation data.

        Args:
            rel_id: integer identity of relation for which data is
                required. If the :class:`ConsumerBase` object was instantiated using
                `multi=True` then `rel_id` is a required argument, otherwise
                it is optional (and not used)

        Returns:
            dict: containing provider application relation relation data.
        """
        if self.multi_mode:
            assert(rel_id is not None)
            rel = self.framework.model.get_relation(self.name, rel_id)
        else:
            assert(len(self.framework.model.relations[self.name]) == 1)
            rel = self.framework.model.get_relation(self.name)

        data = json.loads(rel.data[rel.app]['provider_data'])
        return data

    def _provider_acceptable(self, rel_id):
        """Is a new or an additional provider acceptable.

        Args:
            rel_id : integer ID of provider relation

        Returns:
            True if provider is acceptable else false.
        """
        # only accept a provider if any of the following is true
        # 1) in multi mode
        # 2) seeing the first provider in single mode
        # 3) seeing the same provider again in single mode
        stored_id = self._stored.relation_id
        check_single = ((stored_id is None) or (stored_id == rel_id))
        if self.multi_mode or check_single:
            return True
        return False
