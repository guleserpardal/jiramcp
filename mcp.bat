@echo off
rem jiramcp sunucusunu uv olmadan, pip ile kurulmus .venv uzerinden baslatir.
rem Kullanim:
rem   mcp.bat --env-file mcp.env      asil sunucu (TRANSPORT/HOST/PORT mcp.env icinde)
rem   mcp.bat --env-file local.env    MCP Inspector icin, OAuth olmadan, STDIO
rem Bu dosya STDOUTa hicbir sey yazmamali: STDIO kipinde MCP mesajlari oradan akar.
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
"%~dp0.venv\Scripts\python.exe" -c "from mcp_atlassian import main; main()" %*
