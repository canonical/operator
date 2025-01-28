# Copyright 2025 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this
# file except in compliance with the License. You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under
# the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific language
# governing permissions and limitations under the License.
"""Workarounds for various Juju bugs."""

from __future__ import annotations

import logging
import os
import shutil
from collections import defaultdict
from typing import Any

import opentelemetry.trace
from importlib_metadata import distributions  # type: ignore

logger = logging.getLogger(__name__)
tracer = opentelemetry.trace.get_tracer(__name__)


# FIXME must this hack be run before OTEL packages are imported?
# must test this
@tracer.start_as_current_span('ops.remove_stale_otel_sdk_packages')  # type: ignore
def remove_stale_otel_sdk_packages() -> None:
    """Remove stale opentelemetry sdk packages from the charm's Python venv.

    Charmcraft doesn't record empty directories in the charm (zip) file.
    Juju creates directories on demand when a contained file is unpacked.
    Juju removes what it has installed before the upgrade is unpacked.
    Juju prior to 3.5.4 left unrecorded, stale directories.

    See https://github.com/canonical/grafana-agent-operator/issues/146
    and https://bugs.launchpad.net/juju/+bug/2058335

    This only has an effect if executed on an upgrade-charm event.
    """
    if os.getenv('JUJU_DISPATCH_PATH') != 'hooks/upgrade-charm':
        return

    logger.debug('Applying _remove_stale_otel_sdk_packages patch on charm upgrade')
    # group by name all distributions starting with "opentelemetry_"
    otel_distributions: dict[str, list[Any]] = defaultdict(list)
    for distribution in distributions():
        name = distribution._normalized_name
        if name.startswith('opentelemetry_'):
            otel_distributions[name].append(distribution)

    logger.debug(f'Found {len(otel_distributions)} opentelemetry distributions')

    # If we have multiple distributions with the same name, remove any that have 0
    # associated files
    for name, distributions_ in otel_distributions.items():
        if len(distributions_) <= 1:
            continue

        logger.debug(f'Package {name} has multiple ({len(distributions_)}) distributions.')
        for distribution in distributions_:
            if not distribution.files:  # Not None or empty list
                path = distribution._path
                logger.info(f'Removing empty distribution of {name} at {path}.')
                shutil.rmtree(path)

    logger.debug('Successfully applied _remove_stale_otel_sdk_packages patch. ')
