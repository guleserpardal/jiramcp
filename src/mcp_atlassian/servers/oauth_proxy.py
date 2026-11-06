"""OAuth proxy extensions and configuration helpers."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import posixpath
import re
import time
from collections.abc import Iterable
from contextvars import ContextVar
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit, urlunsplit

from fastmcp.server.auth.auth import AccessToken as FastMCPAccessToken
from fastmcp.server.auth.oauth_proxy import OAuthProxy
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    OAuthClientInformationFull,
    RefreshToken,
    RegistrationError,
    TokenError,
)
from mcp.server.auth.settings import RevocationOptions
from mcp.shared.auth import OAuthToken
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("mcp-atlassian.server.oauth_proxy")
_trace_logger = logging.getLogger("mcp-atlassian.oauth_trace")
_flow_id: ContextVar[str] = ContextVar("oauth_flow_id", default="setup")


def _flow_from_state(state: str) -> str:
    """Produce the same opaque correlation ID as ITool, never the state itself."""
    return hashlib.sha256(state.encode()).hexdigest()[:16]


def _trace(step: str, message: str, **detail: str | int | bool) -> None:
    """Emit opt-in metadata only; no credentials, payloads or URL queries."""
    if os.getenv("MCP_OAUTH_TRACE", "").lower() not in {"true", "1", "yes"}:
        return
    _trace_logger.setLevel(logging.INFO)
    payload = {
        "component": "mcp",
        "flowId": _flow_id.get(),
        "step": step,
        "message": message,
        "detail": detail,
    }
    _trace_logger.info("[OAuth] %s", json.dumps(payload, ensure_ascii=False))


def _endpoint(url: str) -> str:
    """Keep host and route, dropping userinfo and query credentials."""
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{host}{port}{parsed.path}"


def _normalize_list(values: Iterable[str] | None) -> list[str] | None:
    if values is None:
        return None
    return [value.strip() for value in values if value and value.strip()]


def parse_env_list(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    if not raw.strip():
        return []
    normalized = raw.replace(",", " ")
    return [item.strip() for item in normalized.split() if item.strip()]


def _redirect_target(uri: str) -> tuple[str, str, int | None, str] | None:
    """Return the origin and route used by a redirect URI."""
    try:
        parsed = urlsplit(uri)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if not parsed.scheme or not hostname:
        return None

    scheme = parsed.scheme.lower()
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None

    hostname = hostname.rstrip(".").lower()
    try:
        hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    try:
        hostname = str(ipaddress.ip_address(hostname))
    except ValueError:
        pass

    path = posixpath.normpath(unquote(parsed.path or "/"))
    if not path.startswith("/"):
        path = f"/{path}"

    return scheme, hostname, port, path.rstrip("/") or "/"


def _callback_uri(base_url: str, redirect_path: str) -> str:
    """Build the proxy's callback URI from its public base URL and route."""
    parsed = urlsplit(base_url)
    callback_path = f"{parsed.path.rstrip('/')}/{redirect_path.lstrip('/')}"
    return urlunsplit((parsed.scheme, parsed.netloc, callback_path, "", ""))


_SECRET_RE = re.compile(
    r'("?(?:access_token|refresh_token|id_token|client_secret|code)"?\s*[:=]\s*"?)([^"&,\s}]+)',
    re.IGNORECASE,
)


def _mask_secrets(text: str) -> str:
    """Mask token/secret values that an upstream error body might echo."""
    return _SECRET_RE.sub(lambda m: f"{m.group(1)}***", text or "")


