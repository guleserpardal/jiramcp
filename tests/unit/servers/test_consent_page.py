"""Kurum onay ekranı: form sözleşmesi, kaçış, logo, okuma/yazma metni."""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_atlassian.servers import consent_page as cp


def _render(**kw: object) -> str:
    args: dict[str, object] = {
        "client_id": "cid-1",
        "redirect_uri": "http://localhost:5050/api/jira-oauth/callback",
        "scopes": ["READ"],
        "txn_id": "TXN",
        "csrf_token": "CSRF",
        "client_name": "QNB ITool",
    }
    args.update(kw)
    return cp.create_consent_html_tr(**args)  # type: ignore[arg-type]


def test_form_contract_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    """FastMCP'nin POST işleyicisinin beklediği alanlar aynen var."""
    monkeypatch.delenv("MCP_CONSENT_LOGO_FILE", raising=False)
    page = _render()
    assert 'name="txn_id" value="TXN"' in page
    assert 'name="csrf_token" value="CSRF"' in page
    assert 'name="submit" value="true"' in page
    assert 'name="action" value="approve"' in page
    assert 'name="action" value="deny"' in page
    assert "Content-Security-Policy" in page
    assert "Jira hesabınızı bağlayın" in page
    assert "QNB ITool" in page


def test_escapes_client_supplied_text() -> None:
    """İstemci adı DCR ile dışarıdan gelir — HTML olarak yorumlanmamalı."""
    page = _render(client_name='<script>alert("x")</script>')
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page


def test_read_only_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("READ_ONLY_MODE", "true")
    assert "Yalnız okuma" in _render()
    monkeypatch.setenv("READ_ONLY_MODE", "false")
    assert "Okuma ve yazma" in _render()


def test_logo_embedded_as_data_uri(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    logo = tmp_path / "logo.svg"
    logo.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    monkeypatch.setenv("MCP_CONSENT_LOGO_FILE", str(logo))
    assert 'src="data:image/svg+xml;base64,' in _render()


def test_missing_logo_falls_back_to_org_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_CONSENT_LOGO_FILE", "/yok/logo.png")
    monkeypatch.setenv("MCP_CONSENT_ORG", "Test Kurum")
    page = _render()
    assert "<img" not in page
    assert '<div class="org">Test Kurum</div>' in page


def test_install_replaces_fastmcp_renderer(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastmcp.server.auth.oauth_proxy import consent as consent_module

    original = consent_module.create_consent_html
    try:
        monkeypatch.delenv("MCP_CONSENT_PAGE", raising=False)
        assert cp.install_consent_page() is True
        assert consent_module.create_consent_html is cp.create_consent_html_tr
    finally:
        consent_module.create_consent_html = original


def test_install_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastmcp.server.auth.oauth_proxy import consent as consent_module

    original = consent_module.create_consent_html
    monkeypatch.setenv("MCP_CONSENT_PAGE", "fastmcp")
    assert cp.install_consent_page() is False
    assert consent_module.create_consent_html is original


def test_consent_has_no_unconditional_storage_or_revocation_promises() -> None:
    page = _render()
    assert "yalnız şirket içindeki" not in page
    assert "şifreli tutulur" not in page
    # form-action olursa Chrome, onay sonrası Jira'ya giden 302'yi engeller.
    assert "form-action" not in page
    assert 'name="referrer" content="no-referrer"' in page
    assert "focus-visible" in page
    assert "@media(max-width:640px)" in page
