# B6 Faz Raporu — Yürütme worker ve kesinti sonrası recovery

- **Tarih:** 2026-10-12
- **Rol:** B6 implementasyon agent'ı (dağıtık worker sistemleri: lease, fencing, recovery)
- **Plan:** `docs/ai-agent-plan/02-rabbitmq-haberlesme-plani.md` "Aşama B6" (satır 374–400)
- **Ortam:** RabbitMQ 4.2.9 (docker `blogapp-rabbitmq`, healthy), PostgreSQL 18 (`blogapp-postgres`, healthy), Python 3.13.9, pydantic 2.11.7, aio-pika 9.5.8, alembic 1.20.0, asyncpg 0.32.0. Test izolasyonu (L009): özel vhost `blogapp_w5_b6` + özel scratch DB `blogdb_agent_test_b6`; parola yalnız `docker/.env`'den çalışma anında okundu (koda/fixture'a girmedi).

## 1. Yapılan işler

Plan B6 maddelerinin karşılıkları:

| Plan maddesi (B6:386–398) | Karşılık |
| --- | --- |
| Kalıcı iş kaydı + lease_owner/lease_until/execution_attempt/fencing_token | `agent.jobs` genişletildi (migration 0003); `claim_next_job` FOR UPDATE SKIP LOCKED ile claim |
| Lease yenilemesi graph ilerlemesine bağlı | `worker._LeaseWatch`: arka plan döngüsü + çekirdek ilerleme sinyallerinde heartbeat (`_WorkerProgressSink.publish` → `watch.heartbeat`) |
| Süresi geçen işi SINIRLI recovery ile yeniden sahiplenme | `claim_next_job` recovery koşulu (`lease_until < now()` + `execution_attempt < max`); sınırı aşan iş `fail_expired_jobs_beyond_attempts` ile kalıcı kapanır |
| Eski worker'ın sonucu ezmesini engelleme (fencing) | `complete_job`/`fail_job` ATOMİK guard: `status='running' AND fencing_token=$ AND NOT EXISTS(cancel_intents)`; koşul bozulursa `rejected` + gerekçe (`fencing_mismatch`/`not_running`/`cancel_requested`/`not_found`) |
| A8 checkpoint girişleriyle yarım işi devam ettirme | `worker._try_resume`: checkpoint varsa A8 `resume` girişi; `execution_id` run başına kararlı (`job-{run_id}`); uyumsuz checkpoint anlaşılır `validation_error` terminali |
| Tamamlanmış işi duplicate komutla tekrar başlatmama | claim yalnız `accepted`/`queued` seçer; terminal iş claim edilmez; terminal yazımı idempotent reddedilir |
| Konuşma geçmişini backend snapshot'ına göre koruma | `worker._build_context`: payload `conversation_history` aynen çekirdeğe taşınır; worker tur eklemez/çıkarmaz (test kanıtı §3) |
| Derin araştırma için AYRI kapasite (fast\|research) | `queue_class` kolonu; rota `deep_research` çıkınca worker işi `research` kuyruğuna ERTELER (`requeue_job(queue_class='research', reset_attempt=True)`); router kararı çekirdekte üretildiği için backend sınıflandırmaz (B4 kuralıyla uyumlu) |
| Broker ACK ≠ graph tamamlanması | Worker broker tüketmez; yürütme hatası requeue ile DEĞİL job retry/recovery politikasıyla (lease bitişi → recovery; deneme sınırı → sweep) |
| Deadline/bütçe yeniden yürütmede SIFIRLANMAZ | `deadline_at` iş kaydında kalır; recovery aynı deadline'ın kalanında çalışır; BudgetStore aynı run_id ile paylaşılır (test kanıtı §3) |
| Belirsiz dış model çağrı maliyeti kaydı | Kesilen denemelerin maliyeti `result_json.uncertain_usage` alanına A2'nin `uncertain` işaretiyle yazılır (`worker._result_json`) |

## 2. Değişen dosyalar

