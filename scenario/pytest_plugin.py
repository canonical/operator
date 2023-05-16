#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest

from scenario import capture_events


@pytest.fixture()
def emitted_events():
    with capture_events() as captured:
        yield captured
