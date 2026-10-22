# Canonical yazar profili (Who am I)

Blog sahibi Berkay Kaplan / MrBekoX hakkında yayınlanması onaylanmış **tek** çalışma zamanı
kaynağı. Python agent (profil RAG), .NET backend (`GET /api/v1/profile`, sunum guard'ı,
kabulde sürüm pinleme) ve `/about` sayfası bu dizindeki aynı veriyi kullanır. Ayrı biyografi
kopyası tutulmaz.

| Dosya | Amaç |
| --- | --- |
| `manifest.json` | `profile_id`, `revision`, `content_hash` (= `profile.json` ham byte SHA-256), `status` (`public`), `approved`, tarihler, ham kaynak özeti |
| `profile.json` | Bölümler (`section_id` = `/about` anchor), TR/EN başlık ve alias'lar, beyan meta verisi (`claim.as_of`, `temporal`, `status`), notlar, gizlilik yapılandırması (`privacy`), dönüşüm/çelişki kaydı (`provenance`) |
| `source/author-profile.source.md` | Kullanıcının verdiği ham biyografi, birebir (SHA-256 `266a5bcb…87aac`) |
| `tools/update_manifest.py` | `--check` tutarlılık denetimi, `--bump` yeni revision + hash |

## Tarih ve doğrulama anlamı

- `source.received_at = 2026-10-21`: kaynağın bu çalışma için okunduğu tarih.
- `content_created_at`: çalışma sürümünün oluşturulma zamanı.
- `verified_at = null`: iddialar bağımsız doğrulanmadı (`self_reported_not_independently_verified`).
- "Şu an", sürüm, release, lisans incelemesi ve canlı test ifadeleri `claim.as_of` tarihli
  beyanlardır. Agent bunları güncel internet bilgisi gibi sunmaz.
- Ham kaynaktaki blog ajanı mimarisi (FastAPI/ChromaDB) bu deponun kodundan farklıdır. Ham metin
  değiştirilmedi; ilgili bölümlerde not ve `provenance.transformations` T05 kaydı vardır.

## Güncelleme (operatör)

1. `profile.json` dosyasını düzenle: bölüm ekle, düzelt veya kaldır. Ham kaynak değiştiyse
   `source/` altına koy ve manifest'teki `source.sha256` ile `provenance.raw_sha256` alanlarını
   güncelle.
2. `python src/content/author-profile/tools/update_manifest.py --bump` çalıştır. Revision bir
   artar; `content_hash` ve `content_created_at` yenilenir.
3. `python src/content/author-profile/tools/update_manifest.py --check` sonucu tutarlı olmalı.
   Ardından Python, .NET ve frontend testlerini çalıştır.
4. Backend ve agent servislerini **aynı commit'ten** derleyip dağıt. Yeni sürüm, okuyucular hash'i
   doğruladığı anda etkin olur.
5. Etkiler:
   - Eski sürüme pinlenmiş sonuçlar GET, status, replay ve SignalR sunumlarında "profil bilgisi
     güncellendi" olarak maskelenir.
   - Devam eden eski run, worker'daki kaynak pinlenen sürümle uyuşmazsa `config_error` ile biter.
     Worker sessizce sürüm değiştirmez.
6. Profili yayından kaldırmak için `manifest.json` içinde `"status": "withdrawn"` (veya
   `"approved": false`) yap ve `--bump` çalıştır. Bu durumda:
   - `/about` gövde göstermez;
   - `GET /api/v1/profile` 503 döner;
   - `who_am_i` istekleri kapasite hatası alır;
   - eski profil cevapları maskelenir.

Dosyalar `.gitattributes` içinde `-text` olarak işaretlidir. Satır sonu dönüşümü hash'i bozmaz.
Bir editör CRLF/LF değiştirirse okuyucular açıkça hata verir; düzeltmek için `--bump` çalıştır.
