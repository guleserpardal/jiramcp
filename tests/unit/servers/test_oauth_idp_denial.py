"""Jira'da "reddet" → uygulamaya geri dönüş (state'siz Jira hata yönlendirmesi)."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from starlette.applications import Starlette

from mcp_atlassian.servers.consent_page import install_consent_page
from mcp_atlassian.servers.oauth_proxy import HardenedOAuthProxy
from mcp_atlassian.utils.token_verifier import AtlassianOpaqueTokenVerifier
from tests.utils.oauth_dcr_harness import (
    OAuthDCRClientHarness,
    RegisteredClient,
    build_pkce_verifier,
)

CLIENT_CB = "http://127.0.0.1:4242/callback"
JIRA = "https://jira.example.test"


def _proxy() -> HardenedOAuthProxy:
    return HardenedOAuthProxy(
        base_url="https://mcp.test",
        upstream_authorization_endpoint=f"{JIRA}/rest/oauth2/latest/authorize",
        upstream_token_endpoint=f"{JIRA}/rest/oauth2/latest/token",
        upstream_client_id="upstream-client-id",
        upstream_client_secret="upstream-client-secret",
        token_verifier=AtlassianOpaqueTokenVerifier(required_scopes=["READ"]),
        allowed_grant_types=["authorization_code", "refresh_token"],
        forced_scopes=["READ"],
        require_authorization_consent=True,
        redirect_path="/callback",
    )


@pytest.fixture
async def browser(
    tmp_path,
) -> AsyncIterator[tuple[httpx.AsyncClient, HardenedOAuthProxy]]:
    install_consent_page()
    provider = _proxy()
    app = Starlette(routes=provider.get_routes("/mcp"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://mcp.test"
    ) as client:
        yield client, provider


async def _approve_consent(
    client: httpx.AsyncClient, registered: RegisteredClient, state: str
) -> str:
    """/authorize → consent page → approve; returns the txn_id sent to Jira."""
    _, challenge = build_pkce_verifier()
    r = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": registered.client_id,
            "redirect_uri": registered.redirect_uri,
            "scope": "READ",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    assert r.status_code in {302, 307}
    consent_url = r.headers["location"]
    txn_id = parse_qs(urlparse(consent_url).query)["txn_id"][0]
    page = await client.get(consent_url)
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert csrf, page.text[:300]
    r = await client.post(
        "/consent",
        data={
            "txn_id": txn_id,
            "csrf_token": csrf.group(1),
            "submit": "true",
            "action": "approve",
        },
    )
    assert r.status_code in {302, 303, 307}
    assert r.headers["location"].startswith(JIRA)
    return txn_id


async def _register(client: httpx.AsyncClient) -> RegisteredClient:
    harness = OAuthDCRClientHarness(client, upstream_ca_path=None)  # type: ignore[arg-type]
    return await harness.register(CLIENT_CB)


def _client_redirect(r: httpx.Response) -> dict[str, list[str]]:
    assert r.status_code in {302, 307}, r.text[:300]
    target = urlparse(r.headers["location"])
    assert f"{target.scheme}://{target.netloc}{target.path}" == CLIENT_CB
    return parse_qs(target.query)


@pytest.mark.anyio
async def test_denial_without_state_returns_to_app(browser) -> None:
    client, _ = browser
    reg = await _register(client)
    await _approve_consent(client, reg, "app-state-1")

    r = await client.get(
        "/callback",
        params={
            "error": "access_denied",
            "error_description": "The user cancelled the authentication",
        },
    )
    q = _client_redirect(r)
    assert q["error"] == ["access_denied"]
    assert q["state"] == ["app-state-1"]


@pytest.mark.anyio
async def test_denial_with_state_still_returns_to_app(browser) -> None:
    client, _ = browser
    reg = await _register(client)
    txn_id = await _approve_consent(client, reg, "app-state-2")
    r = await client.get(
        "/callback", params={"error": "access_denied", "state": txn_id}
    )
    assert _client_redirect(r)["state"] == ["app-state-2"]


@pytest.mark.anyio
async def test_denial_without_binding_shows_turkish_page(browser) -> None:
    client, _ = browser
    r = await client.get("/callback", params={"error": "access_denied"})
    assert r.status_code == 400
    assert "OAuth Error" not in r.text
    assert "izin vermediniz" in r.text
    assert "<script" not in r.text


@pytest.mark.anyio
async def test_two_pending_flows_are_not_guessed(browser) -> None:
    client, _ = browser
    reg = await _register(client)
    await _approve_consent(client, reg, "one")
    await _approve_consent(client, reg, "two")
    r = await client.get("/callback", params={"error": "access_denied"})
    assert r.status_code == 400
    assert "location" not in r.headers


@pytest.mark.anyio
async def test_success_callback_is_untouched(browser, monkeypatch) -> None:
    """A code (not an error) without state still goes to FastMCP's own checks."""
    client, _ = browser
    r = await client.get("/callback", params={"code": "x"})
    assert r.status_code == 400


@pytest.mark.anyio
async def test_cookie_token_must_match_transaction(browser) -> None:
    """A binding whose token differs from the transaction's is not trusted."""
    client, provider = browser
    reg = await _register(client)
    txn_id = await _approve_consent(client, reg, "app-state-3")
    txn = await provider._transaction_store.get(key=txn_id)
    assert txn is not None
    txn.consent_token = "something-else"
    await provider._transaction_store.put(key=txn_id, value=txn, ttl=900)

    r = await client.get("/callback", params={"error": "access_denied"})
    assert r.status_code == 400
    assert "location" not in r.headers
