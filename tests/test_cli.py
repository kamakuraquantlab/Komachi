"""The argument parser itself, which no other test builds."""

def test_every_subcommand_resolves_to_a_handler():
    """Guards against a handler being renamed or removed out from under the parser.

    Nothing else in the suite builds the parser, so a subcommand pointing at a
    function that no longer exists stayed invisible until the CLI was run.
    """
    import cli

    parser = cli.build_parser()
    actions = [a for a in parser._subparsers._group_actions if hasattr(a, "choices")]
    seen = 0
    for action in actions:
        for name, sub in action.choices.items():
            func = sub.get_default("func")
            if func is None:      # a group like `auth`, whose children carry the handlers
                continue
            assert callable(func), f"{name} resolves to {func!r}"
            seen += 1
    assert seen >= 10
