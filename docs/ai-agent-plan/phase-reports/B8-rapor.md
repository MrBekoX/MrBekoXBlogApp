# B8 Faz Raporu — Makale olayları ve içerik güncelliğini bağla

Tarih: 2026-10-12 · Dal: `feature/ai-agent-integration` · Sahip: B8 implementasyon agent'ı

Plan kaynağı: `docs/ai-agent-plan/02-rabbitmq-haberlesme-plani.md` "Aşama B8" (satır 438-465),
satır satır uygulandı. Kararlar: D008 (backend-atandı monoton `article_revision`; `BlogPost.Version`
KULLANILMADI — L004), D011 (tek konsolide EF migration), D013 (declarer kimliği), L009 (faz başına
kendi vhost + scratch DB). RAG aracı faz başında doğrulandı:
`node docs/ai-agent-plan/source/tools/search.cjs verify` → `valid: true` (30 kaynak, 60 parça, 23 aşama).
B8 CONTEXT'i `search.cjs search --stage B8 --query "Makale revizyonu outbox değişiklik aktarımı ve
vector index" --format prompt` ile getirildi; kullanılan kaynaklar: [ENG-OUTBOX#C1], [ENG-OUTBOX#C2]
(relay tekrarında consumer idempotentliği), [PG-ISOLATION#C1] (Read Committed statement-level
snapshot — senkron anlık okuması), [PG-ISOLATION#C2] (eşzamanlı güncellemede revision monotonluk
kuralı), [PGVECTOR#C1/#C2] (aşağıdaki sınır kararı).

## 1. Sözleşme bağlılığı (DONUK B1) — plan maddelerinin eşlemesi

`content.article.changed` şeması DONMUŞTUR (`src/contracts/agent/v1/payloads/content.article.changed.schema.json`):
`article_id, article_revision, action(updated|unpublished), content_hash?, language?, title?`.
Dispatch özetindeki "status, canonical URL, yayınlanmış snapshot" öğeleri L003 gereği PLAN METNİYLE
birlikte yorumlandı ve donuk sözleşmeye şu şekilde eşlendi:

- **status** → `action` enum'u: `updated` = yayımlanmış içerik anı, `unpublished` = kaldırma
  TOMBSTONE'u (şema: unpublished'ta `content_hash` taşınması YASAK).
- **yayınlanmış snapshot** → K7: içerik gövdesi MESAJA GÖMÜLMEZ; (article_id, revision, hash)
  referans üçlüsü taşınır. Gerçek gövde, yürütme anında backend'in kabul snapshot'ından
  (`AgentRun.ContextSnapshotJson` — slug/title/hash içerir) ve consumer'ın opsiyonel gövde
  köprüsünden gelir.
- **canonical URL** → mesajda ayrı alan yoktur; consumer tarafında A3 `build_canonical_url`
  (slug + `canonical_url_template`) ile üretilir; slug çalışma anındaki kabul snapshot'ından
  çözülür. B1 registry ayna testleri bozulmadı (mevcut `AgentContractSchemaMirrorTests` yeşil).

## 2. .NET tarafı (yayınla/güncelle/kaldır/sil → içerik olayları)

### 2.1 `BlogPost.ContentRevision` + migration (ADDITIVE)

- `src/backend/Core/Domain/Entities/BlogPost.cs`: `long ContentRevision` (varsayılan 0) eklendi;
  XML doc D008/L004 referanslı — `Version` (xmin rowversion) revizyon DEĞİLDİR ve hiçbir yerde
  revizyon olarak kullanılmadı.
- Migration `20261012012750_AddContentRevision` (`dotnet ef migrations add`, tasarım zamanı
  bağlantısı `BLOGAPP_MIGRATION_CONNECTION` env'den, değer log'a yazılmadı): `posts.content_revision
  bigint NOT NULL DEFAULT 0` + `agent_content_syncs` tablosu (watermark kaydı) + iki operasyonel
  indeks. Tamamen ADDITIVE; ModelSnapshot güncel.
- `AgentContentSync` entity + `AgentContentSyncStatus` enum (Domain) +
  `AgentContentSyncConfiguration` (Infrastructure): senkron kaydı (sync_id PK, status, batch_size,
  item_count, total_batches, revision_watermark, started_at, completed_at).
- `IApplicationDbContext.AgentContentSyncs` additive DbSet.

### 2.2 `AgentContentEventService` — karar tablosu (AYNI transaction kuralı)

`IAgentContentEventService` (`Common/Interfaces/Messaging`) + gerçekleştim (`Common/Messaging`).
Handler akışı: `Observe(post)` → mutasyon → `RecordChangeAsync(post, before)` → handler'ın TEK
`SaveChangesAsync`'i → makale değişikliği + outbox kaydı AYNI transaction ([ENG-OUTBOX#C1]).

