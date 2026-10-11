# B4 Faz Raporu — Python inbox ve kalıcı iş kabulü

Tarih: 2026-10-11 · Faz: B4 (W3) · Sahip: B4 implementasyon agent'ı
Plan: `docs/ai-agent-plan/02-rabbitmq-haberlesme-plani.md` §"Aşama B4 Python inbox ve kalıcı iş kabulünü uygula" (satır 309-337)

## 1. Yapılan işler

Plan B4 transaction adımlarının (1 envelope/payload doğrulama → 2 producer/tür
politikası → 3 consumer kapsamlı inbox benzersizliği → 4 run_id + payload_hash
idempotent iş kabulü → 5 AgentJob + accepted olayı outbox kaydı aynı
transaction'da → 6 commit → 7 broker ACK) tamamı uygulandı. Intake callback'i
graph'ı ÇALIŞTIRMAZ; `graph_executor` yalnız B6 bağlantı noktası olarak
enjekte edilebilir ve kabul akışı onu hiç çağırmaz.

### Yeni dosyalar

| Dosya | Sorumluluk |
| --- | --- |
| `src/services/ai-agent-service/app/messaging/db.py` | `AgentDbSettings` (env-only parola, `AGENT_DB_PASSWORD` yoksa fail-fast), asyncpg havuz fabrikası |
| `src/services/ai-agent-service/app/messaging/job_store.py` | `JobStore.accept_execution`: inbox + job + outbox tek transaction; `compute_payload_hash` (kanonik JSON SHA-256); `build_accepted_envelope` (yeni message_id, causation_id = komut message_id, event_sequence 0); outbox claim/mark/failure |
| `src/services/ai-agent-service/app/messaging/intake.py` | `IntakeService.handle_delivery`: `parse_envelope` (B1 sözleşmeleri, DONMUŞ) → tür/üretici politikası (`EXECUTE_COMMAND_TYPE` + yön) → JobStore → normal dönüş = ACK; `AgentContractError`/`IntakePolicyError`/`JobPayloadConflict` → B2 consumer base nack→DLX (requeue döngüsü yok) |
| `src/services/ai-agent-service/app/messaging/outbox.py` | `OutboxRelay.run_once`: claim (lease) → `publish_envelope` (confirm) → `published_at`; confirm kaybında kayıt beklemede kalır, `last_error` görünür |
| `src/services/ai-agent-service/migrations/` | Alembic 1.20.0 zinciri: `env.py` (async/asyncpg resmî şablon, `version_table_schema='agent'`), `alembic.ini` (parola yalnız env), `versions/20261011_0001_agent_schema.py`, `README.md` |
| `src/services/ai-agent-service/tests/intake/` | 14 test (`__init__.py`'li paket, L005 uyumlu): kabul/idempotency/çatışma/çökme pencereleri/gerçek consumer DLQ/relay |

### Değişen dosyalar

- `app/messaging/__init__.py`: yalnız B4 çıktılarının export'u.
- `pyproject.toml`: `asyncpg>=0.32,<0.33`, `alembic>=1.20,<1.21`,
  `sqlalchemy>=2.0,<2.1` (ve eksik olan `aio-pika>=9.5,<10` bildirimi).

## 2. Karar önerileri (D011 kilitleme)

- **Migration aracı: Alembic 1.20.0.** Arşivde migration aracı karşılığı yoktu
  (`search.cjs list --stage B4` → yalnız PG-ISOLATION, RMQ-CONFIRMS, AIO-PIKA,
  ENG-OUTBOX; `grep -ri alembic docs/ai-agent-plan/source/` → boş). Resmî belge
  ile doğrulandı: alembic.sqlalchemy.org/en/latest/front.html → "Alembic
  1.20.0", SQLAlchemy 2.0.0+ gerekir (WebFetch, 2026-10-11). Kurulu: alembic
  1.20.0 + SQLAlchemy 2.0.40 + asyncpg 0.32.0 (PyPI: asyncpg 0.32.0, Python
  >=3.9). Çalışma zamanı yolu ham asyncpg kullanır; SQLAlchemy yalnız
  migration zamanı aracıdır.
- **DB/şema kararı: blogdb_dev içinde `agent` schema'sı (D011'in şema seçeneği).**
  Gerekçe: (a) compose tek postgres container'ı paylaşır; ayrı DB yine aynı
  kümede olur, sahiplik ayrımı şema düzeyinde zaten sağlanır; (b) D011 metni
  şema seçeneğini açıkça adlandırır; (c) Alembic sürüm tablosu hedef şema
  içindedir (`agent.alembic_version_agent`) → migration sahipliği tek yerden
  doğrulanır; (d) backend EF şemasına (public) dokunulmaz, schema'lar arası FK
  yok (D011). `blogdb_dev`'e uygulandı: `upgrade head` → 0001, tablolar
  `inbox_messages`, `jobs`, `outbox_events` (aşağıda kanıt).
- **Inbox kapsamı:** PK `(consumer_name, message_id)` — planın "consumer
  kapsamlı inbox benzersizlik kontrolü"nün doğrudan karşılığı. Inbox satırı
  yalnız iş kabulü ile AYNI transaction'da doğar; ayrı "görüldü" işareti yoktur.
- **Çatışma yönetimi:** aynı run_id + farklı payload_hash → kabul transaction'ı
  geri alınır, inbox'a `status='conflict'` satırı AYRI transaction'da yazılır,
  `JobPayloadConflict` yükselir → mesaj DLX'e düşer. Tekrar teslim aynı
  message_id ile gelirse inbox kısa yolu ACK verir (çatışma mükerrer raporlanmaz).
- **Outbox relay:** claim `FOR UPDATE SKIP LOCKED` + `claimed_until` lease;
  confirm gelmeden kayıt beklemede kalır ([ENG-OUTBOX#C1]/[#C2],
  [RMQ-CONFIRMS#C1]). accepted olayı yeni mantıksal mesajdır: yeni message_id,
  `causation_id` = komutun message_id, `event_sequence=0` (B5 run başına atomik
  sıra üretimini devralır).

## 3. Gerçek test kanıtları

Ortam: blogapp-rabbitmq (RabbitMQ 4.2.9, healthy) + blogapp-postgres
(PostgreSQL 18.0, healthy; compose'dan çalışıyor, düzenlenmedi).

### GATE 1 — `python -m pytest src/services/ai-agent-service/tests/intake -q`

İki kez koşuldu: `14 passed` (71s) ve `14 passed` (56s). Test DB'si, gerçek
migration zinciriyle yaratılan scratch `blogdb_agent_test`'tir (blogdb_dev'e
test yazmaz); broker tarafında plan B2'nin onayladığı vhost izolasyonu
kullanılır (`blogapp_dev_b4` — gerekçe §5).

Senaryo → test eşlemesi (plan kabul ölçütleri):

| Plan senaryosu | Test | Kanıt |
| --- | --- | --- |
| Commit öncesi crash yeniden teslimle kurtarılır | `test_precommit_crash_is_recovered_by_redelivery` | pre_commit kancası transaction'ı geri alır (jobs=0), kanal ACK'sız kapatılır → broker `redelivered=True` ile yeniden teslim eder → tek job; executor çağrısı 0 |
| Commit sonrası crash çift iş yaratmaz | `test_postcommit_crash_does_not_duplicate_job` | commit kalıcı (jobs=1), ACK'sız kanal → yeniden teslim → `duplicate_inbox` → ACK; jobs hâlâ 1, outbox 1 |
| Tekrar teslim idempotent | `test_redelivery_same_message_id_is_inbox_idempotent`, `test_same_run_same_payload_new_message_id_is_duplicate_job` | aynı message_id → `duplicate_inbox`; farklı message_id + aynı hash → `duplicate_job` (ikinci accepted olayı üretilmez) |
| LLM çağrısı yok | tüm intake testlerinde `executor_spy.calls == []` | `graph_executor` hiç çağrılmaz |
| Aynı run_id farklı payload → çatışma | `test_same_run_different_payload_conflicts` + `test_conflicting_message_goes_to_dlq_and_job_survives` | `JobPayloadConflict` fırlar, inbox `conflict` satırı, mevcut job + accepted olayı korunur, mesaj DLQ'da |
| ACK commit'ten sonra | `test_consumer_acks_only_after_durable_accept` | gerçek `BrokerConsumer` döngüsünde job kalıcı olduktan sonra kuyruk boşalır |
| Sözleşme geçersiz / tür politikası | `test_invalid_contract_message_goes_to_dlq_without_job`, `test_wrong_type_message_is_policy_rejected_to_dlq` | DLQ'ya düşer, job/inbox oluşmaz, requeue döngüsü yok |
| Relay confirm + idempotency + hata | `test_relay_publishes_accepted_event_and_marks_published`, `test_relay_failure_keeps_record_pending_with_error`, `test_claim_lease_prevents_double_claim` | backend `agent.run.accepted` olayını tam zarf sözleşmesiyle alır (`parse_envelope` geçer; causation_id/event_sequence=0/producer agent-py); ikinci relay çevrimi yayınlanmış kaydı tekrar yayınlamaz; yayın hatasında kayıt pending + `last_error` + attempts=1; lease ikinci claim'i engeller |

### GATE 2 — pyproject değiştiği için tüm suite

`python -m pytest src/services/ai-agent-service/tests -q` → **386 passed,
1 skipped** (122s). B4 öncesi taban 277 passed/1 skipped idi (progress.md);
artış B4'ün 14 testi + paralel A4/B3 fazlarının yeni testleridir. messaging_broker
(B2) testleri aynı koşuda yeşil: regresyon yok.

### Migration döngüsü kanıtı (blogdb_dev)

`alembic upgrade head` → `downgrade base` → `upgrade head` çalıştırıldı:
`['alembic_version_agent','inbox_messages','jobs','outbox_events']` →
`['alembic_version_agent']` → tam küme; `version_num = '0001'`; indeksler
`ix_outbox_events_pending` (kısmi), `jobs_run_id_key` (UNIQUE — idempotent kabul
anahtarı), PK'ler. Son durum: blogdb_dev agent şeması head'de, `jobs` kayıt
sayısı 0 (temel teslim durumu).

### RAG kullanımı

`search --stage B4 --query "Consumer ACK kalıcı kabul ve tekrar teslim
idempotency"` ve `"Inbox deseni idempotent consumer mesaj tekrarı ve
transaction commit sonrası ACK"` çalıştırıldı. Teknik iddialar şu parçalara
dayanır: [RMQ-CONFIRMS#C1] (consumer ACK publisher confirm'den bağımsız),
[RMQ-CONFIRMS#C2] (ACK teslimin geldiği kanaldan, manuel ACK + sınırlı
prefetch), [ENG-OUTBOX#C1] (iş verisiyle mesaj aynı transaction'da),
[ENG-OUTBOX#C2] (relay tekrarlarına karşı consumer idempotency),
[PG-ISOLATION#C2] (Read Committed'ta eşzamanlı yazanın beklemesi — unique
yarışı yeniden okumayla çözme), [PG-ISOLATION#C1], [AIO-PIKA#C1] (robust
bağlantı). Kaynak kimlikleri kod yorumlarına da işlendi.

## 4. Karşılaşılan hatalar ve düzeltmeler (yeni ders adayları)

1. **Alembic "sessiz rollback":** env.py'de sürüm tablosu öncesi `CREATE
   SCHEMA` aynı bağlantıda commit'siz yapılınca alembic'in transaction'ı iç
   içe geçti; `upgrade` "başarılı" göründü, hiçbir tablo kalmadı. Düzeltme:
   schema garantisi ayrı commit'li `run_sync` adımına taşındı
   (`migrations/env.py:_ensure_agent_schema`). Ayrıca downgrade şemayı CASCADE
   ile silerse alembic kendi sürüm tablosunu güncelleyemez → 0001 downgrade
   yalnız tabloları kaldırır.
2. **asyncpg jsonb → str:** asyncpg jsonb kolonları str döndürür; relay'in
   `AgentEnvelope.model_validate(dict(row["envelope"]))` satırı
   `ValueError` ile patladı (relay ilk koşuda hiç yayınlayamadı — test
   yakaladı). Düzeltme: `outbox._decode_envelope` (str/dict ikisini kabul eder).
3. **Paralel B3 girişimi (ortam):** B3'ün .NET testleri AYNI broker vhost'unu
   (blogapp_dev) kullanıyor; broker log kanıtıyla `b3-purge` / `b3-drain` /
   `backend-net-tests` bağlantıları benim test mesajlarımı tüketiyordu
   (publish confirmed ama derinlik 0). Ayrıca B3'ün restart senaryosu broker'ı
   yeniden başlattı (management 180s erişilemez oldu). Düzeltme: B4 testleri
   planın B2 kuralına uygun **ayrı vhost** (`blogapp_dev_b4`) kullanır; izin
   modeli B2 ile birebir. Bu bir test-izolasyon kararıdır, ürün kodu vhost
   ayarını değiştirmez (BrokerSettings default'u blogapp_dev kalır).
4. **Management API yükle dayanıklılık:** B3 yükü altında management HTTP
   keep-alive bağlantıları kopuyordu (RemoteDisconnected). Kuyruk derinliği ve
   purge AMQP'ye taşındı (passive declare `declaration_result.message_count`,
   `queue.purge()`); provisioning isteklerinde artan backoff'lu retry var.
5. **Yarım kayıt çakışması (L006 akrabası):** paralel A4 agent'ı
   `agent_core/routing.py`'yi düzenlerken eksik import'la bıraktı
   (`NameError: Field`); test toplaması bir an engellendi. Beklendi ve edit
   tamamlandıktan sonra yeniden koşuldu; dosya sahipliği çakışması olmadı.

## 5. Sınırlar ve B7/B6'ya notlar

- **Transient DB hatası → DLQ:** B2 consumer base'in tek istisna politikası
  gereği geçici DB kesintisinde de mesaj DLQ'ya düşer. Transport hatası /
  kalıcı sözleşme hatası ayrımı ve gecikmeli retry planın B7 kapsamıdır
  (dispatch'te kapsam dışı).
- **Deadline kontrolü:** intake deadline'ı saklar (`jobs.deadline_at`) ama
  süresi geçen işi REDDETMEZ; plan bu kontrolü B7'ye ("Deadline'ı intake,
  retry, recovery ve worker başlangıcında kontrol et") ve B6'ya verir.
- **Outbox relay sürekli döngüsü:** B4'te `run_once` + testler; sürekli
  çalışma (`run_forever` benzeri yaşam döngüsü) FastAPI/lifespan host'u ile
  B5/B6 konu bağlamında kurulabilir. Relay yalnız accepted olayını taşır;
  progress/outcome olayları B5'te aynı tabloyu yeniden kullanır.
- **event_sequence:** accepted olayı 0 ile başlar; run başına atomik sıra
  üretimi B5'in sorumluluğudur (plan satır 355).
- **Test izolasyon vhost'u** (`blogapp_dev_b4`): yalnız tests/intake conftest'i
  kullanır; üretim vhost'u product kodunda değişmedidir. Süit paralel başka
  agent'la koşarken bile kararlıdır (iki ardışık koşu + tam suite kanıtlı).

## 6. Çıktı dosyaları

- `src/services/ai-agent-service/app/messaging/{db,job_store,intake,outbox}.py` (yeni)
- `src/services/ai-agent-service/app/messaging/__init__.py` (export)
- `src/services/ai-agent-service/migrations/` (yeni: env.py, alembic.ini, script.py.mako, versions/20261011_0001_agent_schema.py, README.md)
- `src/services/ai-agent-service/pyproject.toml` (bağımlılıklar)
- `src/services/ai-agent-service/tests/intake/` (yeni, 14 test; **not: `tests/` .gitignore'da — L001 gereği orchestrator force-add ile commit etmeli**)
- `docs/ai-agent-plan/phase-reports/B4-rapor.md` (bu dosya — aynı şekilde force-add)
