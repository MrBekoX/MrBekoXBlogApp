# B9 Faz Raporu — İş birliği onayı ve resume mesajlarını bağla

Tarih: 2026-10-12 · Faz: B9 (W6: A9 → B9 ∥ B10) · Durum: **Doğrulandı (gate yeşil)**

Plan metni: `docs/ai-agent-plan/02-rabbitmq-haberlesme-plani.md` "Aşama B9" bölümü (satır 467-488).
RAG: faz başında `node docs/ai-agent-plan/source/tools/search.cjs verify` → `valid:true`
(30 kaynak / 60 parça / 23 aşama). Teknik bağlam:
`search --stage B9 --query "Onay authorization resume ve idempotent kayıt" --format prompt`
→ [ENG-OUTBOX#C1/#C2], [LG-INTERRUPTS#C1/#C2], [ASPNET-AUTH#C1/#C2] parçaları bağlam olarak kullanıldı.

## 1. Yapılan işler

### 1.1 Backend — AgentProposal kalıcı saklama (Domain, ADDITIVE)

- `src/backend/Core/Domain/Entities/AgentProposal.cs` (yeni): proposal kimliği
  (`ProposalId`), içerik sürümü/hash'i (`Version` + `ContentHash` = SHA-256 UTF-8
  özet), run sahipliği (`RunId` + `OwnerKey` kopyası), makale üçlüsü
  (`ArticleId`/`ArticleRevision`/`BaseContentHash` — D008 anlamı), süre sınırı
  (`ExpiresAt`) ve durum makinesi (`Status`: `proposed → confirmed → resume_sent`;
  `AgentProposalStatus` sabitleri). Plan B9: "Proposal kimliği, içerik sürümü/hash'i,
  run sahipliği ve süre sınırı tut."
- Mevcut entity'lere dokunulmadı (additive tablo).

### 1.2 Backend — IAgentCollaborationStore + AgentCollaborationService (Application)

Entegrasyon sahibi sözleşmesi (`Features/AgentFeature/Collaboration/`):

- `IAgentCollaborationStore.cs` (yeni): `UpsertProposalAsync` (idempotent — aynı
  `(ProposalId, ContentHash)` tekrarı no-op), `GetRunStateAsync` (sahiplik kaynağı
  backend run kaydı), `GetCurrentProposalAsync` (en yüksek sürüm), `ConfirmAsync`
  (koşullu `proposed→confirmed` UPDATE — yarışta TEK çağrı satır etkiler),
  `MarkResumeSentAsync` (koşullu `confirmed→resume_sent`).
- `AgentCollaborationModels.cs` (yeni): `AgentProposalUpsert`, `CollaborateSubmitResult`
  (Accepted | Duplicate | RejectedOwner | RejectedVersion + RegisteredAt + sürüm +
  ret gerekçesi), `CollaborateResumeResult` (Sent | Duplicate | RejectedOwner |
  RejectedVersion), `ConfirmationTransition`.
- `AgentCollaborationContentHash.cs` (yeni): sürüm hash'i = backend'in sakladığı
  **düzenlenebilir özetin** UTF-8 SHA-256 özeti (D008 kuralı).
- `AgentCollaborationService.cs` (yeni):
  - `UpsertProposalAsync(...)`: yalnız KALICI KAYIT; onay üretmez.
  - `SubmitConfirmationAsync(run_id, proposal_id, submitted_content_hash,
    edited_summary?, owner_key, confirmed_at)`: açık onay + hash eşleşmesi + owner
    eşleşmesi + süre geçerliliği; `edited_summary` verildiyse gönderilen hash'in
    `SHA-256(edited_summary)` olması zorunlu ve düzenleme YENİ SÜRÜM olarak
    kaydedilir (plan: "Ziyaretçinin düzenlemesini yeni proposal sürümüyle
    ilişkilendir"). Kabulde AgentActionResultV1 (accepted + **applied_article_revision**)
    AYNI transaction'da outbox'a yazılır; sürüm/süre reddinde ret kararı gerekçesiyle
    ve **deterministik message_id** ile (UUIDv5 benzeri, SHA-1 tabanlı) TEK KEZ
    bildirilir; sahiplik reddinde mesaj ÜRETİLMEZ (bkz. §4).
  - `ResumeRequestAsync(run_id, proposal_id, expected_content_hash, owner_key)`:
    onaylanmış sürümün hash'i beklenenle eşleşmeli; durum makinesi koşullu UPDATE ile
    `resume_sent`'e geçer — **aynı onay için ikinci resume ÜRETİLMEZ** (Duplicate,
    yeni outbox kaydı yok; eşzamanlı çağrıda da 196-test kapısında doğrulandı).
