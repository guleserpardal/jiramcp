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
# FastMCP'nin varsayılanıyla aynı: görsel yalnız https/data, betik yok.
# form-action BİLEREK yok: Chrome form-action'ı formdan sonraki yönlendirme
# zincirinin TAMAMINA uygular (Chromium #40923007). Form kendi adresine gider
# ama onay sonrası 302 Jira'ya (başka origin) yönlenir; 'self' yazılırsa tarayıcı
# yönlendirmeyi engeller ve kullanıcı izin ekranında takılı kalır.
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
    read_only = _read_only()
    access_label = "Yalnız okuma" if read_only else "Okuma ve yazma"
    erisim = (
        "Yetkiniz olan projeleri ve Jira maddelerini görüntüleme. "
        "Madde oluşturma, değiştirme veya silme izni verilmez."
        if read_only
        else "Jira yetkileriniz ve verilen izin kapsamı içinde "
        "projeleri ve maddeleri görüntüleme ve değiştirme."
    )
    logo_html = (
        f'<img class="logo" src="{e(logo)}" alt="{e(org)}" />'
        if logo
        else f'<div class="org">{e(org)}</div>'
    )
    cimd = (
        f'<div class="ok">Uygulama alan adı: <strong>{e(cimd_domain)}</strong></div>'
        if is_cimd_client and cimd_domain
        else ""
    )
    destek = f'<p class="foot">Destek · {e(support)}</p>' if support else ""
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
<meta name="referrer" content="no-referrer">
{csp_meta}
<title>{e(app)} — Jira bağlantısı</title>
<style>
  :root {{ color-scheme: light; --navy:#102d55; --blue:#124b9a;
    --ink:#182c46; --muted:#62748a; --line:#e5ebf2; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; min-height:100vh; padding:36px 24px;
    background:radial-gradient(ellipse at 20% 0%,#e3edf8,transparent 60%),#f3f6fa;
    color:var(--ink); font:14px/1.6 "Segoe UI",system-ui,-apple-system,Arial,sans-serif;
    display:grid; place-items:center; }}
  .shell {{ width:100%; max-width:820px; }}
  .brand {{ display:flex; align-items:center; justify-content:space-between;
    gap:16px; padding:0 4px; margin-bottom:20px; }}
  .org {{ color:var(--navy); font-size:20px; font-weight:750; letter-spacing:-.5px; }}
  .logo {{ max-height:34px; max-width:190px; display:block; }}
  .internal {{ font-size:11px; color:#53677f; letter-spacing:1.5px;
    text-transform:uppercase; }}
  .card {{ background:white; border:1px solid #dfe7f0; border-radius:22px;
    box-shadow:0 22px 60px -30px #152d5555; overflow:hidden;
    display:grid; grid-template-columns:260px minmax(0,1fr); }}
  .overview {{ background:linear-gradient(145deg,#153963,#102844); color:white;
    padding:34px 28px; display:flex; flex-direction:column; position:relative; }}
  .eyebrow {{ color:#bdcde1; font-size:10px; letter-spacing:2px;
    text-transform:uppercase; font-weight:650; margin:0 0 28px; }}
  .apps {{ display:flex; align-items:center; gap:12px; margin-bottom:22px; }}
  .app-icon {{ width:52px; height:52px; border-radius:15px; display:grid;
    place-items:center; font-size:17px; font-weight:750; background:white;
    color:#163c6b; box-shadow:0 5px 18px #071b3633; }}
  .jira-icon {{ background:#2875ed; color:white; }}
  .arrow {{ color:#b9cce4; font-size:21px; }}
  .overview h2 {{ margin:0 0 6px; font-size:20px; line-height:1.35;
    overflow-wrap:anywhere; letter-spacing:-.3px; }}
  .overview p {{ color:#c3d1e2; margin:0; font-size:13px; }}
  .account-note {{ margin-top:auto; padding-top:42px; }}
  .account-note strong {{ display:block; color:#f0f5fc; font-size:12px;
    margin-bottom:5px; }}
  .account-note p {{ font-size:12px; line-height:1.7; }}
  .content {{ padding:34px 34px 26px; min-width:0; }}
  h1 {{ font-size:25px; line-height:1.25; letter-spacing:-.8px; margin:0 0 12px; }}
  .intro {{ color:var(--muted); margin:0 0 24px; font-size:13px; }}
  .intro strong {{ color:var(--ink); font-weight:650; }}
  .permission {{ padding:17px 18px; background:#f5f8fc; border:1px solid var(--line);
    border-radius:13px; margin-bottom:19px; }}
  .permission-head {{ display:flex; gap:10px; align-items:center; margin-bottom:7px; }}
  .dot {{ width:7px; height:7px; border-radius:50%; background:#287563; flex-shrink:0;
    }}
  .permission strong {{ font-size:13px; }}
  .permission p {{ margin:0; font-size:12px; color:#53677f; line-height:1.75; }}
  .assurances {{ display:grid; gap:14px; margin-bottom:22px; }}
  .assurance {{ display:flex; align-items:flex-start; gap:11px; }}
  .symbol {{ color:#356a9c; width:21px; height:21px; flex-shrink:0; margin-top:2px; }}
  .assurance strong {{ display:block; font-size:12px; margin-bottom:2px; }}
  .assurance p {{ color:var(--muted); font-size:12px; margin:0; line-height:1.6; }}
  .next {{ border-top:1px solid var(--line); padding-top:17px; margin:0 0 17px;
    color:var(--muted); font-size:12px; }}
  .next strong {{ color:var(--ink); font-weight:600; }}
  .actions {{ display:flex; gap:10px; }}
  button {{ min-height:44px; border:1px solid #dbe3ec; border-radius:9px;
    font:600 13px/1.3 "Segoe UI",system-ui,sans-serif; cursor:pointer;
    padding:12px 16px; background:white; color:#445871; }}
  .approve {{ flex:1; color:white; background:var(--blue); border-color:var(--blue);
    box-shadow:0 4px 10px #124b9a15; }}
  .approve:hover {{ background:#0c3d80; }}
  button:hover {{ border-color:#9baec4; }}
  button:focus-visible,summary:focus-visible {{ outline:3px solid #e4ab39;
    outline-offset:4px; }}
  details {{ margin-top:18px; font-size:11px; color:var(--muted); }}
  summary {{ cursor:pointer; width:fit-content; padding:3px 0; }}
  .technical {{ margin:10px 0 0; border-left:2px solid var(--line); padding-left:12px;
    }}
  .technical dt {{ font-weight:650; margin-top:7px; }}
  .technical dd {{ margin:0; overflow-wrap:anywhere; }}
  .ok {{ margin:0 0 16px; color:#385c7f; font-size:11px; overflow-wrap:anywhere; }}
  .foot {{ text-align:center; color:#738196; font-size:11px; margin:17px 0 0; }}
  @media(max-width:640px) {{
    body {{ padding:24px 16px; place-items:start center; }}
    .brand {{ margin-bottom:17px; }} .org {{ font-size:18px; }}
    .internal {{ font-size:9px; letter-spacing:.8px; }}
    .card {{ grid-template-columns:minmax(0,1fr); border-radius:18px; }}
    .overview {{ padding:22px 24px; }} .eyebrow {{ margin-bottom:16px; }}
    .apps {{ margin-bottom:13px; }} .app-icon {{ width:42px; height:42px;
      border-radius:12px; }}
    .overview h2 {{ font-size:18px; }} .account-note {{ display:none; }}
    .content {{ padding:26px 24px; }} h1 {{ font-size:24px; }}
  }}
  @media(prefers-reduced-motion:no-preference) {{ button {{ transition:background
    .15s,border-color .15s; }} }}
</style>
</head>
<body>
<main class="shell">
  <header class="brand">{logo_html}<span class="internal">Uygulama
    bağlantısı</span></header>
  <section class="card" aria-labelledby="consent-title">
    <aside class="overview" aria-label="Bağlantı özeti">
      <div class="eyebrow">Jira bağlantısı</div>
      <div class="apps" aria-hidden="true">
        <span class="app-icon">{e(app[:2].upper())}</span><span class="arrow">→</span>
        <span class="app-icon jira-icon">J</span>
      </div>
      <h2>{e(app)}</h2>
      <p>Jira hesabınıza bağlanır.</p>
      <div class="account-note"><strong>Yetkileriniz geçerlidir.</strong>
        <p>Bağlantı, Jira hesabınızın erişim sınırları içinde çalışır.</p></div>
    </aside>
    <div class="content">
      <h1 id="consent-title">Jira hesabınızı bağlayın</h1>
      <p class="intro"><strong>{e(app)}</strong>, Jira hesabınıza erişmek için
        izninizi istiyor.</p>
      {cimd}
      <section class="permission" aria-label="İstenen erişim">
        <div class="permission-head"><span class="dot"
          aria-hidden="true"></span><strong>{access_label}</strong></div>
        <p>{erisim}</p>
      </section>
      <div class="assurances">
        <div class="assurance">
          <svg class="symbol" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            stroke-width="1.5" aria-hidden="true"><rect x="5" y="10" width="14"
            height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/></svg>
          <div><strong>Jira erişiminiz ayrı yönetilir</strong><p>Jira erişim
            bilgilerinizi bağlantı sunucusu yönetir.</p></div>
        </div>
        <div class="assurance">
          <svg class="symbol" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            stroke-width="1.5" aria-hidden="true"><path d="M4 10a8 8 0 1 1 1 8M4
            4v6h6"/></svg>
          <div><strong>Kontrol sizde</strong><p>Bağlantıyı uygulamadan kaldırabilir,
            Jira hesabınızdaki uygulama izinlerini yönetebilirsiniz.</p></div>
        </div>
      </div>
      <p class="next"><strong>Sonraki adım:</strong> Jira'ya yönlendirileceksiniz.
        Gerekirse hesabınıza giriş yapıp erişimi onaylayın.</p>
      <form id="consentForm" method="POST" action="">
        <input type="hidden" name="txn_id" value="{e(txn_id)}" />
        <input type="hidden" name="csrf_token" value="{e(csrf_token)}" />
        <input type="hidden" name="submit" value="true" />
        <div class="actions">
          <button type="submit" name="action" value="deny">Vazgeç</button>
          <button type="submit" name="action" value="approve" class="approve">İzin ver
            ve devam et <span aria-hidden="true">→</span></button>
        </div>
      </form>
      <details><summary>Bağlantı ayrıntıları</summary><dl class="technical">
        <dt>Uygulama kimliği</dt><dd>{e(client_id)}</dd>
        <dt>Dönüş adresi</dt><dd>{e(redirect_uri)}</dd>
        <dt>İzin kapsamı</dt><dd>{e(", ".join(scopes) if scopes else "—")}</dd>
      </dl></details>
    </div>
  </section>
  {destek}
</main>
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