class HardenedOAuthProxy(OAuthProxy):
    """OAuthProxy with stricter DCR controls for grants and scopes."""

    def __init__(
        self,
        *,
        base_url: AnyHttpUrl | str,
        redirect_path: str | None = None,
        allowed_grant_types: list[str] | None = None,
        forced_scopes: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(base_url=base_url, redirect_path=redirect_path, **kwargs)
        self.revocation_options = RevocationOptions(enabled=True)
        self._allowed_grant_types = _normalize_list(allowed_grant_types)
        self._forced_scopes = _normalize_list(forced_scopes)
        self._proxy_callback_target = _redirect_target(
            _callback_uri(str(self.base_url), self._redirect_path)
        )

    def _wrap_trace_route(self, app: ASGIApp, path: str) -> ASGIApp:
        """Observe OAuth routes without replacing protocol handlers or bodies."""

        async def observed(scope: Scope, receive: Receive, send: Send) -> None:
            request = Request(scope)
            flow = request.headers.get("X-OAuth-Flow-Id", "")
            flow = flow if re.fullmatch(r"[0-9a-f]{16}", flow) else "setup"
            transaction = None
            if path == "/authorize" and request.query_params.get("state"):
                flow = _flow_from_state(request.query_params["state"])
            elif path in {"/consent", self._redirect_path}:
                transaction_id = request.query_params.get(
                    "txn_id" if path == "/consent" else "state", ""
                )
                if transaction_id:
                    transaction = await self._transaction_store.get(key=transaction_id)
                    if transaction:
                        flow = _flow_from_state(transaction.client_state)
            context_token = _flow_id.set(flow)
            started = time.monotonic()
            _trace(
                "MCP_HTTP_RECEIVED",
                "MCP OAuth isteği alındı",
                path=path,
                method=request.method,
            )
            if path == "/consent":
                _trace(
                    "CONSENT_REQUEST",
                    "İzin ekranı gösteriliyor veya yanıtı işleniyor",
                    transactionFound=transaction is not None,
                )
            elif path == self._redirect_path:
                _trace(
                    "JIRA_CALLBACK",
                    "Tarayıcı Jira'dan MCP callback adresine döndü",
                    hasCode=bool(request.query_params.get("code")),
                    transactionFound=transaction is not None,
                )

            async def observed_send(message: Message) -> None:
                if message["type"] == "http.response.start":
                    status = int(message["status"])
                    _trace(
                        "MCP_HTTP_RETURN",
                        "MCP OAuth yanıtı gönderiliyor",
                        path=path,
                        status=status,
                        elapsedMs=int((time.monotonic() - started) * 1000),
                    )
                    headers = dict(message.get("headers", []))
                    location = headers.get(b"location", b"").decode("latin-1")
                    query = parse_qs(urlsplit(location).query)
                    if path == self._redirect_path and "code" in query:
                        _trace(
                            "MCP_CODE_ISSUED",
                            "Jira tokenları alındı; ITool için ayrı MCP kodu üretildi",
                        )
                        _trace(
                            "ITOOL_REDIRECT",
                            "Tarayıcı MCP kodu ve ITool state ile uygulamaya dönüyor",
                            endpoint=_endpoint(location),
                        )
                    elif path == "/authorize" and location:
                        _trace(
                            "MCP_AUTHORIZE_REDIRECT",
                            "Tarayıcı izin ekranına veya Jira'ya yönlendiriliyor",
                            endpoint=_endpoint(location),
                        )
                    elif path == "/consent" and location:
                        _trace(
                            "CONSENT_REDIRECT",
                            "İzin ekranından sonraki adrese yönlendiriliyor",
                            endpoint=_endpoint(location),
                        )
                await send(message)

            try:
                await app(scope, receive, observed_send)
            except Exception:
                _trace(
                    "MCP_REQUEST_FAILED",
                    "OAuth isteği tamamlanamadı; hata ayrıntıları gizlendi",
                )
                raise
            finally:
                _flow_id.reset(context_token)

        return observed

    def get_routes(self, mcp_path: str | None = None) -> list[Route]:
        """Retain SDK routes, adding isolated tracing around their ASGI apps."""
        routes = super().get_routes(mcp_path)
        if os.getenv("MCP_OAUTH_TRACE", "").lower() in {"true", "1", "yes"}:
            for route in routes:
                if route.path in {
                    "/authorize",
                    "/consent",
                    "/token",
                    "/register",
                    "/revoke",
                    self._redirect_path,
                }:
                    route.app = self._wrap_trace_route(route.app, route.path)
        return routes

    def _generate_pkce_pair(self) -> tuple[str, str]:
        """Observe the proxy's independent upstream PKCE pair without its values."""
        pair = super()._generate_pkce_pair()
        _trace(
            "MCP_PKCE_CREATED",
            "MCP, Jira bağlantısı için ayrı verifier ve SHA-256 challenge üretti",
        )
        return pair

    def _prepare_scopes_for_token_exchange(self, scopes: list[str]) -> list[str]:
        """Send no ``scope`` in the code exchange (Jira DC token request).

        RFC 6749 §4.1.3 has no ``scope`` parameter in the authorization-code
        token request and Jira Data Center does not document one; the scope is
        fixed at the authorize step. With ``READ_ALL`` Jira answered the token
        request with HTTP 500.
        """
        return []

    def _prepare_scopes_for_upstream_refresh(self, scopes: list[str]) -> list[str]:
        """Same for refresh: the grant keeps the scope it was issued with."""
        return []

    def _create_upstream_oauth_client(self) -> Any:
        """Log upstream HTTP boundaries using SDK-supported client event hooks."""
        client = super()._create_upstream_oauth_client()

        async def upstream_error(response: Any) -> None:
            # Jira's error body is the only place the cause is written
            # (e.g. a 500 from the token endpoint); log it, never the request.
            if response.status_code < 400:
                return
            try:
                await response.aread()
                body = _mask_secrets(response.text)[:1000]
            except Exception:  # noqa: BLE001 - logging must not break the flow
                body = "(gövde okunamadı)"
            logger.error(
                "Jira OAuth hatası: HTTP %s %s — %s",
                response.status_code,
                _endpoint(str(response.request.url)),
                body,
            )

        client.event_hooks.setdefault("response", []).append(upstream_error)
        if os.getenv("MCP_OAUTH_TRACE", "").lower() not in {"true", "1", "yes"}:
            return client

        async def sending(request: Any) -> None:
            _trace(
                "JIRA_HTTP_SEND",
                "MCP Jira OAuth adresine istek gönderiyor",
                method=request.method,
                endpoint=_endpoint(str(request.url)),
            )

        async def returned(response: Any) -> None:
            _trace(
                "JIRA_HTTP_RETURN",
                "Jira OAuth HTTP yanıtı alındı",
                status=response.status_code,
            )

        client.event_hooks.setdefault("request", []).append(sending)
        client.event_hooks.setdefault("response", []).append(returned)
        return client

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        """Observe the code lookup before the framework's PKCE check."""
        result = await super().load_authorization_code(client, authorization_code)
        _trace(
            "MCP_CODE_CHECK",
            "MCP kodunun istemci ve süre kontrolü yapıldı",
            valid=result is not None,
        )
        if result is not None:
            _trace(
                "MCP_PKCE_CHECK", "SDK verifier ve challenge eşleşmesini kontrol edecek"
            )
        return result

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        """This hook runs after the SDK has validated the client's PKCE proof."""
        _trace(
            "MCP_PKCE_VERIFIED",
            "MCP kodu ve ITool verifier kontrolü SDK tarafından geçti",
        )
        token = await super().exchange_authorization_code(client, authorization_code)
        _trace(
            "JIRA_TOKEN_STORED", "Jira erişim bilgileri MCP OAuth deposuna kaydedildi"
        )
        _trace(
            "MCP_TOKEN_ISSUED",
            "ITool için MCP access tokenı ve varsa refresh tokenı üretildi",
            hasRefreshToken=bool(token.refresh_token),
        )
        return token

    async def _is_revoked(self, upstream_id: str) -> bool:
        """Persist grant revocation across workers and in-flight refreshes."""
        return bool(
            await self._client_storage.get(
                key=upstream_id, collection="jiramcp-revoked-grants"
            )
        )

    async def load_access_token(self, token: str) -> FastMCPAccessToken | None:
        """Keep the validated MCP client identity after the upstream token swap."""
        validated = await super().load_access_token(token)
        if validated is None:
            _trace("MCP_ACCESS_REJECTED", "MCP tokenı doğrulanamadı")
            return None
        payload = self.jwt_issuer.verify_token(token)
        mapping = await self._jti_mapping_store.get(key=payload["jti"])
        if mapping is None or await self._is_revoked(mapping.upstream_token_id):
            return None
        _trace(
            "JIRA_TOKEN_RESOLVED",
            "MCP tokenı doğrulandı; bağlantının Jira tokenı çözüldü",
        )
        claims = dict(validated.claims or {})
        claims["jiramcp_grant_id"] = mapping.upstream_token_id
        claims["jiramcp_jti"] = payload["jti"]
        return FastMCPAccessToken.model_validate(
            validated.model_dump()
            | {"client_id": payload["client_id"], "claims": claims}
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        """Reject refreshes for a disconnected grant, including rotated tokens."""
        payload = self.jwt_issuer.verify_token(
            refresh_token.token,
            expected_token_use="refresh",  # noqa: S106
        )
        mapping = await self._jti_mapping_store.get(key=payload["jti"])
        if mapping is None or await self._is_revoked(mapping.upstream_token_id):
            raise TokenError("invalid_grant", "Connection has been revoked")
        _trace("MCP_REFRESH_START", "MCP ve Jira token yenileme işlemi başlatıldı")
        result = await super().exchange_refresh_token(client, refresh_token, scopes)
        _trace("MCP_REFRESH_READY", "Token yenileme tamamlandı")
        return result

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        """Revoke the MCP grant without affecting other application connections.

        Jira's own authorization is managed separately in Jira. Do not pass an
        MCP-issued token to Jira's token revocation endpoint.
        """
        if isinstance(token, RefreshToken):
            payload = self.jwt_issuer.verify_token(
                token.token,
                expected_token_use="refresh",  # noqa: S106
            )
            jti = payload["jti"]
            mapping = await self._jti_mapping_store.get(key=jti)
            upstream_id = mapping.upstream_token_id if mapping else None
        else:
            claims = token.claims or {}
            jti = claims.get("jiramcp_jti")
            upstream_id = claims.get("jiramcp_grant_id")
        _trace("REVOKE_START", "MCP bağlantı izni iptal ediliyor")
        if upstream_id:
            # A tombstone also blocks an in-flight refresh that restores storage.
            await self._client_storage.put(
                key=upstream_id,
                value={"revoked": True},
                collection="jiramcp-revoked-grants",
            )
            await self._upstream_token_store.delete(key=upstream_id)
        if jti:
            await self._jti_mapping_store.delete(key=jti)
        _trace("REVOKE_DONE", "MCP bağlantı izni iptal edildi")

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        for redirect_uri in client_info.redirect_uris or []:
            if _redirect_target(str(redirect_uri)) == self._proxy_callback_target:
                raise RegistrationError(
                    "invalid_redirect_uri",
                    "DCR redirect_uri must not target the OAuth proxy callback",
                )

        updates: dict[str, object] = {"response_types": ["code"]}

        if self._allowed_grant_types is not None:
            requested = list(client_info.grant_types or [])
            filtered = [gt for gt in requested if gt in self._allowed_grant_types]
            if requested and set(requested) - set(filtered):
                logger.warning(
                    "DCR requested unsupported grant types %s; enforcing %s",
                    sorted(set(requested) - set(filtered)),
                    self._allowed_grant_types,
                )
            if not filtered:
                filtered = list(self._allowed_grant_types)
            updates["grant_types"] = filtered

        if self._forced_scopes is not None:
            forced_scope = " ".join(self._forced_scopes).strip()
            updates["scope"] = forced_scope or None
            if client_info.scope and client_info.scope != forced_scope:
                logger.warning(
                    "DCR requested scope '%s'; enforcing '%s'",
                    client_info.scope,
                    forced_scope,
                )

        client_info = client_info.model_copy(update=updates)
        await super().register_client(client_info)


__all__ = ["HardenedOAuthProxy", "parse_env_list"]
