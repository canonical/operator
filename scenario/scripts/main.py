#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os

import typer

from scenario.scripts.snapshot import snapshot
from scenario.scripts.state_apply import state_apply


def _setup_logging(verbosity: int):
    base_loglevel = int(os.getenv("LOGLEVEL", 30))
    verbosity = min(verbosity, 2)
    loglevel = base_loglevel - (verbosity * 10)
    logging.basicConfig(level=loglevel, format="%(message)s")


def main():
    app = typer.Typer(
        name="scenario",
        help="Scenario utilities. "
             "For docs, issues and feature requests, visit "
             "the github repo --> https://github.com/canonical/ops-scenario",
        no_args_is_help=True,
        rich_markup_mode="markdown",
    )

    app.command(name="snapshot", no_args_is_help=True)(snapshot)
    app.command(name="state-apply", no_args_is_help=True)(state_apply)

    @app.callback()
    def setup_logging(verbose: int = typer.Option(0, "-v", count=True)):
        _setup_logging(verbose)

    app()


if __name__ == "__main__":
    main()
