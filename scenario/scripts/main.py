#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os

import typer

from scenario.scripts.snapshot import snapshot


def _setup_logging(verbosity: int):
    base_loglevel = int(os.getenv("LOGLEVEL", 30))
    verbosity = min(verbosity, 2)
    loglevel = base_loglevel - (verbosity * 10)
    logging.basicConfig(level=loglevel, format="%(message)s")


def main():
    app = typer.Typer(
        name="scenario",
        help="Scenario utilities.",
        no_args_is_help=True,
        rich_markup_mode="markdown",
    )

    # trick to prevent 'snapshot' from being the toplevel command.
    # We want to do `scenario snapshot`, not just `snapshot`.
    # TODO remove if/when scenario has more subcommands.
    app.command(name="_", hidden=True)(lambda: None)

    app.command(name="snapshot", no_args_is_help=True)(snapshot)

    @app.callback()
    def setup_logging(verbose: int = typer.Option(0, "-v", count=True)):
        _setup_logging(verbose)

    app()


if __name__ == "__main__":
    main()
