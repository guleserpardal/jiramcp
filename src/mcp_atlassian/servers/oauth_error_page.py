"""Türkçe hata sayfası: Jira yetkilendirmesi uygulamaya geri iletilemediğinde.

Normalde Jira'nın hatası (ör. kişi "reddet"e bastı) bağlanan uygulamanın dönüş
adresine iletilir ve uygulama kendi mesajını gösterir. Bu sayfa yalnız hangi
uygulamaya döneceği bulunamadığında (işlem süresi dolmuş, tarayıcı farklı, ya da
aynı tarayıcıda birden çok bekleyen bağlantı) çıkar. Betik içermez (CSP).
"""

from __future__ import annotations

import html
import os

from mcp_atlassian.servers.consent_page import CSP_POLICY, DEFAULT_ORG

_MESSAGES = {
    "access_denied": (
        "Jira erişimine izin vermediniz",
        "Bağlantı kurulmadı. Bu pencereyi kapatıp uygulamaya dönebilirsiniz.",
    ),
}
_DEFAULT = (
    "Jira bağlantısı tamamlanamadı",
    "Bu pencereyi kapatıp uygulamadan yeniden bağlanmayı deneyin.",
)


def create_idp_error_html_tr(error: str) -> str:
    """Render the page for an upstream (Jira) authorization error.

    Args:
        error: OAuth ``error`` code returned by Jira (shown escaped).

    Returns:
        Complete HTML document.
    """
    e = html.escape
    org = os.getenv("MCP_CONSENT_ORG", "").strip() or DEFAULT_ORG
    title, body = _MESSAGES.get(error, _DEFAULT)
    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<meta http-equiv="Content-Security-Policy" content="{e(CSP_POLICY)}">
<title>{e(title)}</title>
<style>
  :root {{ color-scheme: light; --brand:#b6007a; --ink:#1f1a2e; --muted:#6b6577;
    --line:#ebe7ee; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; min-height:100vh; display:flex; align-items:center;
    justify-content:center; padding:24px 16px; color:var(--ink);
    font:14px/1.5 "Segoe UI", system-ui, -apple-system, Roboto, Arial, sans-serif;
    background:radial-gradient(circle at top left, rgb(182 0 122 / 9%),
      transparent 32rem), #f6f4f7; }}
  .card {{ width:100%; max-width:480px; background:#fff; border:1px solid var(--line);
    border-radius:16px; box-shadow:0 12px 32px rgba(31,26,46,.08); }}
  .top {{ padding:16px 24px; border-bottom:1px solid var(--line); font-weight:800;
    font-size:17px; color:var(--brand); }}
  .body {{ padding:24px; }}
  h1 {{ font-size:20px; line-height:1.3; margin:0 0 8px; }}
  p {{ margin:0; color:#4a4458; }}
  code {{ font-size:12px; color:var(--muted); }}
  .code {{ margin-top:16px; font-size:12px; color:var(--muted); }}
</style>
</head>
<body>
<main class="card" aria-labelledby="t">
  <div class="top">{e(org)}</div>
  <div class="body">
    <h1 id="t">{e(title)}</h1>
    <p>{e(body)}</p>
    <p class="code">Hata kodu: <code>{e(error)}</code></p>
  </div>
</main>
</body>
</html>"""
