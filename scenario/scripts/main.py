import typer

from scenario.scripts.snapshot import snapshot


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
    app()


if __name__ == "__main__":
    main()
