"""``python -m mcp_atlassian.db <upgrade|downgrade REV|current|sql|ping>``."""

from __future__ import annotations

import asyncio
import statistics
import sys
import time

from alembic import command

from mcp_atlassian.db.migrate import alembic_config

_USAGE = "usage: python -m mcp_atlassian.db upgrade|downgrade REV|current|sql|ping"
_PING_ROUNDS = 10


async def ping() -> list[str]:
    """Measure connection setup and query round trip to PostgreSQL.

    Every OAuth storage access is one round trip; a login needs ~14, each MCP
    request ~4 (fewer with the read cache). Use this from the MCP host.

    Returns:
        Report lines (no URL or password).
    """
    import asyncpg

    from mcp_atlassian.db.settings import VERSION_TABLE, asyncpg_url, get_pg_url

    started = time.perf_counter()
    conn = await asyncpg.connect(asyncpg_url(get_pg_url()), timeout=10)
    connect_ms = (time.perf_counter() - started) * 1000
    try:
        rounds = []
        for _ in range(_PING_ROUNDS):
            t = time.perf_counter()
            await conn.fetchval("SELECT 1")
            rounds.append((time.perf_counter() - t) * 1000)
        version = await conn.fetchval(
            f"SELECT version_num FROM {VERSION_TABLE}"  # noqa: S608 - constant
        )
    finally:
        await conn.close()
    avg = statistics.mean(rounds)
    return [
        f"connect: {connect_ms:.0f} ms",
        f"query round trip: avg {avg:.1f} ms, min {min(rounds):.1f}, "
        f"max {max(rounds):.1f} ({_PING_ROUNDS} x SELECT 1)",
        f"estimated storage time: login ~{14 * avg:.0f} ms, "
        f"MCP request ~{4 * avg:.0f} ms without cache",
        f"schema revision: {version}",
    ]


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
    elif action == "ping":
        for line in asyncio.run(ping()):
            print(line)
    elif action == "sql":
        command.upgrade(cfg, "head", sql=True)
    else:
        print(_USAGE, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
