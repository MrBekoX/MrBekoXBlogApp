# A3 Faz Raporu — İçerik bölümleme ve hibrit retrieval

- **Faz:** A3 (markdown korumalı bölümleme, ortak anchor sözleşmesi, hibrit retrieval, idempotent indeksleme, kaldırma iş modeli)
- **Tarih:** 2026-10-11
- **Branch / temel:** `feature/ai-agent-integration`, çalışma sırasında HEAD `6ed4cc7` (başlangıç anındaki son A3-öncesi kayıt: B1 4a887cb + doküman commit'leri)
- **Rol:** A3 implementasyon agent'ı
- **Okunan girdiler:** `docs/ai-agent-plan/01-agent-gelistirme-plani.md` "Aşama A3" (satır 229–261), `main-prompt.md`, `decisions.md` (D001–D012), `progress.md`, `lessons-learned.md` (L001–L004), `phase-reports/A1-rapor.md`, mevcut kod: `app/agent_core/models/article.py`, `ports/content.py`, `ports/embedding.py`, `ports/cancellation.py`, `errors.py`, `adapters/test_doubles/*`, `tests/conftest.py`, B1 sözleşmesi `src/contracts/agent/v1/payloads/content.article.changed.schema.json`
- **Yazılan dosyalar:** yalnız izinli kapsam — `src/services/ai-agent-service/app/agent_core/content/**` (7 yeni dosya), `src/services/ai-agent-service/tests/content/**` (5 yeni dosya), bu rapor. Mevcut hiçbir dosya değiştirilmedi; `src/contracts/**` donuk kaldı; `pyproject.toml`'a dokunulmadı (A2 sahipliği); commit/push yapılmadı.

## 1. Ortam ve ön koşul doğrulaması

| Kontrol | Komut | Sonuç |
| --- | --- | --- |
| Python | `python --version` | Python 3.13.9 |
| Bağımlılıklar | `python -m pip show pydantic pytest` | pydantic 2.11.7, pytest 8.3.3; pytest-asyncio KURULU DEĞİL (async testler `run()` deseniyle senkron koşar) |
| A3 ön koşulları | `models/article.py`, `ports/content.py`, `ports/embedding.py` okundu | `ArticleSnapshot`/`ArticleChunk`/`compute_content_hash` (A0), `ContentRepository`/`EmbeddingProvider`/`CancellationToken` portları (A1) mevcut |
| Kaynak arama | `node docs/ai-agent-plan/source/tools/search.cjs search --stage A3 --query "Pgvector hibrit retrieval ve chunk bağlamı" --format prompt` | CONTEXT döndü: [PGVECTOR#C1], [PGVECTOR#C2], [ENG-CONTEXTUAL#C1], [ENG-CONTEXTUAL#C2], [LG-RAG#C1], [LG-RAG#C2] |
| L002 kontrolü | `ls nul` (repo kökü) | yok — cmd yönlendirmesi kullanılmadı |

## 2. Oluşturulan paket yapısı

```
app/agent_core/content/
├── __init__.py           # paket dışa açılımı
├── anchors.py            # ORTAK anchor sözleşmesi: TR katlama + tekrarlanan başlık -n
├── chunking.py           # markdown hiyerarşi + kod bloğu korumalı bölümleyici
├── config.py             # EmbeddingModelConfig + ChunkingConfig.for_model + INDEX_VERSION
├── models.py             # IndexedChunk (chunk + content_hash + heading_path + anchor + URL)
├── retrieval.py          # tokenize, cosine, BM25, RRF füzyon, SearchFilters, SearchCache
├── index.py              # InMemoryContentIndex: idempotent/atomik yazma, kaldırma, arama
├── pgvector.py           # B8 adaptör SÖZLEŞMESİ (çalıştırılmaz, config_error üretir)
└── pgvector_schema.sql   # B8 hedef DDL (agent şeması, D011)

tests/content/            # A3 test sahipliği (kök tests/conftest.py değiştirilmedi)
├── fixtures.py           # ORTAK anchor fixture tabloları + örnek makale + test sağlayıcıları
├── test_anchors.py       # 18 test
├── test_chunking.py      # 11 test
├── test_indexing.py      # 13 test
├── test_retrieval.py     # 12 test
└── test_pgvector_contract.py  # 5 test
```

## 3. Plan yapılacaklarının karşılıkları

| Plan A3 maddesi | Uygulama | Kanıt |
| --- | --- | --- |
| Markdown başlık hiyerarşisini ve kod bloklarını koruyarak bölümle | `chunking.py`: ATX başlık yığını → başlık yolu (kök: makale başlığı); fenced blok (```) ve tilde (~~~) tek parça; fence içi `#` başlık sayılmaz; kapatılmamış fence belge sonuna dek | `test_chunking.py::test_sample_markdown_heading_paths_and_order`, `::test_code_fence_stays_whole`, `::test_heading_inside_fence_is_not_a_heading`, `::test_tilde_fence_supported` |
| Parçaları article_id, article_revision, content_hash, başlık yolu, anchor, canonical URL ile ilişkilendir | `content/models.py::IndexedChunk` (mevcut `ArticleChunk`'u sarmalar, alan kopyalamaz; `extra="forbid"`) | `test_indexing.py::test_indexed_chunks_carry_contract_fields` |
| Uzun parçaları anlamlı sınırlardan böl; boyutları embedding modeline göre yapılandır | `ChunkingConfig.for_model`: `max_chars = max_chunk_tokens × chars_per_token`; bölünme sırası paragraf → cümle (`.!?…`) → kelime sınırı; parçalar kaynağın kesintisiz dilimidir (`content == content[char_start:char_end]`, A0 §4 citation sözleşmesi) | `test_chunking.py::test_config_derives_max_chars_from_embedding_model`, `::test_long_section_splits_within_limit_and_loses_no_content` |
| Türkçe karakterler + tekrarlanan başlıklar için ortak anchor sözleşmesi | `anchors.py`: ç→c, ğ→g, ı→i, İ→i (casefold ÖNCESİ — `İ`.casefold() birleşik nokta üretir), ö→o, ş→s, ü→u, I→i; 2. oluşum `-2`, 3. `-3`; katlama eşleşmeleri (ÖZET/özet) tekrar sayılır; yalnız noktalama → `bolum` yedeği. Sözleşmenin asıl kaynağı `tests/content/fixtures.py` tablolarıdır (chunker + anchor testleri aynı tabloyu kullanır) | `test_anchors.py` (18 test), `::test_sample_markdown_anchors_follow_document_order` |
| Embedding ile anlamsal + anahtar kelime aramasını birleştir | `retrieval.py`: cosine benzerliği [PGVECTOR#C1] + Türkçe katlamalı BM25 (tam terim eşleşmesi teknik kimlikler için önemli [ENG-CONTEXTUAL#C1]) + reciprocal rank fusion [PGVECTOR#C2]; k=60 standart değeri; deterministik eşitlik kırılımı (skor, article_id, chunk_index) | `test_retrieval.py::test_rrf_fusion_combines_both_rankings`, `::test_relevant_chunk_ranks_first` |
| article_id, dil, yayın durumu filtreleri | `SearchFilters.allows` — filtreler **skorlamadan önce** aday kümesine uygulanır; sızma yapısal olarak olanaksız | `test_retrieval.py::test_identical_content_of_other_article_cannot_leak_through_filters`, `::test_language_filter_excludes_other_language`, `::test_published_filter_respects_all_states` |
| Yeniden indekslemeyi içerik hash'iyle idempotent yap | `index_article`: aynı revision + aynı `content_hash` → embedding çağrısı YAPMADAN atlama (`indexed=False`); aynı revision + farklı hash → `stale_snapshot` (revizyon yayın anı kimliğidir, D008/W0 §1.4) | `test_indexing.py::test_same_content_is_not_indexed_twice` (provider.call_count==1), `::test_same_revision_with_different_hash_is_rejected` |
| Yeni revizyonun görünmesini atomik hale getir | Makale durumu tek `_ArticleEntry`; yeni revizyon yan tarafta tam kurulur (embed arızasında eski durum dokunulmaz) ve tek sözlük atamasıyla değiştirilir; geç gelen eski revizyon `stale_snapshot` reddi | `test_indexing.py::test_failed_embed_leaves_previous_revision_intact`, `::test_late_arriving_older_revision_is_rejected`, `::test_updated_article_found_under_new_revision` |
| Kaldırma iş modeli: eski parçalar + ilgili önbellek | `remove_article` B1 `content.article.changed` action=unpublished'a eşlenir; bilinen revizyondan eski kaldırma talebi stale (içerik dokunulmaz); makale yoksa idempotent `removed=False`; `SearchCache.invalidate_article` | `test_indexing.py::test_known_revision_removal_hides_old_content_and_invalidates_cache`, `::test_stale_removal_keeps_newer_content` |
| Embedding boyutu, model kimliği, indeks sürümü saklama | İndeks manifest alanları: `model_id`, `dimensions`, `INDEX_VERSION` (pgvector DDL'inde `embedding_model_id`/`index_version` sütunları) | `test_pgvector_contract.py::test_index_version_constant_is_declared` |
| Model değişince yeniden indeksleme stratejisi | Manifest uyuşmazlığı `config_error` üretir ve `reindex()` zorunlu kılar; `reindex` yan yapıda kurup tek atamayla değiştirir (arızada mevcut indeks korunur) | `test_indexing.py::test_embedding_model_change_requires_reindex`, `::test_reindex_rebuilds_whole_index_atomically` |

## 4. Sınır kararı: gerçek DB bağlantısı kurulmadı

Görev sınırı uyarınca **hiçbir gerçek veritabanı bağlantısı kurulmadı** ve kurulabilir de olmadı:

1. **In-memory gerçekleştirim + tam test kapsamı:** `InMemoryContentIndex` — 55 test bu gerçekleştirimi koşar.
2. **pgvector şema/SQL + adaptör sözleşmesi (çalıştırılmadan belgelenir):** `pgvector_schema.sql` — `agent.content_chunk` tablosu (PK `article_id, article_revision, chunk_index`; `content_hash`, `anchor`, `published`, `embedding vector(N)`, `embedding_model_id`, `index_version`; HNSW cosine indeksi [PGVECTOR#C1]; `to_tsvector('simple')` + GIN full text tarafı [PGVECTOR#C2]; D011 gereği yalnız `agent` şeması). `pgvector.py` — `PgvectorContentIndexStore` Protocol'ü (upsert/delete/search_hybrid yüzeyi) ve sürücüsüz ortamda **config_error üreten iskelet**; test yalnız sözleşme biçimini ve hata davranışını doğrular, bağlantı açmaz.

**Açık sınırlama (rapor şartı):** gerçek pgvector entegrasyonu, bağlantı havuzu, migration ve yeniden indeksleme stratejisinin üretimde doğrulanması **B8 içerik senkronu** kapsamındadır. Bu fazda pgvector tarafı YALNIZ belgelenmiştir; çalıştırılmamıştır.

## 5. Gerçek çalıştırılan kontroller

| Kontrol | Komut | Sonuç |
| --- | --- | --- |
| **GATE** | `python -m pytest src/services/ai-agent-service/tests/content -q` (repo kökünden) | **55 passed** |
| Birleşik regresyon (A1+B1+A3; devam eden A2/B2 dizinleri hariç) | `python -m pytest src/services/ai-agent-service/tests --ignore=…/tests/messaging_broker --ignore=…/tests/state -q` | **226 passed, 1 skipped** (171+1 önceki fazlar + 55 A3) |
| Statik analiz (sahip olunan dosyalar) | `python -m pyflakes app/agent_core/content/ tests/content/*.py` | temiz (exit 0) |
| Kaynak arşivi | `node docs/ai-agent-plan/source/tools/search.cjs search --stage A3 …` | 6 parça CONTEXT |

Hariç tutulan dizinler bu oturumda **paralel çalışan diğer fazlara** aittir ve çalışma ağacında devam eden işlerdir (aşağıda §7).

## 6. Tasarım kararları ve gerekçeleri

- **`IndexedChunk` kompozisyonu:** mevcut `ArticleChunk` modeli değiştirilemez (sahiplik kuralı); kayıt onu sarmalar, `content_hash`/`heading_path`/`anchor`/`canonical_url`/`language`/`published` retrieval bağlamını taşır.
- **Gömme metni bağlam eki:** parça metnine `başlık yolu` öneki eklenir — "Parçalar, kaynak bağlamını kaybettiğinde arama ve cevap üretimi zorlaşır" [ENG-CONTEXTUAL#C1], kısa bağlam eki yaklaşımı [ENG-CONTEXTUAL#C2]. Yan etki: makale başlığı kovası tüm parçalarda paylaşıldığından saf anlamsal skor tam 0 olmayabilir; sıralama yine de ilgili bölümü ayırt eder (testte üst sıra doubly rank-1 doğrulanır).
- **BM25/RRF parametreleri:** k1=1.5, b=0.75 klasik değerler; RRF k=60 literatür standardı [PGVECTOR#C2]. Filtrelenmiş küme üzerinde hesaplanır (N küçük; in-memory için yeterli, pgvector tarafında FTS + RRF SQL'e taşınacak).
- **Kaldırma semantiği:** `article_revision >= mevcut` → sil; `eski` → stale, dokunma (monotonik revizyon, D008); makale yok → idempotent başarı. Gerekçe: senkron tekrar teslimi güvenli olmalı (ana prompt: inbox/idempotency kuralı).
- **Önbellek:** sorgu sonuç önbelleği (toplam sonuç anahtarları + makale etiketleri); okumada anahtarlar indekse karşı çözülür, silinmiş parça görülürse yeniden hesap; `index_article`/`remove_article` makalenin girdilerini düşürür. Kapasite 128, FIFO taşma.
- **Eşzamanlılık modeli:** tek yazıcı varsayımı (B8 senkron sırası); okuyucular atomik referans ataması sayesinde kısmi makale durumu görmez. Çok yazıcılı senaryo B8'de kilit/lease ile ele alınır.
- **Anchor sıra numarası:** GitHub `-1` başlangıcı yerine `-2` başlangıcı seçildi (2. oluşum okunuşu); sözleşme fixture'larla sabitlendiği için değişirse tek tablo güncellenir.

## 7. Bulgular ve çapraz faz notları

- **F1 (orta, çözüldü — kendi dizinim):** `tests/content/conftest.py` varlığı, kök `tests/` testlerinin `import conftest` çözümlemesini gölgeliyordu (`AttributeError: module 'conftest' has no attribute 'make_route'` — birleşik koşuda 61 başarısızlık). Düzeltme: content dizininden conftest kaldırıldı, fabrikalar `fixtures.py`'e taşındı; birleşik koşu 226 passed'a döndü. **Aynı yapı A2'nin `tests/state/conftest.py`'de de var ve şu an koleksiyon hatası üretiyor:** `python -m pytest … --ignore=…/messaging_broker` → `tests/state/test_graph_runner.py:44: NameError: name 'ScriptedEffects' is not defined` (onların `import conftest` çözümlemesi de gölgeleniyor). Dizin A2 sahipliğinde olduğundan dokunulmadı; A2'ye aynı desen önerilir (subdir conftest'i kaldırıp fabrika modülü kullanmak).
- **F2 (bilgi):** Çalışma ağacı paylaşımlı: A2 (`agent_core/state|budget|graph`, `tests/state`, `ports/budget.py`, `pyproject.toml`) ve B2 (`messaging/*`, `tests/messaging_broker`, `docker-compose.yml`) bu oturumda paralel yazıyor. Tam `tests/` koşusu bu yüzden başarısızdır (messaging_broker gerçek broker ister ve devam eden API'dir); A3 kapsamı bu başarısızlıklara dahil değildir.
- **F3 (L001, orchestrator'a):** `.gitignore:27 tests/` gereği `tests/content/**` yeni dosyaları normal `git add` ile alınmaz; commit adımında `git add -f` gerekir (rapor `docs/` için de geçerli).
- **F4 (düşük):** `pyproject.toml` için yeni paket gereksinimi YOK — content modülleri yalnız stdlib + pydantic kullanır; A2'nin dosyasına dokunulmadı.

## 8. Sınırlamalar (açık beyan)

- Test embedding'i `HashingEmbeddingProvider` (hash-kova, `is_test_double=True`) ve A1'in `FakeEmbeddingProvider`'ıdır; **gerçek embedding sağlayıcı başarısı değildir** (ana prompt kuralı). Anlamsal kalite (reranking, bağlam eki faydası) gerçek sağlayıcıyla A4/A10'da ölçülmelidir.
- Türkçe kök bulma (stemming) yapılmaz; BM25 tam terim + katlama üzerinden çalışır.
- Setext başlıkları ve girintili kod blokları kapsam dışıdır (ATX + fenced desteklenir; docstring'de belgeli).
- Tek başına `max_chars`'ı aşan fenced blok bölünmez (belgeli istisna; testle sabit).
- `progress.md`/`decisions.md` tek yazarı ana orkestratördür; bu rapor yalnız öneri sağlar.

## 9. Kullanılan kaynak kimlikleri

[PGVECTOR#C1], [PGVECTOR#C2], [ENG-CONTEXTUAL#C1], [ENG-CONTEXTUAL#C2]; bağlam veri olarak ele alındı [LG-RAG#C2]. Repo davranışı iddiaları yalnız bu rapordaki dosya/satır ve gerçek test çıktılarıyla desteklenmiştir.

## 10. Sonraki adım önerisi

A4 soru-cevap akışı bu paketi `SearchQuery` + `ScoredChunk.record.canonical_url`/`heading_path` üzerinden tüketebilir; `SourceReference` üretimi için `article_id/article_revision/chunk_index` üçlüsü kayıtlarda hazırdır.
