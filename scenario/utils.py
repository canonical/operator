#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.


def exhaust(generator):
    while True:
        try:
            next(generator)
        except StopIteration as e:
            return e.value