| Dosya | Sahiplik | Değişiklik |
| --- | --- | --- |
| `src/services/ai-agent-service/migrations/versions/20261012_0003_job_leases_and_cancel_intents.py` | B6 (yeni) | `agent.jobs`: `queue_class`(default 'fast', CHECK fast\|research), `lease_owner`, `lease_until`, `execution_attempt`(default 0), `fencing_token`(bigint, `agent.job_fencing_seq` global monoton dizi), `result_json`, `started_at`; `ck_jobs_status`'a 'queued'/'running' eklendi (B4'ün 'accepted' değeri KORUNDU); `agent.cancel_intents` (run_id PK, requested_at, requested_by); claim için iki kısmi endeks (`ix_jobs_claimable`, `ix_jobs_expired_running`). Downgrade roundtrip test edildi. |
| `src/services/ai-agent-service/app/messaging/job_store.py` | B6 (ADDITIVE — B4 `accept_execution` ve B5 yolları değişmedi; diff +517 satır, 0 silme) | `claim_next_job` (CTE + FOR UPDATE SKIP LOCKED; deadline/iptal niyeti filtreleri; SINIRLI recovery), `renew_lease` (yalnız sahibiyseniz), `complete_job`/`fail_job` (ATOMİK guard + terminal olayı AYNI transaction'da sıra tahsisiyle outbox'a yazma — `outbox_event` opsiyonel parametre), `requeue_job` (needs_input/erteleme), `release_job_lease`, `fail_expired_jobs_beyond_attempts` (sweep), `has_cancel_intent`, `fetch_job_full`, `count_cancel_intents` |
| `src/services/ai-agent-service/app/messaging/worker.py` | B6 (yeni) | `ExecutionWorker` (run_once/run_forever/sweep), `WorkerSettings`, `ExecutionDependencies`, lease watch, metered model, progress köprüsü, terminal/needs_input/erteleme sonuç yol haritası |
| `src/services/ai-agent-service/tests/worker/**` | B6 (yeni paket, `__init__.py`'li — L005) | conftest (vhost/DB/topology kurulumu), helpers, 32 test (4 dosya; bağımsız inceleme 2. turunun iki kanıt boşluğu kapandı: gather'lı eşzamanlı claim yarışı + bütçe-rezervasyon korunması, ayrıca progress-tetikli heartbeat sondası) |
| `docs/ai-agent-plan/phase-reports/B6-rapor.md` | B6 (yeni; L001 gereği orchestrator force-add ile commitler) | Bu rapor |

