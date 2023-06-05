#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import logging

import pytest

from scenario import capture_events
from scenario.outputs import ACTION_OUTPUT, ActionOutput

logger = logging.getLogger(__name__)


@pytest.fixture()
def emitted_events():
    with capture_events() as captured:
        yield captured


@pytest.fixture(autouse=True)
def action_output():
    logger.info("setting up action context")
    ao = ActionOutput()
    tok = ACTION_OUTPUT.set(ao)
    yield ao
    logger.info("resetting action context")
    ACTION_OUTPUT.reset(tok)
