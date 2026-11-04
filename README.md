# jiramcp — Kurum içi Jira MCP sunucusu

Jira (ve Confluence) için kurum içi bir [Model Context Protocol](https://modelcontextprotocol.io)
sunucusu. ITool ve kurum içi chatbot Jira'ya bu sunucu üzerinden, **kişinin kendi Jira
kimliğiyle** erişir.

```
Tarayıcı ──► ITool / Chatbot ──Bearer <MCP token>──► jiramcp ──Bearer <kişinin Jira token'ı>──► Jira
```

- Jira token'ları (erişim + yenileme) **yalnız bu sunucuda**, şifreli tutulur.
- İstemciler (ITool, chatbot) bu sunucudan kendi kısa ömürlü token'ını alır; Jira token'ını görmez.
- Kişi bağlantıyı Jira → Profil → **Authorized applications** ekranından iptal eder.

## Kurulum (Windows, uv olmadan)

Python 3.10 ya da üstü gerekir.

```bat
git clone https://github.com/guleserpardal/jiramcp C:\jiramcp
cd C:\jiramcp
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

`requirements.txt`, `uv.lock`'taki sabit sürümlerin pip karşılığıdır.

## Ayar

`mcp.env.example` dosyasını `mcp.env` adıyla kopyalayıp doldurun (`mcp.env` repoya konmaz):

- `JIRA_URL` — Jira adresi
- `ATLASSIAN_OAUTH_CLIENT_ID` / `_SECRET` — Jira yöneticisinin açtığı **Application Link
  (External application → Incoming, OAuth 2.0)** kaydının değerleri
- `ATLASSIAN_OAUTH_REDIRECT_URI` — kayıttaki Redirect URL ile birebir aynı
  (`http://localhost:9000/callback`)
- `ATLASSIAN_OAUTH_ALLOWED_CLIENT_REDIRECT_URIS` — bağlanacak istemcilerin dönüş adresleri

## Çalıştırma

```bat
cd C:\jiramcp
set PYTHONPATH=C:\jiramcp\src
.venv\Scripts\python -c "from mcp_atlassian import main; main()" --env-file mcp.env --transport streamable-http --host 127.0.0.1 --port 9000
```

Kontrol: `http://localhost:9000/.well-known/oauth-authorization-server` JSON dönmeli;
kimliksiz `POST http://localhost:9000/mcp` **401** dönmeli.

Windows komut penceresinde **Hızlı Düzenleme Modu**'nu kapatın (pencere başlığı → Özellikler):
pencereye tıklamak sunucuyu dondurur.

## Onay ekranı

İstemci ilk bağlandığında kişiye Türkçe, kurum adıyla bir onay ekranı gösterilir
(`src/mcp_atlassian/servers/consent_page.py`). Ardından Jira'nın kendi onay ekranı gelir.

| Değişken | Ne işe yarar |
| --- | --- |
| `MCP_CONSENT_ORG` | Ekrandaki kurum adı (varsayılan `QNB Sigorta`) |
| `MCP_CONSENT_LOGO_FILE` | Logo dosyası (PNG/SVG/JPG, ≤ 512 KB); sayfaya gömülür |
| `MCP_CONSENT_SUPPORT` | Alt bilgideki iletişim |
| `MCP_CONSENT_PAGE=fastmcp` | Kütüphanenin özgün (İngilizce) ekranına döner |

## Token'lar nerede

Sunucunun çalıştığı makinede, şifreli dosyalar olarak:

- Windows: `%LOCALAPPDATA%\fastmcp\oauth-proxy\<kod>\`
- Linux: `~/.local/share/fastmcp/oauth-proxy/<kod>/`

Şifreleme anahtarı Jira client secret'tan türetilir; secret değişirse herkes bir kez
yeniden bağlanır. Birden çok kopya çalışacaksa ortak bir Redis deposu gerekir
(`ATLASSIAN_OAUTH_CLIENT_STORAGE_MODE`).

## Güvenlik ayarları

`READ_ONLY_MODE=true` yazma araçlarını kapatır; `MCP_ALLOWED_URL_DOMAINS` sunucunun
yalnız Jira'ya istek atmasını sağlar; sunucu `127.0.0.1`'e bağlanır, dışarıya TLS
sonlandıran ters vekil arkasından açılır. Ayrıntılı örnek: `hardened.env.example`.

## Geliştirme

```bash
uv sync --frozen --dev
uv run pytest tests/unit -q
uv run ruff check src tests && uv run mypy src
```

Bağımlılık değişince `requirements.txt` yeniden üretilir:

```bash
uv export --frozen --no-dev --no-emit-project --no-hashes -o requirements.txt
```

## Lisans

MIT lisanslı açık kaynak bir projeden türetilmiştir; lisans ve telif bildirimleri
[LICENSE](LICENSE) dosyasındadır.


## Bağlantıyı kaldırma ve dağıtım

OAuth metadata `/revoke` adresini sunar. İstemci, kendi MCP erişim veya yenileme
tokenını bu adrese göndererek yalnız o bağlantının iznini kaldırabilir. Aynı
bağlantıya ait erişim ve yenileme tokenları engellenir; başka istemcilerin
bağlantıları korunur. Devam eden yenilemelerin bağlantıyı geri getirmemesi için
iptal bilgisi ortak OAuth deposunda tutulur. Bu işlem Jira hesabındaki genel
Application Link iznini kaldırmaz; o izin Jira profilinden yönetilir.

`ATLASSIAN_OAUTH_PROXY_ENABLE=true` iken zorunlu OAuth ayarları eksikse sunucu
başlamaz; sessizce yetkilendirmesiz çalışma kipine düşmez.

Varsayılan FastMCP deposu şifrelidir. Özel `client_storage` fabrikası kullanılırsa
şifreleme, erişim kontrolü ve yedekleme fabrika sahibinin sorumluluğundadır. Çok
kopyalı kurulumda OAuth deposu ve şifreleme/imzalama anahtarı tüm kopyalar için
uyumlu ve ortak yönetilmelidir. İptal işaretleri de aynı depoda korunmalıdır.

Güncellemede önce bu sunucuyu, sonra ITool istemcisini yeniden başlatın. ITool'un
kişisel MCP bağlantısı mevcut diğer Jira ekranlarını kendiliğinden taşımaz.


## OAuth adım logları

`MCP_OAUTH_TRACE=true` ile yeniden başlatın. `-vv` gerekmez. İzin ekranı,
Jira'ya yönlendirme, Jira token HTTP isteği/yanıtı, SDK PKCE doğrulaması, ayrı
MCP tokenı üretimi, yenileme ve iptal adımları konsolda görünür. ITool'da
`JIRA_MCP_TRACE=true` ayarıyla aynı akışı istemci tarafında izleyin. Ortak
`flowId` yalnız log etiketidir; doğrulama veya kullanıcı kimliği değildir.
Kod/token/state/verifier değerleri, HTTP gövdeleri ve URL query değerleri
trace'e yazılmaz. `MCP_PKCE_VERIFIED`, framework kontrolü geçtikten sonra yazılır;
Jira'nın iç PKCE hesabı sunucuda gözlemlenemez, başarılı HTTP dönüşü görülür.
Özel OAuth deposu kullanıldığında şifreleme fabrika sahibinin sorumluluğundadır.