**Dokunulmayan donuk alanlar:** `src/contracts/agent/**`, `app/messaging/contracts/**`, `events.py` (B5 kural kaynağı — worker scope kontrolünü `AgentEventPublisher._check_source_scope`'a DELEGASYONLA yaptı kopyalamadı), `intake.py`, `agent_core` (yalnız import; A8 `resume`/`prepare_and_route` girişleri kullanıldı), `.NET` tarafı. `control_store.py`/`control.py` yazılmadı (B7).

## 3. Gerçek test kanıtları

### 3.1 Migration zinciri (scratch DB `blogdb_agent_test_b6`)

```
alembic upgrade head → 0001 → 0002 → 0003 OK
alembic downgrade 0002 → OK; tekrar upgrade head → OK (roundtrip)
```

### 3.2 GATE — komut ve sonuç

Komut (repo kökünden, görevde tanımlanan haliyle):

```
python -m pytest src/services/ai-agent-service/tests/worker -q
```

Sonuç (son kesin koşum): **32 passed, 1 warning in 38.68s**. Paket 9 kez koşuldu; hepsi yeşil (28 testlik sürüm: 57.08s / 62.10s / 77.17s / 68.07s / 51.80s / 30.37s / 29.79s; 32 testlik sürüm: 38.68s / 46.66s). Warning, alembic `path_separator` deprecation'ıdır (B4/B5 paketlerindeki ile aynı, bu fazın konusu değil).

Kabul ölçütlerinin (plan B6:400) test karşılıkları:

| Kabul ölçütü | Test |
| --- | --- |
| worker kill/restart | `test_worker_lifecycle.py::test_worker_kill_and_restart_resumes_from_checkpoint` — Worker A `prepare_and_route` sonrası model çağrısında çöker (iş running+lease kalır); Worker B lease bitmiş işi devralır (`recovered=True`, `attempt=2`) ve `resume` yoluyla tamamlar; `run_resumed` ilerlemesi outbox'ta kanıtlanır; konuşma geçmişi prompt'ta korunur; `deadline_at` değeri değişmez |
| lease kaybı | `test_worker_contention.py::test_lease_renewal_refusal_aborts_execution_midflight` — iş atomik olarak B'ye geçince A'nın yenilemesi fencing reddiyle düşer, iptal sinyali model çağrısını keser (`cancelled_while_waiting=True`), terminal YAZILMAZ; `test_live_worker_with_lost_lease_cannot_overwrite_new_owner` — canlı A'nın `complete_job`'u `fencing_mismatch` ile reddedilir, sonucu yazılamaz, B tamamlar |
| iki worker yarışı | **Gerçek eşzamanlılıkla (asyncio.gather, kendi DB bağlantılarında):** `test_concurrent_claims_race_single_job_exactly_one_wins` (tek işe eşzamanlı 2 claim → 1 kazanan, kaybeden None) ve `test_concurrent_claims_on_multiple_jobs_get_distinct_jobs` (4 işe eşzamanlı 4 claim → 4 ayrı iş, 4 benzersiz fencing token) — SKIP LOCKED çekişim altında kanıtlanır. Sıralı WHERE-filtre davranışı ayrıca `test_sequential_second_claim_gets_nothing_while_lease_active`'te sabit. + fencing testleri + `test_job_store_claims.py::test_fencing_rejects_stale_attempt_result` |
| checkpoint'ten devam | kill/restart testi + `test_job_store_claims.py` terminal-outbox aynı-transaction testleri; A8 zarf/yürütme kimliği bağlaması `load_resume_payload(execution_id=...)` ile zorlanır |
| araştırma yükü altında hızlı soru | `test_worker_capacity.py::test_fast_question_completes_while_research_job_still_running` — araştırma işi research kapasitesinde kapı modeliyle çalışırken hızlı soru fast worker'da tamamlanır; araştırma işi running kalır; `test_deep_research_route_defers_job_to_research_queue` erteleme sözleşmesini sabitler |
| lease yenilemesi graph ilerlemesine bağlı (B6:387) | `test_worker_contention.py::test_progress_event_itself_triggers_lease_renewal` — arka plan döngü task'ı iptal edilerek (yenileme üretmesi imkânsız kılınarak) YALNIZ bir DomainProgress olayı yayınlanır; `lease_until` yine de ilerler → progress→heartbeat yolu ayrıca kanıtlanır (arka plan döngüsü güvenlik ağı `test_renew_loop_keeps_live_execution_recoverable_only_after_release`'te) |
| deadline/kaynak/model bütçesi sıfırlanmaz (B6:398) | Deadline: kill/restart testinde `deadline_at` aynen korunur; downtime'da dolan deadline'lı iş recovery ile yeniden yürütülmez. **Model bütçesi:** `test_worker_lifecycle.py::test_budget_reservations_survive_recovery_execution` — aynı BudgetStore örneği iki worker'a bağlanır; deneme 1'in AÇIK kalan rezervasyonu (reserved=1, release olmadan kesildi) deneme 2'de SAYALI kalır (toplam reserved=2; sıfırlanmış olsaydı 1), deneme 2 commit'i (15 token) `usage()` ile görünür |