- `Common/Messaging/AgentCollaborationEnvelopeComposer.cs` (yeni, ADDITIVE dosya —
  B1 donuk `AgentCommandEnvelopeComposer`/registry dosyalarına dokunulmadı):
  `ComposeResumeRequested` + `ComposeActionResult` (donuk
  `AgentResumeRequestedV1`/`AgentActionResultV1` DTO'larından) + deterministik ret
  kimliği. Tüm zarflar commit öncesi `AgentContractValidator` ile doğrulanır (B3 deseni).
- `Common/Options/AgentCollaborationSettings.cs` (yeni): `ProposalValidityHours`
  (varsayılan 168) — süre sınırı backend politikasıdır.
- Açık eylem komutları (onayın TEK girişi; LLM metni hattan GEÇMEZ):
  `Commands/SubmitCollaborationConfirmationCommand/` ve
  `Commands/RequestCollaborationResumeCommand/` (MediatR; oturum → owner_key
  çözümlemesi `u:{userId}` / `g:{guestSession}`; istemci owner alanı taşımaz — plan
  satır 124).

### 1.3 Backend — Projection bağlantısı (B5 → B9, ADDITIVE)

- `AgentRunEventProjectionEvent`'e `ProposalUpsert` opsiyonel üyesi eklendi
  (`Features/AgentFeature/Events/AgentRunEventProjectionHandler.cs`); handler, Apply
  kararında upsert'i **AYNI transaction'da** store'a yazar; sahiplik kilitli run
  satırının `OwnerKey`'inden tamamlanır (istemciden gelmez). Eski olay/Stale/quarantine
  yolları upsert YAZMAZ.
- `Infrastructure/Messaging/AgentEventProjectionConsumer.cs`: `AgentActionProposedV1`
  olayı için `BuildProposalUpsert` — içerik hash'i summary üzerinden hesaplanır,
  `ExpiresAt` = occurred_at + politika penceresi.

### 1.4 Backend — Infrastructure (migration + store + additive DI)

- `Persistence/Configurations/AgentProposalConfiguration.cs` (yeni): tablo
  `agent_proposals`; unique `UX_agent_proposals_proposal_content (ProposalId, ContentHash)`
  (idempotent upsert + sürüm bağı DB güvencesi), unique
  `UX_agent_proposals_proposal_version (ProposalId, Version)`, CHECK
  `CK_agent_proposals_status` (üç durum kümesi).
- Migration `20261012081319_AddAgentProposal` (`dotnet ef migrations add`, B3/B5/B8
  tek konsolide zincirine additive; D011). Snapshot yalnız yeni entity bloğu eklendi
  (`git diff --stat`: 96 insertions).
- `Messaging/EfAgentCollaborationStore.cs` (yeni): sahibin transaction'ına katılır;
  unique ihlali (23505) idempotent upsert yarışında no-op'e düşer; onay/resume geçişleri
  `ExecuteUpdateAsync` koşullu UPDATE'lerdir.
- `Messaging/AgentCollaborationDependencyInjection.cs` (yeni): `AddAgentCollaboration`
  — settings + `IAgentCollaborationStore` + `AgentCollaborationService` (B10 DI ile
  tüketir). `AgentEventProjectionDependencyInjection.cs`'e tek satır `AddOptions()`
  (consumer'ın yeni IOptions bağımlılığı bu hat tek başına kurulduğunda da çözümlensin).

### 1.5 Python — kontrol consumer graph devamı (control.py, ADDITIVE; B7 bozulmaz)

`src/services/ai-agent-service/app/messaging/control.py`:

- `ControlResumeDriver` Protocol (yeni): `resume_requested` / `action_result` — B6/A8
  resume girişini (entrypoints.resume + A9 çalışma makinesi) kompoze eden sözcü.
- `ControlConsumerService(..., resume_driver=None)`; `build_control_consumer(...,
  resume_driver=None)`.
- Yol ayrımı: **cancel** her zaman B7 yolu (inbox-first, değişmedi); resume/action_result
  driver'sızken B7 yolu (kayıt + ACK); driver'lıyken B9 devamı:
  1. Salt-okuma inbox ön-okuması (sıralı tekrar teslim/ağ tekrarı → `duplicate`, driver çağrılmaz),
  2. bilinmeyen run → `ControlPolicyError` → DLQ (B7 davranışı korundu),
  3. driver (ACK kalıcı sorumluluk devrinden ÖNCE değil — plan kritik kontrolü),
  4. inbox kaydı BAŞARI SONRASI.
  Driver hatasında inbox YAZILMAZ ve teslim ACK'sız kalır → transport retry yeniden
  çağırır (en az bir kez devam). Çift graph etkisinden A9 çalışma makinesi korur
  (sonuçlanmış çalışmaya ikinci müdahale `validation_error`; retry sınıflandırmasında
  graph-hatası → ACK).
- B7'nin cancel/inbox/tür politikası davranışı değişmedi (`tests/control` Suite'i tam
  kapıda yeşil kaldı — 196/196).

### 1.6 Testler

- Python `tests/collab/` (yeni, `__init__.py`'li paket — L005; KENDİ vhost
  `blogapp_w6_b9` + scratch DB `blogdb_agent_b9` — L009): conftest (B7 kalıbı),
  `doubles.py` (`RecordingResumeDriver`, `is_test_double`), `test_control_continuation.py`:
  kabul, ağ sonrası tekrar (aynı message_id → duplicate, driver tek çağrı),
  **gerçek graph kanıtı** (driver, doğrulanmış backend sonucunu A9
  `run_collaboration`'a taşıyıp needs_input'taki çalışmayı RESOLVED/COMPLETED'a geçirir),
  eşzamanlı ikiz teslim → tek graph etkisi, bilinmeyen run → DLQ + inbox yok,
  driver hatası → ACK yok + inbox yok + yeniden çağrı, driver'lı cancel → B7 aynen.
- .NET `Api.Tests/Messaging/Collaboration/` (yeni; izole DB `blogdb_b9tests`):
  `AgentCollaborationSubmitTests` (12), `AgentCollaborationResumeTests` (7),
  `AgentCollaborationCommandTests` (4; açık eylem = oturumsuz Unauthorized, owner
  oturumdan çözülür, yabancı run Forbidden).

## 2. Kabul ölçütleri → kanıt (plan B9 satır 488)

| Ölçüt | Test | Sonuç |
| --- | --- | --- |
| Çift tıklama | `Submit_DoubleClick_SecondCallIsDuplicate_WithoutSecondRecordOrMessage` + eşzamanlı `Submit_ConcurrentRaces_ProduceExactlyOneAcceptedRecord` | Yeşil: Accepted + Duplicate; tek kayıt, tek mesaj |
| Ağ sonrası tekrar | Python `test_action_result_continues_graph_and_redelivery_is_duplicate` + .NET aynı testin ikinci çağrı kolu | Yeşil: duplicate, driver/tekrar kayıt yok |
| Değiştirilmiş proposal | `Submit_TamperedHash_...` + `Submit_StaleVersionAfterEdit_IsRejected` + `Resume_WithTamperedHash_IsRejected` | Yeşil: RejectedVersion; ret gerekçesiyle agent'a TEK mesaj; proposal proposed kalır |
| Geçersiz sahiplik | `Submit_ForeignOwner_...`, `Resume_ForeignOwner_...`, komut testleri | Yeşil: RejectedOwner/Forbidden; agent'a mesaj ÜRETİLMEZ |
| Onaysız işlem | `Resume_WithoutConfirmation_IsRejected_WritesNoMessage`; `Upsert_AloneNeverConfirms_...` | Yeşil: RejectedVersion ("öneri onaylanmadı"); mesaj yok |
| Backend kayıt hatası | `Submit_EditWhenBackendRecordFails_ReportsNothingAsAccepted` (8001 karakterlik özet → gerçek varchar(8000) yazım hatası) | Yeşil: DbUpdateException; onay kaydı + outbox mesajı + sürüm satırı YOK (tek transaction); sonraki geçerli onay çalışır |
| LLM metni onay kaynağı değildir | `Upsert_AloneNeverConfirms_EvenWhenSummaryContainsApprovalLanguage` ("onaylıyorum, kaydedin" içeren özet kaydedilir ama confirmed OLMAZ; outbox boş) + komut testleri (onayın tek girişi komut) | Yeşil |

## 3. Gerçek çalıştırılan kontroller (komut + çıktı)

1. `node docs/ai-agent-plan/source/tools/search.cjs verify` → `"valid": true` (30 kaynak/60 parça/23 aşama).
2. `cd src/services/ai-agent-service && python -m pytest tests/collab -q` →
   **7 passed** (son koşum; 3 kez koşuldu, hepsi yeşil).
3. `RABBITMQ_VHOST=blogapp_w6_b9net dotnet test src/backend/Presentation/Api.Tests --nologo -v q` →
   **Başarılı! Başarısız: 0, Başarılı: 196, Toplam: 196** (tam suite; B9'un 23 yeni testi
   + B1-B8 regresyonu + kullanıcının paralel B10 testleri).
4. Migration üretimi: `dotnet ef migrations add AddAgentProposal` (BLOGAPP_MIGRATION_CONNECTION
   env ile; tasarım zamanı fabrikası). `git diff --stat` snapshot: 96 ekleme / 0 silme.
5. L009 bulgusu (aşağıda F1): izole vhost'suz koşumlarda B3 Outbox/Relay testleri
   dalgalandı (9 → 2 → 25 → 29 başarısızlık arasında oynadı); izole vhost'ta seri koşum
   196/196. **Öneri**: .NET broker testlerinin standart koşumu `RABBITMQ_VHOST`
   override'ıyla faz başına vhost kullanmalı (B2/B3/B5 .NET testleri hâlâ paylaşılan
   `blogapp_dev`'de).

## 4. Bulgular

- **F1 (orta, ortam — L009'un .NET ayağı):** `Api.Tests/Messaging/Broker/BrokerTestEnvironment.cs:17`
  .NET broker testleri varsayılanda paylaşılan `blogapp_dev` vhost'unu kullanıyor;
  paralel koşumlarda (kullanıcının B10 doğrulama döngüsü — broker loglarında
  `blogapp_dev_b4`/`blogapp_dev_b5net` mağaza açılışları kanıtlı) B3 Outbox/Relay
  testleri birbirinin kuyruklarını tüketip dalgalandı. Çözüm: kapı koşumu
  `RABBITMQ_VHOST=blogapp_w6_b9net` izole vhost'una alındı (provizyon python conftest
  izin modeliyle) → 196/196. Kalıcı önlem önerisi (sahibi: orchestrator/B11):
  .NET broker testlerine faz başına vhost kuralı.

- **F2 (orta, ortam olayı — KÖK NEDEN BULUNDU VE DÜZELTİLDİ):** Orchestrator'ın ilk
  kapı koşumunda Collaboration koleksiyonunun TAMAMI (17 test, ~4 sn aralıklarla)
  düşmüştü. Kök neden: sabit test DB adı. İki eşzamanlı `dotnet test` koşumu
  (orchestrator kapısı + paralel B10 doğrulama koşumu — ikisi de tam suite'i
  koşar) ikisi de `blogdb_b9tests`'i DROP/CREATE etti; birinin
  `DROP ... WITH (FORCE)` çağrısı diğerinin canlı bağlantılarını kesti.
  Kanıt: postgres logları 09:45-09:51 UTC — `FATAL: database "blogdb_b9tests"
  does not exist` (3×) + `terminating connection due to administrator command`
  fırtınası; ayrıca düzeltme sırasında rebuild'in `MSB3027 ... kilitlendi:
  testhost (30348)` hatası paralel koşumu doğrudan gösterdi. **Düzeltme**
  (`AgentCollaborationDatabaseFixture.cs`): B9 test DB adı KOŞUM BAŞINA benzersiz
  (`blogdb_b9tests_<epoch-hex>`); init'te 2 saatten eski bayat koşum DB'leri
  süpürülür (güncel eşzamanlı koşumların DB'lerine dokunulmaz); dispose kendi DB'sini
  siler. Düzeltme sonrası: koleksiyon 23/23 + tam kapı 196/196 yeşil. Not: aynı
  sabit-ad riski B7 (`blogdb_b7tests`), B5 (`blogdb_b5tests`), B10
  (`blogdb_b10tests`) fixture'larında da vardır — sahiplerine bırakıldı (dosya
  sahipliği sınırı).

- **F3 (düşük, ortam olayı — giderildi):** İzole .NET vhost'u provizyonu sırasında
  yaptığım hatalı çağrı paylaşılan `blogapp` yönetici kullanıcısının tag'ini
  `none`'a düşürdü (management API erişimi 401 verdi). `rabbitmqctl set_user_tags
  blogapp administrator` + `change_password blogapp blogapp_dev` (compose
  bootstrap değeri) ile ~1 dk içinde geri alındı; `blogapp_dev` vhost yetkileri
  (GET /permissions/blogapp_dev/*) doğrulanarak bozulmadığı kanıtlandı. Ders:
  provizyon betikleri yalnız KENDİ fazın kullanıcılarını yazmalı (python conftest
  zaten öyle — benim betiğim blogapp'ı yanlışlıkla listeye almıştı).
- **F4 (düşük, sözleşme notu — bilinçli sapma):** Entegrasyon sahibi sözleşmesindeki
  `UpsertProposalAsync(run_id, proposal_id, content_hash, summary, owner_key,
  expires_at)` altı alanına ek olarak upsert kaydı makale üçlüsünü
  (`ArticleId`, `ArticleRevision`, `BaseContentHash`) taşır. Gerekçe: donuk B1
  `agent.action.result` şemasının allOf kuralı kabul kararında
  `applied_article_revision` ZORUNLU kılar; bu alan proposal olayından kaydedilmeden
  geçerli bir kabul mesajı üretilemez. `AgentProposalUpsert` kaydındaki ilk altı alan
  sözleşmeyle birebirdir; B10 tüketimini etkilemez.
- **F5 (düşük, tasarım kararı — raporlanır):** Ret bildirimleri: RejectedVersion
  (sürüm/süre) agent'a `outcome=rejected` + gerekçe ile TEK KEZ (deterministik
  message_id + outbox varlık kontrolü) bildirilir; **RejectedOwner'da mesaj
  ÜRETİLMEZ** — yetkisiz çağıranın agent kontrol akışına kayıt enjekte edememesi
  için (plan kritik kontrol: kimlik/run sahipliği backend tarafından doğrulanır).
  A9 tarafında herhangi bir validated_result çalışmayı RESOLVED'a taşımaktadır;
  bu, sahiplik redlerinin sessiz kalmasını zorunlu kılar.
- **F6 (düşük, sürüm bağlamı notu):** A9 agent tarafı sürüm hash'i
  `proposed_content` üzerinden (`compute_content_hash`), backend sürüm hash'i
  backend'in sakladığı düzenlenebilir özet üzerinden hesaplar. Sınırüstü bağ
  `proposal_id` + backend'in kendi sürüm disiplinidir; donuk
  `AgentResumeRequestedV1`/`AgentActionResultV1` payload'ları hash taşıyamadığından
  hash'ler arası eşitlik mesajlarda iddia edilmez (A9 checkpoint'i kendi
  `proposal_content_hash`'ini kendi içinde denetler).

## 5. Değişen dosyalar (B9 sahipliği)

Yeni:
- `src/backend/Core/Domain/Entities/AgentProposal.cs`
- `src/backend/Core/Application/Common/Options/AgentCollaborationSettings.cs`
- `src/backend/Core/Application/Common/Messaging/AgentCollaborationEnvelopeComposer.cs`
- `src/backend/Core/Application/Features/AgentFeature/Collaboration/` (4 dosya)
- `src/backend/Core/Application/Features/AgentFeature/Commands/SubmitCollaborationConfirmationCommand/`
- `src/backend/Core/Application/Features/AgentFeature/Commands/RequestCollaborationResumeCommand/`
- `src/backend/Infrastructure/Infrastructure/Persistence/Configurations/AgentProposalConfiguration.cs`
- `src/backend/Infrastructure/Infrastructure/Persistence/Migrations/20261012081319_AddAgentProposal(.Designer).cs`
- `src/backend/Infrastructure/Infrastructure/Messaging/EfAgentCollaborationStore.cs`
- `src/backend/Infrastructure/Infrastructure/Messaging/AgentCollaborationDependencyInjection.cs`
- `src/services/ai-agent-service/tests/collab/` (4 dosya)
- `src/backend/Presentation/Api.Tests/Messaging/Collaboration/` (4 dosya)

Değişen (additive):
- `Core/Application/Common/Interfaces/Data/IApplicationDbContext.cs` (+DbSet)
- `Core/Application/Features/AgentFeature/Events/AgentRunEventProjectionHandler.cs`
  (+store param, +proposal upsert kancası, +`ProposalUpsert` üyesi)
- `Infrastructure/Infrastructure/Persistence/AppDbContext.cs` (+DbSet)
- `Infrastructure/Infrastructure/Persistence/Migrations/AppDbContextModelSnapshot.cs`
- `Infrastructure/Infrastructure/Messaging/AgentEventProjectionConsumer.cs`
  (+IOptions ctor, +BuildProposalUpsert)
- `Infrastructure/Infrastructure/Messaging/AgentEventProjectionDependencyInjection.cs` (+AddOptions)
- `services/ai-agent-service/app/messaging/control.py` (driver + continuation yolu)
- `Api.Tests/Messaging/Projection/AgentEventProjectionConsumerTests.cs` (+AddOptions, +store kaydı)
- `Api.Tests/Messaging/Projection/AgentRunProjectionHandlerTests.cs` (ctor güncellemesi)

Dokunulmadı (donuk/kapsam dışı): `src/contracts/agent/**`, `app/messaging/contracts/**`,
B1 `Common/Messaging` dosyaları, `agent_core/**` (A9 paralel sahipliği), worker/intake/events
python modülleri, `Presentation/API/**` (B10 — kullanıcı paralel sahipliği).

## 6. Belirsizlikler ve sonraki adım

- **B10 bağlantı noktaları hazır:** controller'lar `AgentCollaborationService` +
  iki komutu DI ile tüketir; python tarafında `build_control_consumer(...,
  resume_driver=...)` sözleşmesi sabittir (üretim driver'ı worker
  `ExecutionDependencies` + checkpoint store ile kompoze edilir).
- Kullanıcının B10 çalışması sürerken tam suite iki kez dalgalandı (bkz. F1);
  kapı kanıtı izole vhost'ta 196/196 seri koşumdur. Orchestrator'ın
  bütünleştirme doğrulaması da izole vhost/seri koşum yapmalı (L009).
- E-posta bildirimi bu fazda YOK (plan uyarınca): talep kaydı ile bildirim ayrı
  sorumluluktur; e-posta eklenirse outbox + ayrı tekrar koruması istenir.
- Gerçek LLM/broker üretim sağlayıcısı yok; fixture/test-double başarısı gerçek
  sağlayıcı başarısı sayılmaz (gerçek broker + gerçek Postgres kullanıldı).

## 7. Kullanılan kaynaklar

[ENG-OUTBOX#C1] transactional outbox (iş verisiyle aynı transaction),
[ENG-OUTBOX#C2] relay duplicates → consumer idempotency (deterministic ret id +
inbox), [LG-INTERRUPTS#C1] resume girdisi Command ile aynı yürütmeye (driver
sözleşmesi), [LG-INTERRUPTS#C2] yeniden yürütme yan etkileri (at-least-once driver
+ A9 tek-etki guard'ı), [ASPNET-AUTH#C1/#C2] kimlik sunucuda doğrulanır (owner
oturumdan; istemci owner alanı yetki kaynağı değil).
