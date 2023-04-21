#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import typer

from scenario.scripts import logger
from scenario.scripts.snapshot import snapshot


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
    app.command(name="_", hidden=True)(lambda: None)

    @app.callback()
    def setup_logging(verbose: int = typer.Option(0, "-v", count=True)):
        logger.setup_logging(verbose)

    app()


if __name__ == "__main__":
    main()
