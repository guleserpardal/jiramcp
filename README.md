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
C:\jiramcp\mcp.bat --env-file mcp.env
```

`mcp.bat` `PYTHONPATH`'i ayarlayıp `.venv`'deki Python ile `mcp_atlassian.main()`'i
çağırır; verilen bütün seçenekleri olduğu gibi iletir. Taşıma, adres ve port
`mcp.env`'den gelir (`TRANSPORT=streamable-http`, `HOST`, `PORT`). Elle karşılığı:

```bat
cd C:\jiramcp
set PYTHONPATH=C:\jiramcp\src
.venv\Scripts\python -c "from mcp_atlassian import main; main()" --env-file mcp.env --transport streamable-http --host 127.0.0.1 --port 9000
```

Kontrol: `http://localhost:9000/.well-known/oauth-authorization-server` JSON dönmeli;
kimliksiz `POST http://localhost:9000/mcp` **401** dönmeli.

Windows komut penceresinde **Hızlı Düzenleme Modu**'nu kapatın (pencere başlığı → Özellikler):
pencereye tıklamak sunucuyu dondurur.

## Araçları elle denemek (MCP Inspector)

OAuth olmadan, kendi Jira kişisel token'ınızla yerel bir kopya açıp araç listesini
(`tools/list`) görmek ve araç çağırmak (`tools/call`) için:

1. `local.env.example` dosyasını `local.env` adıyla kopyalayıp `JIRA_PERSONAL_TOKEN`'ı
   doldurun (`local.env` repoya konmaz).
2. `npx @modelcontextprotocol/inspector` çalıştırın; tarayıcıda açılan ekranda
   **Transport Type** `STDIO`, **Command** `C:\jiramcp\mcp.bat`, **Arguments**
   `--env-file C:\jiramcp\local.env`.
3. **Connect** → **Tools** → **List Tools**. `READ_ONLY_MODE=true` iken yazma araçları
   listede görünmez.

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
yeniden bağlanır. Birden çok kopya çalışacaksa ortak depo gerekir: PostgreSQL (aşağıda).

## PostgreSQL deposu

Token'lar dosya yerine PostgreSQL'de tutulabilir. Üç tablo vardır, tablolar Alembic ile
yönetilir (migration'lar paketin içinde: `src/mcp_atlassian/db/migrations/`):

| Tablo | İçerik |
| --- | --- |
| `mcp_oauth_kv` | FastMCP OAuth durumu (istemci kayıtları, Jira token'ları, refresh token'lar). Değerler **şifreli**. FastMCP koleksiyonları ayrı tablo değil, `collection` kolonudur. |
| `mcp_grant_index` | Hangi izin kime / hangi uygulamaya ait. **Token içermez.** `grant_id` = `mcp_oauth_kv`'deki `mcp-upstream-tokens` satırının `key`'i (mantıksal eşleme, FK değil). |
| `mcp_tool_call_audit` | Araç çağrısının sonucu ve süresi; argüman değeri yazılmaz. Saklama 180 gün. |

1. Tabloları açın (veritabanı boş olabilir; başka uygulamaların tablolarına dokunulmaz,
   sürüm tablosu `mcp_alembic_version`):

   ```bat
   set MCP_STORAGE_PG_URL=postgresql://kullanici:parola@sunucu:5432/veritabani
   .venv\Scripts\python -m mcp_atlassian.db upgrade
   ```

   SQL'i bağlanmadan görmek (DBA'ya vermek için): `python -m mcp_atlassian.db sql`.
   Docker: `docker run --rm -e MCP_STORAGE_PG_URL=… --entrypoint python <imaj> -m mcp_atlassian.db upgrade`.

2. `mcp.env`'e ekleyin:

   ```ini
   ATLASSIAN_OAUTH_CLIENT_STORAGE_MODE=factory
   ATLASSIAN_OAUTH_CLIENT_STORAGE_FACTORY=mcp_atlassian.servers.pg_storage:build_storage
   MCP_STORAGE_PG_URL=postgresql://kullanici:parola@sunucu:5432/veritabani
   ```

   Ayrı bir şifreleme anahtarı **yoktur**: anahtar `ATLASSIAN_OAUTH_CLIENT_SECRET`'tan,
   FastMCP'nin dosya deposuyla birebir aynı yolla türetilir. Secret değişirse kayıtlar
   okunamaz, "yok" sayılır ve herkes bir kez yeniden bağlanır (hata vermez). Birden çok
   MCP kopyası aynı tabloyu paylaşabilir; hepsinde aynı secret olmalı. Veritabanını ele
   geçiren secret olmadan token okuyamaz.

3. Temizlik (cron / pg_cron):

   ```sql
   -- saatte bir: süresi dolan OAuth kayıtları
   DELETE FROM mcp_oauth_kv WHERE expires_at IS NOT NULL AND expires_at < now();
   -- günde bir: denetim kayıtları 180 günden eski
   DELETE FROM mcp_tool_call_audit WHERE called_at < now() - interval '180 days';
   ```

Geçişte dosyadaki eski kayıtlar taşınmaz; kullanıcılar bir kez yeniden bağlanır.

Yeni migration (geliştirme): şemayı `src/mcp_atlassian/db/schema.py`'de değiştirin,
sonra `uv run alembic revision --autogenerate -m "aciklama"` ve dosyayı elle gözden
geçirin. `uv run alembic check` şema ile migration'ların uyumunu denetler. Gerçek
veritabanına karşı testler:
`MCP_TEST_PG_URL=postgresql://… uv run pytest tests/integration/test_mcp_pg_storage.py --integration`
(o veritabanındaki `mcp_` tabloları silinip yeniden açılır).

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
