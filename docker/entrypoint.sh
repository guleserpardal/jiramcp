#!/bin/sh
# MCP_DB_MIGRATE_ON_START=true ise PostgreSQL tabloları başlamadan önce güncellenir.
# Birden çok kopya çalışıyorsa bunu kapalı tutup migration'ı ayrı bir işte çalıştırın:
#   docker run --rm --env-file mcp.env jira-mcp:1.0 python -m mcp_atlassian.db upgrade
set -e

if [ "$#" -gt 0 ] && [ "${1#-}" = "$1" ]; then
  # İlk argüman bir komut (ör. python -m mcp_atlassian.db upgrade): onu çalıştır.
  exec "$@"
fi

if [ "${MCP_DB_MIGRATE_ON_START:-false}" = "true" ]; then
  echo "[entrypoint] PostgreSQL migration çalıştırılıyor"
  python -m mcp_atlassian.db upgrade
fi

exec mcp-atlassian "$@"
