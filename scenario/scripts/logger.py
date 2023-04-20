#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os

logger = logging.getLogger(__file__)


def setup_logging(verbosity: int):
    base_loglevel = int(os.getenv("LOGLEVEL", 30))
    verbosity = min(verbosity, 2)
    loglevel = base_loglevel - (verbosity * 10)
    logging.basicConfig(format="%(message)s")
    logging.getLogger().setLevel(logging.WARNING)
    logger.setLevel(loglevel)
