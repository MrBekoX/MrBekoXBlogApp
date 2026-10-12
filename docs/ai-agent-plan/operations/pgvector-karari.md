# pgvector kararı — B11 (uygulanmadı; operasyon kararı olarak belgelendi)

Görev metni: "compose'da postgres yerine pgvector/pgvector imgesine geçiş +
A3 adaptörünün gerçek entegrasyon testi DÜŞÜK RİSKLİyse uygula; değilse B11
raporunda net operasyon kararı olarak belgele (adımlar + rollback). Yarı-
fabricate yasak: uygulanmadıysa 'uygulanmadı' yaz."

## Karar: UYGULANMADI — düşük riskli koşul sağlanmadı

Kanıtlar (dosya+satır, B11 incelemesi):

1. **Adaptör gerçek değil:** `app/agent_core/content/pgvector.py:69-70` —
   `PgvectorContentIndex.__init__` **her koşumda `PortError` yükseltir**.
   Modül docstring'i açıkça "gerçek veritabanı bağlantısı kurmaz" der.
   `PgvectorContentIndexStore` bir Protocol'dur (iskelet sözleşmesi);
   `upsert_article_chunks`/`search_hybrid` gerçekleştirimİ YOKTUR.
2. **Sürücü bağımlılığı yok:** `pyproject.toml`'da asyncpg/alembic/aio-pika
   vardır; pgvector'a özel sürücü (pgvector python paketi veya psycopg)
   YOKTUR — ve pyproject A2 sahipliğindedir (B11 dosya sahipliği dışı).
3. **Gerçek embedding sağlayıcısı yok:** ortam kuralı; `vector(N)` boyutu
   `EmbeddingModelConfig.dimensions` ile kilitlenir
   (`content/pgvector_schema.sql:35-36`) — gerçek model olmadan kolon boyutu
   bile üretim değerine bağlanamaz.
4. **`agent.content_chunk` tablosu hiç yaratılmadı:** Alembic zinciri 0001→0003
   içeriğinde content_chunk yoktur; şema SQL'i "B8 İÇERİK SENKRONUNA KADAR
   ÇALIŞTIRILMAZ" notuyla belge düzeyinde bekler.

İmge geçişi TEK BAŞINA yarı-iş olurdu: extension yüklü bir postgres, onu
kullanan hiçbir kod olmadan çalışır durum değişikliğidir (ayıp değil ama
kazanç da yok) ve A3 entegrasyon testi olmadan "gerçek pgvector" iddiası
fabricate olurdu.

## Uygulama yolu (karar alındığında izlenecek adımlar)

1. **Adaptör gerçekleştirimi (B8/A3 sahipliğiyle):** `pgvector.py` Protocol'unu
   asyncpg tabanlı bir store ile gerçekleştir (tek transaction upsert, stale
   revizyon reddi; `pgvector_schema.sql` sözleşmesi birebir).
2. **Sürücü:** `pyproject.toml`'a `pgvector>=0.3,<0.4` ekle (asyncpg ile
   `pgvector.asyncpg` register_cuda yok; `vector` codec kaydı).
3. **Alembic migration 0004:** `CREATE EXTENSION IF NOT EXISTS vector;` +
   `agent.content_chunk` tablosu (dimensions parametrik).
4. **Compose imgesi:** `postgres:18.0-alpine` → `pgvector/pgvector:pg18`
   (B11'de `docker manifest inspect` ile tag'in varlığı doğrulandı).
   Aynı PG major sürümü → data volume uyumlu; YİNE DE öncesi backup
   (yedekleme-geri-yukleme.md §2) ve sonra `CREATE EXTENSION vector` doğrulaması.
5. **Gerçek entegrasyon testi:** A3 `InMemoryContentIndex` davranış
   sözleşmesiyle AYNI testler gerçek store üstünde (test embeddings
   is_test_double işaretli; deterministik) — idempotent indeksleme, stale
   reddi, kaldırma, RRF füzyonu.
6. **Health:** `/health/agent`'a pgvector erişim kontrolü EKLENEBİLİR (additive).

## Rollback

- İmge: compose'da `postgres:18.0-alpine`'e dön; volume AYNI kalır (pg18
  major uyumu). Extension kalıntısı zararsızdır: `DROP EXTENSION vector;` +
  `DROP TABLE agent.content_chunk;` (migration downgrade) ile temizlenir.
- Adaptör: yapılandırmada in-memory index'e dön (A3'ün mevcut gerçekleştirimi);
  pgvector store yalnız additive bir seçenektir — kaldırılması mevcut davranışı
  değiştirmez.

## B11 raporundaki yeri

Bu karar B11-rapor.md §pgvector'da aynı gerekçeyle, "uygulanmadı" ifadesiyle
raporlanmıştır; progress.md güncellemesi orchestrator içindir.
