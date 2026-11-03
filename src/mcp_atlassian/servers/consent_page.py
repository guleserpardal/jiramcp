"""Kurum onay ekranı (OAuth vekili) — Türkçe, markalı.

FastMCP'nin OAuth vekili, bir istemci (ITool, chatbot…) kişi adına bağlanmak
istediğinde bir onay ekranı gösterir. Bu modül o ekranın HTML'ini kendi
şablonumuzla üretir; akış, form alanları (txn_id, csrf_token, submit,
action=approve|deny) ve güvenlik politikası FastMCP'ninkiyle aynıdır — yalnız
görünüm ve metin değişir.

Ortam değişkenleri (hepsi isteğe bağlı):
    MCP_CONSENT_PAGE        "fastmcp" → kütüphanenin özgün ekranı (bu modül devre dışı)
    MCP_CONSENT_ORG         Ekranda yazan kurum adı (varsayılan "QNB Sigorta")
    MCP_CONSENT_LOGO_FILE   Logo dosyası (PNG/SVG/JPG); sayfaya gömülür (dış istek yok)
    MCP_CONSENT_SUPPORT     Alt bilgide yazan iletişim (ör. "Hayat Yazılım Geliştirme")
"""

from __future__ import annotations

import base64
import html
import logging
import os
from pathlib import Path

logger = logging.getLogger("mcp-atlassian.server.consent_page")

DEFAULT_ORG = "QNB Sigorta"
MAX_LOGO_BYTES = 512 * 1024
_LOGO_TYPES = {
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}
# FastMCP'nin varsayılanıyla aynı: form kendi adresine gönderilir, görsel yalnız
# https/data, betik yok.
CSP_POLICY = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src https: data:; "
    "base-uri 'none'"
)


def _logo_data_uri(path: str | None) -> str | None:
    """Logo dosyasını data URI'ye çevirir; okunamazsa None (ekran logosuz çizilir)."""
    if not path:
        return None
    p = Path(path)
    mime = _LOGO_TYPES.get(p.suffix.lower())
    if not mime:
        logger.warning("MCP_CONSENT_LOGO_FILE tanınmayan uzantı: %s", p.suffix)
        return None
    try:
        data = p.read_bytes()
    except OSError as exc:
        logger.warning("MCP_CONSENT_LOGO_FILE okunamadı: %s", exc)
        return None
    if len(data) > MAX_LOGO_BYTES:
        logger.warning("MCP_CONSENT_LOGO_FILE çok büyük (%d bayt)", len(data))
        return None
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _read_only() -> bool:
    return os.getenv("READ_ONLY_MODE", "false").strip().lower() in {"1", "true", "yes"}


def create_consent_html_tr(
    *,
    client_id: str,
    redirect_uri: str,
    scopes: list[str],
    txn_id: str,
    csrf_token: str,
    client_name: str | None = None,
    title: str = "",
    server_name: str | None = None,
    server_icon_url: str | None = None,
    server_website_url: str | None = None,
    client_website_url: str | None = None,
    csp_policy: str | None = None,
    is_cimd_client: bool = False,
    cimd_domain: str | None = None,
) -> str:
    """FastMCP ``create_consent_html`` ile aynı imza; Türkçe kurum ekranı döner."""
    e = html.escape
    org = os.getenv("MCP_CONSENT_ORG", "").strip() or DEFAULT_ORG
    support = os.getenv("MCP_CONSENT_SUPPORT", "").strip()
    logo = _logo_data_uri(os.getenv("MCP_CONSENT_LOGO_FILE"))
    app = client_name or client_id
    erisim = (
        "Jira'da <strong>yalnız okuma</strong>: senin görebildiğin projeler ve "
        "maddeler. Madde oluşturma ya da değiştirme yapılamaz."
        if _read_only()
        else "Jira'da senin yetkinle <strong>okuma ve yazma</strong>: senin "
        "görebildiğin ve değiştirebildiğin projeler ve maddeler."
    )
    logo_html = (
        f'<img class="logo" src="{e(logo)}" alt="{e(org)}" />'
        if logo
        else f'<div class="org">{e(org)}</div>'
    )
    cimd = (
        f'<div class="ok">Doğrulanmış alan adı: <strong>{e(cimd_domain)}</strong></div>'
        if is_cimd_client and cimd_domain
        else ""
    )
    destek = f'<p class="foot">Sorular için: {e(support)}</p>' if support else ""
    policy = CSP_POLICY if csp_policy is None else csp_policy
    csp_meta = (
        f'<meta http-equiv="Content-Security-Policy" content="{e(policy)}">'
        if policy
        else ""
    )
    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{csp_meta}
