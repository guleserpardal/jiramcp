"""``python -m mcp_atlassian.db <upgrade|downgrade REV|current|sql>``."""

from __future__ import annotations

import sys

from alembic import command

from mcp_atlassian.db.migrate import alembic_config

_USAGE = "usage: python -m mcp_atlassian.db upgrade|downgrade REV|current|sql"


def main(argv: list[str]) -> int:
    """Dispatch a migration command.

    Args:
        argv: Command line arguments without the program name.

    Returns:
        Process exit code.
    """
    if not argv:
        print(_USAGE, file=sys.stderr)
        return 2
    cfg = alembic_config()
    action, rest = argv[0], argv[1:]
    if action == "upgrade":
        command.upgrade(cfg, rest[0] if rest else "head")
    elif action == "downgrade" and rest:
        command.downgrade(cfg, rest[0])
    elif action == "current":
        command.current(cfg)
    elif action == "sql":
        command.upgrade(cfg, "head", sql=True)
    else:
        print(_USAGE, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