| before       | now          | fiil                    | revision | olay                          |
|--------------|--------------|-------------------------|----------|-------------------------------|
| yayında değil| yayında değil| taslak yaşam döngüsü    | değişmez | YOK (taslak taşınmaz)         |
| yayında değil| yayında      | publish / published create | +1    | updated (content_hash'li)     |
| yayında      | yayında değil| unpublish / arşiv / soft delete | +1 | unpublished TOMBSTONE     |
| yayında      | yayında      | hash aynı → no-op       | değişmez | YOK                           |
| yayında      | yayında      | hash farklı             | +1       | updated (content_hash'li)     |

- content_hash = Content UTF-8 SHA-256, lowercase (D008; `AgentContentEventComposer.ComputeContentHash`).
- "Yayında" tanımı `Status == Published && !IsDeleted` — `GetPostBySlugQuery` erişim tanımıyla aynıdır.
- Zarf commit'ten ÖNCE `AgentContractValidator` ile doğrulanır; doğrulama hatası işlemi istisna ile
  bitirir → bozuk zarf broker'a hiç ulaşamaz (B3 deseni).
- Görüntülenme artışı (`IncrementViewCountAsync` — yalnız `ViewCount` ExecuteUpdate) bu servise
  hiç uğramaz: revision değişmez, olay yazılmaz (plan: "Görüntülenme sayısı gibi ilgisiz
  güncellemeler revision artırmasın" — DB testiyle kanıtlı).
- Tüm içerik zarfları `AgentContentEventComposer` ile üretilir: ArticleChanged, SyncBatch,
  SyncCompleted + **ProfileContentChanged/ProjectContentChanged** bestecileri (plan: "Onaylanmış
  profil ve proje kayıtlarını da ayrı sürümlenmiş içerik olaylarıyla aktar"). Profil/proje onaylı
  kayıt üreten bir backend feature henüz yoktur (A0 bulgusu); besteci + doğrulayıcı hazır, üretim
  bağlantı noktası ilgili feature geldiğinde açılır.

### 2.3 Handler kablolaması (ADDITIVE satırlar; mevcut davranış değişmez)

`Create/Update/Publish+Unpublish/Delete/SaveDraft` handler'larına `IAgentContentEventService`
enjekte edildi ve Observe→RecordChange sırası eklendi (diff §2.2 tablosuna birebir uyar).
`Publish`/`Unpublish` no-op çağrılarda olay ÜRETMEZ (geçiş yoksa). `SaveDraft` yayımlanmış
makalenin içeriğini gerçekten değiştirirse updated olayı üretir; taslakta hiçbir şey üretmez.

### 2.4 `ContentSnapshotSyncService` — backend'in başlattığı ilk senkron

- Snapshot: tek sorguda yayımlanmış makalelerin (article_id, ContentRevision, SHA-256(Content))
  kümesi ([PG-ISOLATION#C1]: statement-level tutarlılık yeterli — canlı değişiklikler ayrı ve
  DAHA YÜKSEK revision'lı canlı olaylarla taşınır; consumer monotonlukla birleştirir).
- Batch sınırı: `AgentContentSyncSettings.BatchSize` (varsayılan 50; K7 256 KiB zarf sınırıyla
  uyumlu referans paketleri). Watermark: snapshot anındaki en yüksek revision,
  `agent_content_syncs.revision_watermark`'a yazılır.
- Tüm batch'ler + `ContentSnapshotCompletedV1` (item_count = snapshot sayısı) + sync kaydı TEK
  SaveChanges transaction'ında yazılır; her zarf commit öncesi B1 doğrulayıcısından geçer.
- "Senkron sürerken olan değişiklikler kaybolmaz": DB testi, snapshot referansının rev 2'yi
  taşıdığı ve sonrasındaki canlı değişikliğin rev 3 olayı olarak ayrı outbox satırı olduğunu
  kanıtlar; consumer tarafı monotonluk testi iki sıranın herhangi bir birleşimini doğru işler.
- Tetik zamanı operasyoneldir: `AgentContentSyncSettings.Enabled` (varsayılan false) hosted
  bağlaması B10/B11 kompozisyonu içindir (B3/B5 Program.cs deseniyle aynı).

### 2.5 `AgentResultPresentationGuard` — sunum katmanı denetimi

Plan: "backend, makale kaynaklı sonucu kullanıcıya sunmadan önce kaynakların güncel yayın
erişimini kendi veritabanından kontrol etsin… içerik kullanılamıyor durumu üretsin."

- Denetim **doğrudan backend DB'sine** gider — cacheService KULLANMAZ (eski cache sunulmaz).
- Girdi: `AgentRunResultContext(RunId, ArticleId, ResultJson)` — B5 projection kolonlarından.
  Makale referansları: ResultJson `citations[]` (kind=article, article_id) + run bağlam makalesi.
- Kök kontrol: `IgnoreQueryFilters()` ile silinmiş makaleler de görülür; karar kuralı
  `exists && !IsDeleted && Status == Published`.
- Çıktı: `AgentResultPresentation(IsPresentable, UnavailableArticleIds, AvailableArticleIds,
  UnavailableReason="İçerik kullanılamıyor: …")`. Denetim salt-okur; maskeleme kararı B10
  sunum endpoint'inindir. Bulgu: jsonb'de saklanan snapshot her zaman geçerli JSON'dur; nesne
  olmayan kök (`[]`) için `TryGetProperty` InvalidOperationException fırlatıyordu — test bunu
  yakaladı, `ValueKind == Object` guard'ı eklendi (§6 bulgu F1).

### 2.6 DI

`Infrastructure/Messaging/AgentContentDependencyInjection.AddAgentContentEvents(configuration)`:
`IAgentContentEventService`, `ContentSnapshotSyncService`, `IAgentResultPresentationGuard` +
`AgentContentSyncSettings` bağlaması. **DİKKAT (entegrasyon adımı):** handler'ların yeni
bağımlılığı nedeniyle API host'unun bu extension'ı çağırması gerekir; `Program.cs` B8 dosya
sahipliği DIŞINDADIR — B10 kompozisyonunda `builder.Services.AddAgentContentEvents(builder.Configuration);`
eklenmelidir (B3 `AddAgentOutbox` / B5 projection kayıtlarıyla aynı desende; mevcut host
kaydında bu extension'lar henüz yoktur).

## 3. Python tarafı (`app/messaging/content.py`, messaging/__init__ export)

- **`ContentSyncState`** — projection durumu (bellek-içi; A3 sınır kararıyla uyumlu):
  - Yeni revizyon uygulanır; `revision < bilinen` → `stale_revision` (olayların ters gelmesi
    broker sırasıyla değil monoton revision ile çözülür [PG-ISOLATION#C2]).
  - `revision == bilinen` + farklı hash → **görünür çatışma kaydı** (`ContentRevisionConflict`
    listesi + `logger.error`); mevcut durum korunur.
  - `revision <= bilinen kaldırma` → `stale_after_removal` (kaldırılmış an geri getirilemez).
  - Tombstone (`action=unpublished`) → kaldırma kaydı + durum temizliği; tekrar teslim
    `duplicate_removal` (idempotent — [ENG-OUTBOX#C2]); kaldırma sonrası republish'tan gelen
    ESKİ tombstone `stale_revision` ile reddedilir (makaleyi yeniden indirmez).
  - **`ensure_execution_allowed(article_id, revision)`**: bilinen kaldırma revizyonu >= komut
    revizyonu → `StaleExecutionRejected` (plan: "Agent projection daha yeni bir kaldırma
    revizyonunu biliyorsa eski komutu yürütmesin"; B6 worker bağlantı noktası).
  - İlk senkron: batch_index idempotent; batch kalem canlı olayla AYNI `_apply_published`
    kuralından geçer (senkron sırasındaki güncelleme: canlı olay kazanır, batch kalemi stale);
    completed: `item_count` uyuşmazlığı + eksik batch "incomplete" GÖRÜNÜR işaretlenir;
    **tamamlanmamış/yabancı completed hiçbir koşulda indeks SİLMEZ** (orphan_completion kaydı).
  - Profil/proje olayları ayrı revizyon izleri olarak uygulanır (aynı çatışma kuralları).
- **`ContentConsumerService`** — her teslim `parse_envelope` (B1) ile doğrulanır; içerik
  kuyruğuna içerik-dışı tür → `ContentPolicyError` → B2 consumer tabanı DLX'e yönlendirir
  (requeue döngüsü yok). `handle_delivery` IntakeService desenindedir (ACK broker tabanında).
- **`ContentIndexProjector`** (opsiyonel) — tombstone → A3 `remove_article` (parçalar + arama
  önbelleği tek çağrıda; kaldırma iş modeli: eski revizyon kaldırması `removed=False`);
  updated → gövde köprüsü (`_ContentBodyFetcher`) varsa `index_article` (hash doğrulamalı,
  uyuşmazlık çatışma kaydı) yoksa `state_only`. Gerçek pgvector/adaptör bağlaması aşağıdaki
  sınır kararı gereği bu fazda YOKTUR.
- **`build_content_consumer`** — `BrokerConsumer` + CONTENT_QUEUE fabrikası.
- Export'lar `app/messaging/__init__.py`'e eklendi (dispatch'teki "content_consumer kaydı").

## 4. Test ortamı (L009 izolasyonu)

- Python: vhost **`blogapp_dev_b8`** (kendi
  vhost'u; management API ile idempotent provizyon, topoloji admin bağlantısıyla declare —
  üretimde declarer backend'dir, K3). Scratch DB GEREKMEZ: B8 consumer projection'ı bellek
  içidir ve Python tarafına bu fazda Alembic migration KAPSAM DIŞIDIR (dispatch izinli dosyalar).
- .NET: vhost **`blogapp_dev_b8net`** + scratch DB **`blogdb_b8tests`** (migration zinciri
  `MigrateAsync` ile uygulanır; her koşuda taze kurulup düşürülür). `blogdb_dev` ve
  `blogapp_dev` vhost'una TEST YAZILMADI.
- Ortam olayı yok: checkout/stash yapılmadı (L006); çalışma ağacında kullanıcının paralel
  A8 çalışması (`agent_core/entrypoints.py`, `agent_core/ports/checkpoint.py`,
  `agent_core/checkpoint/`, `tests/checkpoint/` — dispatch kapsamı dışı) B8'e DOKUNULMADAN
  korundu; tam python suite bu değişikliklerle birlikte koşuldu ve yeşildir.

## 5. Kabul ölçütleri ↔ kanıt (plan satır 465)

| Ölçüt | Kanıt |
| --- | --- |
| Olayların ters gelmesi | `test_older_revision_ignored_out_of_order_delivery`, `test_older_removal_after_republish_ignored` (unit) + `test_update_then_out_of_order_old_revision` (GERÇEK broker: eski revizyon kuyruktan sonradan tüketildi, durum gerilemedi) |
| Kaldırma | `test_removal_applies_and_state_moves_to_removal`, `test_duplicate_removal_is_idempotent` + `test_tombstone_consumed_from_real_queue` (GERÇEK broker + A3 indeks: chunk_count 3→0, önbellek düşer) + .NET `Unpublish_PersistsTombstoneEvent` |
| Silme | `SoftDeleteOfPublishedPost_WritesTombstone` (DB): IsDeleted → tombstone, revision +1; taslak silmesi olay üretmez |
| İlk sync sırasında güncelleme | `test_live_change_during_sync_wins_over_late_batch_reference` + .NET `Sync_ItemsCarryCurrentRevisionsSoLiveChangesDominateLater` (snapshot rev 2 referansı + canlı rev 3 olayı ayrı ayrı outbox'ta) |
| Eski sonucun geç gelmesi | `StaleExecutionCommand` test kümesi (`StaleExecutionRejected`) + `AgentResultPresentationGuardTests` (yayından kaldırılmış/silinmiş makaleye dayanan sonuç → `IsPresentable=false`, "içerik kullanılamıyor"; `IgnoreQueryFilters` ile soft-delete de yakalanır) |
| Aynı revizyon farklı hash | `test_same_revision_different_hash_records_visible_conflict` + senkron kalemi çatışması + gövde köprüsü hash uyuşmazlığı (`test_updated_with_mismatched_fetched_hash_records_conflict`) |
| Tamamlanmamış snapshot'ta indeks korunur | `test_incomplete_sync_does_not_trigger_removal`, `test_orphan_completed_recorded_without_any_index_effect`, `item_count_mismatch` görünür kaydı |
| Şema hatalı mesaj DLQ | `test_invalid_contract_message_goes_to_dlq` (GERÇEK broker: yanlış üreticili içerik olayı `agent.content.q.dlq`'ya düştü) |
| Aynı transaction | `PublishedUpdate_PersistsRevisionAndOutboxInSameCommit` + `TransactionWithoutCommit_PersistsNoRevisionAndNoEvent` (rollback'te revision da olay da yok) |

## 6. Bulgular

- **F1 (kod, düşük, DÜZELTİLDİ):** `AgentResultPresentationGuard.CollectArticleReferences`
  nesne olmayan JSON kökünde `InvalidOperationException` fırlatıyordu (`JsonElement.TryGetProperty`
  yalnız JsonException değil element-tip hatası da fırlatır). Tetik: `"[]"` ResultJson.
  Düzeltme: `ValueKind == JsonValueKind.Object` guard'ı
  (`AgentResultPresentationGuard.cs:145`). Yakalayan test:
  `NonObjectResultJson_StillChecksContextArticle`.
- **F2 (entegrasyon notu, ORTA):** `Program.cs`'e `AddAgentContentEvents` çağrısı eklenmeden API
  host'u handler'ların `IAgentContentEventService` bağımlılığını çözümleyemez. Dosya sahipliği
  nedeniyle B8 BU SATIRI EKLEMEDİ; B10 kompozisyonu için zorunlu adım olarak işaretlendi (§2.6).
- **F3 (sınır kararı, raporlanır):** Gerçek pgvector BU FAZDA YOK (dispatch sınır kararı; A3
  sınırıyla aynı). Postgres image'ına pgvector uzantısı ekleme kararı B11 Docker fazının
  konusudur; consumer'ın gövde köprüsü (`_ContentBodyFetcher`) ve `ContentIndexProjector` bu
  bağlamın hazır arayüzleridir. Sınır [PGVECTOR#C1/#C2] ile belgelendi.
- **F4 (kapsam):** Profil/proje içerik olaylarının besteci + consumer uygulaması tamamıştır;
  onaylı profil/proje kaydı üreten backend feature bulunmadığından ÜRETİM tetikleyicisi yoktur
  (emisyon, ilgili feature ile bağlanır).

## 7. GATE — çalıştırılan komutlar ve gerçek çıktılar

1. `node docs/ai-agent-plan/source/tools/search.cjs verify` → `"valid": true` (30 kaynak/60 parça).
2. `python -m pytest src/services/ai-agent-service/tests/content_sync -q` →
   **33 passed in 16.76s** (unit 29 + gerçek broker 4; vhost `blogapp_dev_b8`).
3. `dotnet test src/backend/Presentation/Api.Tests --nologo -v q` →
   **Başarılı! Başarısız: 0, Başarılı: 132, Atlanan: 0, Toplam: 132 — 2 m 17 s**
   (B8 içerik testleri 26/26: DB testleri scratch `blogdb_b8tests`, broker testi
   `blogapp_dev_b8net`; 106 önceki test regresyonsuz).
4. Ek regresyon (GATE dışı, seri): `python -m pytest tests -q`
   (ai-agent-service kökünden) → **630 passed, 1 skipped, 2 warnings in 131.23s** —
   B8 messaging export'ları diğer fazları kırmadı (L009 gereği koşumlar seri yürütüldü,
   paralel suite koşumu yok).

## 8. Dosya listesi (B8 sahipliği)

- Domain: `BlogPost.cs` (+ContentRevision), `AgentContentSync.cs` (yeni), `AgentContentSyncStatus.cs` (yeni)
- Application: `IAgentContentEventService.cs` (yeni), `AgentContentEventComposer.cs` (yeni),
  `AgentContentEventService.cs` (yeni), `AgentContentSyncSettings.cs` (yeni),
  `ContentSnapshotSyncService.cs` (yeni), `AgentResultPresentationGuard.cs` (yeni),
  `IApplicationDbContext.cs` (+DbSet), 6 PostFeature handler (additive satırlar)
- Infrastructure: migration `20261012012750_AddContentRevision` (+Designer),
  `AppDbContextModelSnapshot`, `AppDbContext.cs` (+DbSet), `BlogPostConfiguration.cs`
  (+content_revision eşlemesi), `AgentContentSyncConfiguration.cs` (yeni),
  `AgentContentDependencyInjection.cs` (yeni)
- Python: `app/messaging/content.py` (yeni), `app/messaging/__init__.py` (export)
- Testler: `src/backend/Presentation/Api.Tests/Messaging/Content/*` (6 dosya),
  `src/services/ai-agent-service/tests/content_sync/*` (4 dosya, `__init__.py`'li paket — L005)
- Bu rapor: `docs/ai-agent-plan/phase-reports/B8-rapor.md`

## 9. Çalıştırılmayanlar / sınırlar

- Gerçek pgvector entegrasyonu, backend başlattığı senkronun hosted-service tetikleyicisi ve
  `Program.cs` DI kablolaması (yukarıda) bu fazda koşulmadı — B10/B11 kapsamı.
- Uçtan uca "UI'dan yayınla → agent cevap → kaldırılma sonrası sunum engeli" birleşik akışı
  B10 UI endpoint'leri olmadan koşulamaz; bu fazda her halka kendi gerçek altyapısıyla
  (gerçek broker + gerçek Postgres) ayrı ayrı kanıtlandı.
- Python consumer'ın kalıcı projection deposu yoktur (bellek-içi; A3 sınırı). Worker restart'ında
  durum yeniden kurulmalıdır — kalıcılık gereksinimi A3/B11 değerlendirmesine not edildi.
