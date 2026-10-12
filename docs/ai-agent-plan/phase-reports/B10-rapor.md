# B10 Faz Raporu — UI gateway ve yönetim gözlemlerini bağla

Tarih: 2026-10-12 · Sahip: B10 implementasyon agent'ı · Branch: `feature/ai-agent-integration`

## 1. Kapsam ve yaklaşım

Plan bölümü: `docs/ai-agent-plan/02-rabbitmq-haberlesme-plani.md` "Aşama B10 UI gateway
ve yönetim gözlemlerini bağla" (satır 494-541), tablo birebir uygulandı. RAG doğrulaması
faz başında yapıldı: `node docs/ai-agent-plan/source/tools/search.cjs verify` → `valid:true`
(30 kaynak/60 parça/23 aşama); B10 CONTEXT'i [NEXTJS-APP#C1], [NEXTJS-APP#C2],
[SIGNALR-HUBS#C1], [SIGNALR-HUBS#C2], [ASPNET-AUTH#C2] ile alındı. Hub'ın durum
TAŞIMAMASI ve IHubContext yayını [SIGNALR-HUBS#C1]/[SIGNALR-HUBS#C2] ile uyumludur;
rol yetkilendirmesi endpoint düzeyinde `RequireRole("Admin")` ile kuruldu.

## 2. Endpoint'ler (plan tablosu, birebir)

`src/backend/Presentation/API/Endpoints/AgentEndpoints.cs` — hepsi `/api/v{version}/agent`
altında; **Python'a HTTP çağrısı yapılmaz** (yazma → outbox, okuma → projection):

| Endpoint | Davranış |
| --- | --- |
| `POST /api/v1/agent/messages` | B3 `AcceptAgentRunCommand` MediatR üzerinden; **202 Accepted** + run_id; idempotencyKey opsiyonel (yoksa sunucu üretir) |
| `POST /api/v1/agent/research` | Aynı kabul hattı, `modePreference=deep_research` backend'de sabitlenir |
| `GET /api/v1/agent/runs/{runId}` | Sahiplik + durum + **izin verilen sonuç** (`AgentResultPresentationGuard` B8 denetimi; maskelenme kararı bu endpoint'indir — guard yalnız okur) |
| `GET /api/v1/agent/runs/{runId}/events` | Commit edilmiş projection'dan (`agent_event_inbox`, `status='applied'`) JSON replay (`?after=` imleci, `limit≤200`) **veya** `Accept: text/event-stream` ile SSE (2 sn yapışkan yoklama, terminalde `done`, 300 sn üst sınır, `timeout` olayı + imleç) |
| `POST /api/v1/agent/runs/{runId}/cancel` | B7 `CancelAgentRunCommand`; 202 + `requested/replay/already_terminal` ("iptal isteniyor" terminal değildir) |
| `POST /api/v1/agent/runs/{runId}/resume` | B9 sözleşmesi: beklenen input/proposal sürümü commit edilmiş projection'a göre doğrulanır; `agent.resume.requested` zarfı üretici (`AgentResumeEnvelopeComposer`) ile outbox'a yazılır; 202/409 |
| `POST /api/v1/agent/feedback` | Run sahipliği + 1-5 puan + yorum ≤2000; **idempotent** (feedback_key → deterministik GUID, PK tekilleştirmesi) |
| `GET /api/v1/agent/admin/observations` | `RequireRole("Admin")`; plan admin listesinin tamamı (§4) |

Kimlik: JWT (`userId` claim) veya sunucu tarafı misafir oturumu. Misafir kimliği
`AgentGuestSessionService` (Presentation) ile **HttpOnly çerezden** (`blogapp_agent_guest`,
kanonik UUID, SameSite=Lax, IsEssential, 180 gün) çözülür (K5); istemci owner alanı
yetki kaynağı değildir, endpoint istemciden owner ALMAZ.

## 3. Resume sözleşmesi ve B9 paralelliği

- `IAgentResumeStateStore` portu (Application): `ProjectionAgentResumeStateStore` commit
  edilmiş projection'dan en son uygulanan `agent.run.needs_input` event_sequence'ini
  **InputVersion** olarak okur. Checkpoint referansı B9 iş birliği deposu kaydıdır;
  B10 onu UYDURMAZ (fail-closed): checkpoint bilinmiyorsa komut üretilmez, 409 +
  "checkpoint referansı henüz backend'e kaydedilmedi (B9 iş birliği deposu beklemede)"
  döner. Test yolu `TestResumeStateStore` double'ı ile uçtan uca kanıtlandı (outbox
  satırı + B1 validator geçişi). Python kontrol consumer'ı resume komutlarını B9'a
  kadar kalıcı ACK'lar (`app/messaging/control.py:132`) — hat uyumlu.
- **B9 eşzamanlı çakışma notu (entegrasyon sahibine):** B9 paralel çalışırken kendi
  `RequestCollaborationResumeCommand`, `AgentCollaborationEnvelopeComposer`,
  `IAgentCollaborationStore`/`EfAgentCollaborationStore`, `AgentProposal` entity'si ve
  `AddAgentProposal` migration'ını ekledi; `AgentRunEventProjectionHandler` ctor'una
  `IAgentCollaborationStore` ekledi. B10'un `ResumeAgentRunCommand` + composer'ı ile
  B9'un resume komutu/composer'ı işlevsel olarak örtüşüyor — merge'de BİRİ seçilmeli.
  Program.cs'te B9'un `AddAgentCollaboration` kaydını B10 (DI kablolama sahibi) ekledi.

## 4. Admin gözlemleri (plan B10 admin listesi, hepsi mevcut tablolardan OKUMA)

`GetAgentObservationsQuery` + `GET /api/v1/agent/admin/observations` (Admin rolü):

- Kabul backlog'u: Accepted run sayısı + en eski iş yaşı + pencere içi yeni run.
- Outbox: Pending/Claimed/Published/**DeadLettered** derinlikleri; en eski pending yaşı;
  kabul→confirm ortalama ve **p95 yayın gecikmesi**; attempt>0/LastError kayıtları (confirm hata sinyali).
- Projection inbox: applied/**duplicate**/**stale**/quarantined sayıları (B5 idempotency izleri).
- İş süreleri: kabul→terminal ort/max; **iptal gecikmesi** (ilk cancel outbox kaydı → terminal cancelled);
  mod ve terminal dağılımı; kalite sinyali (unresolved_questions taşıyan completed sonuçlar).
- Geri bildirim özeti: toplam, ortalama puan, puan dağılımı.
- Python `agent.jobs` (queue backlog, en eski bekleyen, **lease'i bitmiş running** = recovery
  adayı, retry'lı bekleyen): **ayrı salt-okunur bağlantıyla** (`IAgentSystemDbConnectionFactory`,
  Presentation'da NpgsqlConnection; EF bağlamı paylaşılmaz), `to_regclass` guard'lı —
  şema yoksa bölüm null (hata değil). Yeni ağır altyapı YOK (D011'e aykırı FK/yazma yok).

Frontend: `src/app/mrbekox-console/dashboard/agent/page.tsx` (6 kart) + konsol
paneline additive bağlantı kartı (`dashboard/page.tsx`).

## 5. UI (src/frontend/blogapp-web)

- `src/types/agent.ts`, `src/lib/agent-api.ts` (apiClient, withCredentials), `src/lib/agent-i18n.ts`
  (tr/en sözlük; global i18n çerçevesi kurulmadan panel kapsamında).
- `src/components/agent/article-agent-panel.tsx`: soru + **açık makale bağlamı** onay kutusu;
  auto/fast/analysis/deep_research seçimi (deep_research ayrı uç noktaya gider);
  **kabul → başlama → tamamlanma AYRI** `StatusStep` şeridi (accepted/starting/started/
  terminal/cancelling); terminal sonuçta answer/report, kaynak kartları (article →
  `source_id` anchor'ından bölüm bağlantısı; web → rel="noopener noreferrer nofollow"),
  içerik-kullanılamıyor maskesi; iptal butonu ("iptal isteniyor" durumu ayrı gösterilir);
  1-5 idempotent geri bildirim; `aria-live="polite"` durum duyuruları; tr/en metinler.
- **Yenileme sonrası geri dönüş:** run_id makale başına localStorage'da; mount'ta
  `GET /runs/{id}` + `GET /events?after=` replay. Canlı ilerleme: `AgentRunsHub`
  `RunUpdated` (env.client.ts'e `AGENT_RUNS_HUB_URL` eklendi, `withCredentials: true`)
  + 4 sn GET replay yedeği (hub yoksa tek başına yeterli — planın "alternatif/eşdeğer" kuralı).
- Makale sayfasına ekleme additive (`posts/[slug]/page.tsx`); mevcut sayfalar kırılmadı.

## 6. Güvenlik sertleştirmeleri (kabul ölçütü: erişim ENGELİ)

1. **AgentRunsHub sahiplik denetimi (B5 dosyasına B10 düzeltmesi):** `SubscribeToRun`
   artık run sahipliğini backend AgentRun kaydından doğrular (JWT claim veya misafir
   çerezi); yabancı bağlantı `HubException` ile reddedilir — hub bildirimi terminalde
   sonuç snapshot'ı taşıyabildiğinden grup üyeliği savunmasızdı.
2. **correlation_id sözleşme hatası düzeltmesi (gerçek üretim hatası):**
   `ICurrentUserService.CorrelationId` üretimde HTTP TraceIdentifier döner (UUID
   değil); resume zarfı `AgentContractValidator`'da reddediliyordu
   (kanıt: `AgentResumeEnvelopeComposerTests` "correlation_id kanonik UUID bekleniyor").
   Resume **ve** B7 cancel handler'ına UUID guard eklendi (UUID olmayan iz → yeni GUID).
   B7 cancel testleri bu hatayı maskeliyordu (TestCurrentUser.CorrelationId=null).
3. Endpoint'lerde run_id kanonik UUID doğrulaması; SSE/sorgularda sahiplik her sayfada yeniden denetlenir.

## 7. Program.cs DI kablolaması (B8 F2 dahil)

`builder.Services.AddRabbitMqAgentMessaging → AddAgentOutbox → AddAgentEventProjection →
AddAgentContentEvents (B8 F2: bu fazda bağlandı) → AddAgentCollaboration (B9)`;
`AgentTopologyInitializerHost` (K3: başlangıçta declare; broker kapalıysa **fail-fast
olmayan** kabul yolu — 10 denemelik geri çekilmeli bildirim, uygulama kalkmaya devam eder;
relay/consumer kendi döngülerinde toparlar). Misafir oturumu, resume store, feedback store,
gözlem bağlantı fabrikası kayıtları. `appsettings.Development.json`'a RabbitMq bölümü
(dev broker kimlikleri — mevcut dev-pattern: `settings.py`/`BrokerTestEnvironment` ile aynı;
AÇIK RİSK: B0'daki dev parola bulgusunun devamı).

## 8. Testler ve doğrulama (gerçek çıktılar)

Yeni test dosyaları: `Api.Tests/Agent/` — `AgentB10DatabaseFixture` (scratch **blogdb_b10tests**,
L009), `AgentRunStatusQueryTests` (sahiplik: yabancı run 403, kimliksiz 401, misafir erişimi;
durum ayrıştırma; B8 maskeleme; replay imleci + stale olmayan replay), `AgentResumeAndFeedbackCommandTests`
(checkpoint double ile outbox+zarf; bayat sürüm 409; fail-closed no-outbox; yabancı 403;
terminal reddi; feedback idempotent replay/403/doğrulama), `AgentObservationsQueryTests`
(sayılar, gecikme, iptal gecikmesi, feedback özeti, agent şeması null düşme),
`AgentResumeEnvelopeComposerTests` (B1 validator birebir uyum).

| Kapı | Komut | Sonuç |
| --- | --- | --- |
| dotnet | `dotnet test src/backend/Presentation/Api.Tests --nologo -v q` (izole vhost `blogapp_w6_b10`, sessiz pencere) | **196/196 BAŞARILI** (0 başarısız; iki bağımsız koşum: 3m39s ve 3m46s — ikincisi per-process DB düzeltmesiyle) |
| frontend | `npm --prefix src/frontend/blogapp-web run build` | **exit=0** ("✓ Compiled successfully", 19/19 statik sayfa) |
| python | `python -m pytest src/services/ai-agent-service/tests -q --ignore=...` (gate'teki ignore listesi) | **626 passed, 1 skipped** (44s) |
| RAG | `node docs/ai-agent-plan/source/tools/search.cjs verify` | `valid:true` |

**Süreç bulguları (L009 teyidi + düzeltme):** Orchestrator doğrulama koşumu, B9'un
AYNI test projesinde eşzamanlı `dotnet test` süreciyle çakıştı ve 24 başarısızlık
gösterdi (9'u B10 koleksiyonundan, 15'i B3 acceptance/relay koleksiyonlarından).
Ayırt edici imzalar: (a) iki sürecin aynı sabit-adlı scratch DB'yi yönetmesi
(`42P01 relation "outbox_messages" does not exist`, `57P01 terminating connection
due to administrator command` — ikinci sürecin fixture init'i birincinin DB'sini
DROP ediyor); (b) bin DLL kilidi (`testhost ... tarafından kilitlendi` — ikinci
sürecin build'i); (c) paylaşılan vhost bağlantı çakışması (`BrokerUnreachableException`;
RABBITMQ_VHOST set edilmediğinde varsayılan blogapp_dev'de B9'un broker testleriyle).
Kontrol koşumu (B10 testleri hariç) 169/170; B10 testleri izlemede birden çok kez 26/26.
**Düzeltme (B10 sahipliğinde):** `AgentB10DatabaseFixture` DB adı SÜREÇ BAŞINA
benzersiz yapıldı (`blogdb_b10tests_p{ProcessId}`; DROP'lar yalnız kendi DB'sine)
— B10 koleksiyonu eşzamanlı ikinci test sürecine artık bağışık; bin kilidi ve
B3/B5/B7/B8/B9 sabit-adlı fixture yarışları ise bu fazın koduyla çözülemez
(oranlar orchestrator'ın SERİ koşum kuralına ya da ilgili faz sahiplerinin aynı
desene geçmesine kalır). Kanıt zinciri: sessiz pencerede tam gate
`RABBITMQ_VHOST=blogapp_w6_b10 dotnet test src/backend/Presentation/Api.Tests
--nologo` → **196/196** (iki kez: 3m39s ve 3m46s; ikinci koşum per-process DB ile).

## 9. Bilinen sınırlar / çalıştırılmayan kontroller

- **SSE akışının kendisi otomatik testte yok** (JSON replay handler testleriyle kapsılı;
  SSE ince döngüdür) — canlı el ile doğrulama yapılmadı.
- **Uçtan uca tarayıcı akışı (mobil/masaüstü) canlı koşulmadı:** worker/model sağlayıcısı
  devrede değil + B9 paralel; UI build + handler-düzey entegrasyon testleriyle sınırlı.
  Ana promptun "tam uçtan uca başarı iddiasını eksik bileşenle verme" kuralı gereği
  bu koşum orchestration'a kalmıştır (W6 bütünleştirmesi).
- Hub sahiplik denetiminin otomatik testi yok (SignalR host gerektirir); kod incelemesiyle
  kanıtlandı.
- Geri bildirim kaydı geçici olarak `agent_event_inboxes` tablosundadır
  (`backend-agent-feedback` tüketici adı; planın "mevcut projection tablolarından okuma"
  hedefiyle uyumlu, migration sahipliği bu fazda değildir). B9/B11 ayrı tabloya taşıyabilir —
  port (`IAgentFeedbackStore`) tek değişim noktası.
- Üretimde `resume` akışı, B9 checkpoint/proposal deposu kaydını yazana dek fail-closed 409 döner (tasarım gereği).
- B9 ile örtüşen resume komutu/composer'ının merge kararı entegrasyon sahibindedir (§3).

## 10. Değişen dosyalar (B10 sahipliği)

- Ekleme: `Endpoints/AgentEndpoints.cs`, `Services/AgentGuestSessionService.cs`,
  `Services/AgentSystemDbConnectionFactory.cs`, `Services/AgentTopologyInitializerHost.cs`,
  `Common/Messaging/AgentResumeEnvelopeComposer.cs`,
  `Features/AgentFeature/Commands/ResumeAgentRunCommand/` (3 dosya),
  `Features/AgentFeature/Commands/RecordAgentFeedbackCommand/` (3 dosya),
  `Features/AgentFeature/Queries/GetAgentRunQuery/`, `GetAgentRunEventsQuery/`,
  `GetAgentObservationsQuery/` (DTO + handler), `Api.Tests/Agent/` (6 dosya),
  frontend: `types/agent.ts`, `lib/agent-api.ts`, `lib/agent-i18n.ts`,
  `components/agent/article-agent-panel.tsx`, `app/mrbekox-console/dashboard/agent/page.tsx`,
  `Api.Tests/xunit.runner.json`.
- Değişiklik: `Program.cs` (DI kablolama + endpoint kaydı), `Hubs/AgentRunsHub.cs`
  (sahiplik), `Commands/CancelAgentRunCommand/CancelAgentRunCommandHandler.cs`
  (correlation guard), `Api.Tests/Messaging/Cancel/AgentBackpressureTests.cs`
  (B9 ctor eklemesine no-op store uyumu — B9'un kırması üzerine, kapıyı açmak için),
  `Api.Tests/Agent/AgentB10DatabaseFixture.cs` (per-process DB adı — çapraz-süreç
  DROP yarışına karşı, §8),
  `Api.Tests/BlogApp.Presentation.Api.Tests.csproj` (runner.json kopya),
  frontend `posts/[slug]/page.tsx`, `mrbekox-console/dashboard/page.tsx`,
  `lib/env.ts`, `lib/env.client.ts`, `appsettings.Development.json` (RabbitMq bölümü).

## 11. Plan kabul ölçütleri karşılama durumu

| Ölçüt (plan satır 541) | Durum |
| --- | --- |
| Mobil/masaüstü uçtan uca akışlar | Kısmi: kabul→ilerleme→terminal akışları handler-düzey gerçek Postgres üstünde test edildi; UI derlendi; **canlı tarayıcı E2E koşulmadı** (§9) |
| Başka kullanıcının run'ına erişim engeli | Doğrulandı: 403 testleri (durum/replay/resume/feedback) + hub sahiplik denetimi |
| Yenileme ve replay | Doğrulandı: `after` imleçli replay + localStorage geri dönüş + canlı/hub + yedek yoklama tasarımı |
