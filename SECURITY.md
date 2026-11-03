# Güvenlik

Bu sunucu kişilerin Jira erişim token'larını tutar. Bir güvenlik açığı fark ederseniz
**herkese açık issue açmayın**; Hayat Yazılım Geliştirme ekibine ve kurum Bilgi Güvenliği
birimine doğrudan bildirin.

Bildirimde şunlar olsun: etkilenen sürüm/commit, açığın tarifi, yeniden üretme adımları,
olası etki.

Temel kurallar:

- `mcp.env` ve Jira client secret repoya konmaz.
- Sunucu `127.0.0.1`'e bağlanır; dışarıya yalnız TLS sonlandıran ters vekil arkasından açılır.
- `READ_ONLY_MODE=true` ve `ATLASSIAN_OAUTH_REQUIRE_CONSENT=true` varsayılan kalır.
- `ATLASSIAN_OAUTH_ALLOWED_CLIENT_REDIRECT_URIS` joker içermez.
