#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Test framework logger"""

import logging
import os

logger = logging.getLogger("ops-scenario")
logger.setLevel(os.getenv("OPS_SCENARIO_LOGGING", "WARNING"))