<title>{e(app)} — Jira erişim onayı</title>
<style>
  :root {{ --mavi: #0b3d91; --metin: #1f2937; --soluk: #6b7280;
           --cizgi: #e5e7eb; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: #f3f5f9; color: var(--metin);
         font: 15px/1.55 "Segoe UI", system-ui, -apple-system, Arial, sans-serif; }}
  .kart {{ max-width: 520px; margin: 48px auto; background: #fff;
          border-radius: 14px; padding: 28px 30px;
          box-shadow: 0 10px 30px rgba(15, 23, 42, .08); }}
  .logo {{ max-height: 44px; max-width: 220px; display: block; margin-bottom: 18px; }}
  .org {{ font-weight: 700; color: var(--mavi); letter-spacing: .3px;
         margin-bottom: 18px; }}
  h1 {{ font-size: 20px; margin: 0 0 6px; }}
  .alt {{ color: var(--soluk); margin: 0 0 18px; }}
  ul {{ padding-left: 18px; margin: 0 0 18px; }}
  li {{ margin-bottom: 8px; }}
  .ok {{ background: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 8px;
        padding: 8px 12px; margin-bottom: 14px; font-size: 14px; }}
  .dugmeler {{ display: flex; gap: 10px; margin-top: 8px; }}
  button {{ flex: 1; font: inherit; font-weight: 600; padding: 11px 14px;
           border-radius: 8px; cursor: pointer; border: 1px solid var(--cizgi);
           background: #fff; color: var(--metin); }}
  button.izin {{ background: var(--mavi); border-color: var(--mavi); color: #fff; }}
  details {{ margin-top: 18px; color: var(--soluk); font-size: 13px; }}
  details div {{ margin-top: 6px; word-break: break-all; }}
  .foot {{ color: var(--soluk); font-size: 13px; margin: 14px 0 0; }}
</style>
</head>
<body>
<div class="kart">
  {logo_html}
  <h1>{e(app)}, Jira hesabına erişmek istiyor</h1>
  <p class="alt">{e(org)} kurum içi Jira bağlantı sunucusu</p>
  {cimd}
  <ul>
    <li><strong>Ne izni veriyorsun:</strong> {erisim}</li>
    <li><strong>Nerede tutulur:</strong> Erişim anahtarın yalnız şirket içindeki bu
      sunucuda, şifreli tutulur. {e(app)} anahtarını görmez.</li>
    <li><strong>Nasıl geri alırsın:</strong> İstediğin zaman {e(app)} menüsünden ya da
      Jira → Profil → Authorized applications ekranından kaldırabilirsin.</li>
  </ul>
  <p class="alt">İzin verince Jira'nın kendi onay ekranı da açılır; orada da
    onaylaman gerekir.</p>
  <form id="consentForm" method="POST" action="">
    <input type="hidden" name="txn_id" value="{e(txn_id)}" />
    <input type="hidden" name="csrf_token" value="{e(csrf_token)}" />
    <input type="hidden" name="submit" value="true" />
    <div class="dugmeler">
      <button type="submit" name="action" value="deny">Vazgeç</button>
      <button type="submit" name="action" value="approve" class="izin">İzin ver</button>
    </div>
  </form>
  <details>
    <summary>Teknik ayrıntılar</summary>
    <div>Uygulama: {e(app)} ({e(client_id)})</div>
    <div>Dönüş adresi: {e(redirect_uri)}</div>
    <div>Kapsam: {e(", ".join(scopes) if scopes else "—")}</div>
  </details>
  {destek}
</div>
</body>
</html>"""


def install_consent_page() -> bool:
    """FastMCP'nin onay ekranı üreticisini bizimkiyle değiştirir.

    FastMCP ``consent`` modülü üreticiyi modül düzeyinde içe aktarıp çağırdığı
    için modüldeki adı değiştirmek yeterlidir; akışa dokunulmaz.

    Returns:
        True if the custom page is active.
    """
    if os.getenv("MCP_CONSENT_PAGE", "").strip().lower() == "fastmcp":
        return False
    from fastmcp.server.auth.oauth_proxy import consent as consent_module

    if not hasattr(consent_module, "create_consent_html"):
        logger.warning(
            "FastMCP onay modülünde create_consent_html yok; özgün ekran kullanılıyor"
        )
        return False
    consent_module.create_consent_html = create_consent_html_tr  # type: ignore[assignment]
    return True