Diğer önemli testler: migration 0003 şema/kısıt (queue_class CHECK, cancel_intents PK), `renew_lease` sahiplik, terminal-öncelik (completed commit'i intent'ten önceyse kazanır; intent önceyse `cancel_requested` reddi ve iş running kalır — terminal 'cancelled' B7'nindir), `requeue_job`/`release_job_lease`, sweep idempotensi + failed olayının aynı transaction'da outbox'a yazımı, rejected terminal yazımının outbox kaydı ÜRETMEMESİ, `needs_input` sonucunun işi beklemeye döndürmesi (terminal değildir), terminal olayın gerçek broker'da `backend.agent.events.q`'ya inmesi (`execution_attempt`, `fencing_token`, atomik `event_sequence` payload'da).

### 3.3 RAG

```
node docs/ai-agent-plan/source/tools/search.cjs verify → valid:true (30 kaynak / 60 parça / 23 aşama)
node docs/ai-agent-plan/source/tools/search.cjs search --stage B6 --query "Worker checkpoint recovery eszamanlilik iptal ve transaction" --format prompt
→ [PY-ASYNCIO#C1/#C2], [LG-PERSISTENCE#C1/#C2], [PG-ISOLATION#C1/#C2] CONTEXT olarak kullanıldı
```

Uygulamaya yansımaları: [PY-ASYNCIO#C2] iptal istisnası bastırılmaz (lease watch CancelledError'ı yükseltir, `_LeaseWatch.stop` bekler); [LG-PERSISTENCE#C2] kalıcı checkpoint deposu (A8 `FileCheckpointStore`) süreç restart'ında korunur; [PG-ISOLATION#C2] Read Committed'ta koşullu UPDATE güncel satırda değerlendirilir — fencing guard'ının dayanağı.

## 4. Tasarım kararları (bu fazın uygulama kararları)

1. **Durum makinesi genişletmesi additive:** B4 kabulü `status='accepted'` yazmaya devam eder; worker hem `accepted` hem `queued`'u claim eder (`CLAIMABLE_JOB_STATUSES`). Ortak sözleşmedeki `queued` değeri B7 test double'ları için tanımlıdır.
2. **fencing_token global monoton dizi** (`agent.job_fencing_seq`): claim başına `nextval`. Job-başına sayaç yerine global dizi, farklı worker'ların token'larının da çakışmamasını sağlar; sıfırlanmaz.
3. **Terminal yazım + terminal olay AYNI transaction:** B5'in "terminal sonuçla outbox kaydı aynı transaction'da" kuralı, fencing-guard'lı `complete_job(outbox_event=...)` ile korunur; `event_sequence` aynı transaction'da atomik tahsis edilir (B5 tablosu). Reddedilen yazım olay üretmez.
4. **Kapasite ertelemesi router sonrası:** `deep_research` kararı çekirdekten çıktığı anda (taze yolda VE checkpoint'li yolda) iş `research` sınıfına geri konur; yürütme başlamadığı için deneme sayacı resetlenir, fencing monoton kalır. Erteleme döngüsü oluşturmaz (research sınıfındaki iş tekrar ertelenmez).
5. **needs_input terminal değildir:** iş `accepted`'a döner (checkpoint korunur); B5 `needs_input` olayı outbox'a yazılır; resume talebi işi yeniden claim eder.
6. **Cancel niyeti üç yerde engel:** claim seçmez, worker yürütme başlatmaz (`aborted_cancel` + lease release), terminal yazım guard'ı reddeder. Terminal 'cancelled' geçişi B7'nin koşullu UPDATE'ine aittir (dispatch sözleşmesi).
7. **Worker broker tüketmez:** intake ACK'tan sonra işin sahibi DB'deki job kaydıdır; yürütme hatası yalnız lease-expiry recovery + deneme sınırı sweep'iyle ele alınır.

## 5. Bulgular

- **F1 (düşük, bu fazda çözüldü) — claim CTE'sinde RETURNING'in eski durumu görmemesi:** `RETURNING` yalnız güncel satırı verdiği için "bu claim recovery mi?" bilgisi ilk taslakta yanlış kolondan okunuyordu; seçim CTE'si (`picked`) durum bayrağını taşımak üzere yeniden yazıldı. Test: `test_expired_lease_recovery_claim_limited_by_attempts` (`recovered=True` iddiası).
- **F2 (düşük, bu fazda çözüldü) — yenileme döngüsü testinin yük altında kırılganlığı:** `test_renew_loop_keeps_live_execution_recoverable_only_after_release` ilk tam suite koşumunda (0.8s lease / 0.25s aralık / 1.4s sabit uyku marjlarıyla) makine yükü altında bir yenileme kaçırıp kırmızıya düştü; test gözlem gütmeli yeniden yazıldı — önce en az bir yenilemenin gerçekleşmesi beklenir (`lease_until` ilerlemesi gözlenir, 20s pencere), iddialar o gözleme dayanır; lease 2.0s / aralık 0.3s'e genişletildi. Düzeltme sonrası tam suite yeşil.
- **F3 (ortam olayı — L006/L009 deseni; tekrarlandı ve sertleştirildi):** İlk tam suite koşumu sırasında broker bağlantısı dış müdahaleyle düştü ("Server connection unexpectedly closed"): events paketinde 13 geçici fixture ERROR'ı üretti ve `blogapp-rabbitmq` konteyneri koşum sırasında restart edildi (`docker ps`: "Up 3 minutes" kanıtı; W3'teki kullanıcı paralel çalışması olayıyla aynı desen). Ayrı koşumda events + intake tamamen yeşildi. Kesin tam suite koşumu (2.) hatasız tamamlandı. **Tekrar (teslim sonrası orchestrator koşumu):** broker yine restart penceresindeyken `tests/worker` oturumu 28 setup ERROR'ı ile düştü (aio-pika "Connection.connect" görevlerinin yıkımı çıktıda kanıtlı; konteyner sonrasında "Up 4 minutes" healthy). Kod değişikliği değildi; `tests/worker/conftest.py` session fixture'ındaki topology declare retry penceresi bu geçişe tahammül için 3×5s'ten 8×5s'e genişletildi. Düzeltme sonrası gate `28 passed, 1 warning in 30.37s` (6. yeşil koşum). Broker'ın tekrar eden restart'ının kök nedeni bu fazın erişimi dışındadır (kullanıcı/B7 paralel etkinliği — orchestrator kaydı önerilir).
- **F4 (çözüldü, öncedentli) — migration smoke testinin head pini:** `tests/intake/test_migrations_smoke.py` head'i "0002"ye sabitliyordu; 0003 head'i ilerletince pin güncellendi ("0003" + `cancel_intents` tablo beklentisi). B5 de aynı dosyadaki pinı 0001→0002 geçişinde güncellemişti (dosyadaki yorum kanıtı); B6 aynı öncedenti izledi. Bu, dispatch dosya kapsamının (tests/worker/**) dışındaki TEK satır düzenlemesidir ve burada açıkça kaydedilir.
- **F5 (düşük, açık — orchestrator takibi):** A8-rapor F4'ün devamı: `.agent_checkpoints/` hâlâ repo `.gitignore`'da değil. B6 testleri worker varsayılan deposuna yazmamak için `make_worker` içinde geçici dizine yönlendirildi ve koşum kalıntıları temizlendi (`git status` temiz); yine de depo köküne `/.agent_checkpoints/` satırının eklenmesi orchestrator'a kalmıştır.
- **F6 (bilgi):** Paralel B7 agent'ının dosyaları (`control_store.py`, `control.py`, `reaper.py`, `retry.py`, `tests/control/`) aynı checkout'ta belirdi; bu fazın teslim dosyalarıyla çakışma yoktur (ayrı dosyalar). B7'nin ortak guard testleri (record_cancel_intent / mark_cancelled_if_running ile terminal-öncelik) bütünleştirme fazında gerçek broker+DB ile koşulacaktır (dispatch kuralı).

## 6. Kapsam dışı bırakılanlar ve sınırlar

- `control_store.py`, `control.py`, cancel consumer, retry/DLQ, backpressure: **B7** (paralel agent; yazılmadı).
- Gerçek retriever/web_tools bağlanmadı: `ExecutionDependencies` enjeksiyon noktaları hazır; makaleye bağlı çalışmalarda çekirdeğin geçiş davranışı (retriever'sız tek-çağrı yolu) işler — A4 F1 geçiş davranışı B8 pgvector entegrasyonuyla kapanacak. Worker testleri makalesiz payload kullanır.
- Gerçek LLM/embedding sağlayıcısı devrede değil; model test double'ları (`FakeModelProvider`, `GateModel`, `KillModel`, `is_test_double=True`) kullanıldı. Fixture/broker/DB/checkpoint davranışları gerçektir; model başarısı gerçek sağlayıcı başarısı SAYILMAZ.
- `run_forever` servis döngüsü ve üretim süreç yönetimi (systemd/container) B11 dağıtım/operasyon kapsamındadır.

## 6.1 Tam suite regresyonu

```
python -m pytest src/services/ai-agent-service/tests -q
→ 700 passed, 1 skipped, 4 warnings in 327.25s (pytest exit 0)   [32 testlik B6 sürümüyle]
→ (önceki kesin koşum, 28 testlik sürümle: 696 passed, 1 skipped, 209.65s)
```

W4 tabanı 560+1'den bu yana büyüme: A8 checkpoint 37, B8 content_sync, B6 worker 32 paketleri. İlk tam suite koşumundaki 2 kırmızı (F2 flaky + F4 head pini) ve 13 events ERROR'ı (F3 broker restart) düzeltme/ortam toparlanması sonrası kesin koşumlarda sıfırlandı.

## 6.2 Bağımsız inceleme 2. turu — kanıt boşluklarının kapatılması

İnceleyicinin ONAY VERİLMEDİ bulgusundaki iki test-evidence boşluğu kapatıldı (+1 öneri):

1. **Claim-tekillik gerçek çekişim altında:** `test_concurrent_claims_race_single_job_exactly_one_wins` ve `test_concurrent_claims_on_multiple_jobs_get_distinct_jobs` — claim_next_job çağrıları `asyncio.gather` ile aynı loop'ta EŞZAMANLI başlatılır; her çağrı kendi pool bağlantısında kendi transaction'ını açar (max_size=6). Tek işe 2 eşzamanlı claim → 1 kazanan + kaybeden None; 4 işe 4 eşzamanlı claim → 4 ayrı iş + 4 benzersiz fencing token. (İnceleyicinin haklı ayrımı: eski `test_two_workers_...` sıralı testi WHERE filtresini kanıtlıyordu; SKIP LOCKED kanıtı artık gather'lı testlerde — sıralı test `test_sequential_second_claim_gets_nothing_while_lease_active` olarak yeniden adlandıldı ve rolü belgelendi.)
2. **Bütçe sıfırlanmaması (B6:398):** `test_budget_reservations_survive_recovery_execution` — kill/restart akışında aynı FakeBudgetStore iki worker'a bağlanır; kesilen denemenin açık rezervasyonu korunur (reserved 1→2; reset senaryosunda 1 olurdu), recovery commit'i usage() ile görünür. (B6-rapor.md:23'teki 'test kanıtı §3' ifadesinin bütçe için karşılıksız olduğu bulgusu bu testle giderildi.)
3. **Öneri — progress-tetikli heartbeat ayrımı:** `test_progress_event_itself_triggers_lease_renewal` — arka plan döngü task'ı iptal edilip yalnız DomainProgress yayınlanarak ilerleme→heartbeat yolunun döngüden AYRI kanıtlanması.

Doğrulama: gate `32 passed` (38.68s ve 46.66s iki koşum) + tam suite `700 passed, 1 skipped` (327.25s).

## 7. Sonraki adım

- B7 ile bütünleştirme: ortak store sözleşmesinin terminal-öncelik testleri gerçek broker+DB ile koşulur (B6 guard'ları hazır: `complete_job` 'cancel_requested' gerekçesi + `cancel_intents` tablosu).
- B9/B10 resume/iptal UI akışları bu fazın `needs_input`/requeue davranışına dayanır.
