# B2 Faz Raporu — Broker topology ve istemci yaşam döngüsü

- **Tarih:** 2026-10-11
- **Rol:** B2 implementasyon agent'ı (RabbitMQ broker topology ve istemci yaşam döngüsü uzmanı)
- **Base:** `feature/ai-agent-integration`, plan dosyası `docs/ai-agent-plan/02-rabbitmq-haberlesme-plani.md` "Aşama B2" (satır 243-271)
- **Ön koşullar okundu:** main-prompt.md, decisions.md (D001–D012), progress.md, lessons-learned.md (L001–L004), integration-architecture.md (K1–K8), phase-reports/B0-rapor.md, phase-reports/W0-ortak-mimari-kararlari.md (§5 Ç3), B1 sözleşmeleri (`src/contracts/agent/v1/contract.json` + `Core/Application/Common/Messaging` + `app/messaging/contracts` — dokunulmadı, yalnız tüketildi)
- **Broker:** RabbitMQ **4.2.9** (`rabbitmq:4.2-management`, Docker 29.8.2 / Compose v5.5.1) — **çalışır ve healthy durumda bırakıldı** (W3+ kullanacak)

## 1. Yapılan iş

Plan B2 bölümü satır satır uygulandı:

1. **Docker:** `docker/docker-compose.yml`'e **yalnız ekleme** ile `rabbitmq` servisi (K8: yalnız `backend-net` ağı, portlar `127.0.0.1`'e bound, kalıcı volume `rabbitmq_data`, `rabbitmq-diagnostics -q ping` healthcheck). Sabit tag `rabbitmq:4.2-management` (Docker Hub manifest ile çekilebilirliği doğrulandı). Dev kimlikler `${VAR:-varsayılan}` düz metin — dispatch izniyle `.env` dokunulmadı.
2. **Geliştirme/üretim ayrımı:** vhost ile (`blogapp_dev`); servis kullanıcıları publish/consume yetki regex'leriyle ayrıldı (§3). Exchange/kuyruk adları donmuş B1 sözleşmesinden/plan topolojisinden gelir, yapılandırmaya bağlı değildir.
3. **.NET `BuildingBlocks.Messaging` (D012 konumu, RabbitMQ.Client 7.x ile temiz yeniden yazım — eski 3dbdef8 kodu kopyalanmadı):** bağlantı ömrü yöneticisi, idempotent topology initializer (tek declarer, K3), confirm'lu + mandatory publisher, consumer tabanı, DI kaydı.
4. **Python `app/messaging` (contracts hariç):** robust bağlantı (aio-pika 9.5.8), pasif topology doğrulama (fail-fast), registry-tabanlı confirm'lu publisher, robust consumer.
5. **Testler:** `src/backend/Presentation/Api.Tests/Messaging/Broker/` (12 xunit testi) + `src/services/ai-agent-service/tests/messaging_broker/` (17 pytest testi, kendi conftest'i — kök tests/conftest'e dokunulmadı).

## 2. Topology (kurulan)

| Varlık | Ad | Argümanlar |
| --- | --- | --- |
| Exchange (topic, durable) | `blog.agent.commands`, `blog.agent.events`, `blog.content.events`, DLX `blog.agent.dead` | — |
| Ana kuyruk (durable) | `agent.execute.q`, `agent.control.q`, `agent.content.q`, `backend.agent.events.q` | `x-dead-letter-exchange=blog.agent.dead` (rk korunur, hedef DLQ'ya düşer) |
| DLQ (durable) | `<ana>.dlq` (ör. `agent.execute.q.dlq`) | ana kuyrukla aynı rk'lar `blog.agent.dead`'e bound |
| Retry (hedefe özel) | `blog.agent.retry.{10s,30s,120s}` exchange + `<ana>.retry.{tier}s.q` | `x-message-ttl=tier*1000` + `x-dead-letter-exchange=<orijinal exchange>` (TTL sonrası aynı rk ile geri) |

- Binding'ler B1 yön/routing tablosundan; **sapma gerekçesi:** `content.project.changed.v1` binding'i eklandı — plan diyagramında (satır 48-49) yok ama B1 registry'sinde tanımlı tür routable olmalı (L003: plan metni asıl; B1 tablosu satır 233 açıkça bu anahtarı tanımlar).
- Retry kademeleri 10s/30s/2dk **B7'nin değerlendirme önerisidir** (plan satır 414 "değerlendir"); ayarlanabilir (`RabbitMqSettings.RetryTierSeconds` / `build_topology(retry_tier_seconds=...)`). Yayın politikası (ne zaman retry) B7'dir; B2 yalnız routing'i kurar ve gerçek TTL→orijinal-exchange dönüşünü broker'da doğrular.
- **Kuyruk türü:** dev'de durable classic; quorum plan satır 60 + [RMQ-QUORUM#C1] uyarınca (tek düğüm HA sağlamaz) B11 prod değerlendirmesine bırakıldı.
- **Diller arası tutarlılık:** retry ad formülü `.NET` ile Python'da başta farklıydı (`agent.execute.q.retry.10s.q` vs `agent.execute.retry.10s.q` — brokerda iki aile belirdi); Python .NET formülüne (`<ana>.retry.{tier}s.q`) çevrildi, bayat kuyruklar silindi. Artık iki taraf aynı argümanlarla idempotent declare ediyor; iki test paketi aynı broker üstünde çift yönlü koşuldu (PRECONDITION_FAILED yok).

## 3. Kimlik/yetki modeli (yapılandırma düzeyinde, dev düz metin — sıra log/kod/commit'e girmedi)

vhost `blogapp_dev`; kullanıcılar RabbitMQ management API ile idempotent provizyon edilir (komutlar `tests/messaging_broker/conftest.py::provision_vhost_and_users` içinde kanıtlı ve otomatik):

| Kullanıcı | configure | write (publish) | read (consume) |
| --- | --- | --- | --- |
| `blogapp` (admin, compose env) | `.*` | `.*` | `.*` |
| `backend_svc` (uygulama kimliği) | — (declarer değil) | `blog\.(agent\.commands\|content\.events)` | `backend\.agent\.events\.q(\.dlq)?` |
| `agent_svc` | — (pasif doğrular) | `blog\.agent\.events` | `agent\.(execute\|control\|content)\.q(\.dlq)?` |
| `agent_restricted` | — | — | — (vhost'a bile bağlanamaz) |
| *declarer kimliği* (operasyonel) | `.*` | topoloji kaynakları | topoloji kaynakları |

**Ölçülmüş RabbitMQ 4.2 kuralı (büyük bulgu — F1):** DLX'li kuyruğun **yaratımı** declarer'dan o kuyruk kaynağına **read** ve DLX exchange'ine **write** izni ister (mevcut eşdeğer kuyruğun tekrar declare'i denetimi atlar). Ayrıca pasif declare "hedefte en az bir izin" ister (resmî access-control kuralı). Bu yüzden declarer, uygulama servis kimliğinden ayrı operasyonel bir kimliktir (`RabbitMqSettings.DeclarerUserName/Password`; dev testlerinde admin) ve **uygulama mesajı yayınlamak için kullanılmaz** — "backend events'e yayın yapamaz" engeli `backend_svc` için geçerli kalır (test kanıtlı).

## 4. Yazılan dosyalar (izin kapsamı içinde)

| Dosya | İçerik |
| --- | --- |
| `docker/docker-compose.yml` | `rabbitmq` servisi + `rabbitmq_data` volume (yalnız ekleme) |
| `src/backend/BuildingBlocks/BuildingBlocks/Messaging/RabbitMqSettings.cs` | bağlantı/tüketim ayarları + declarer kimliği + `MaxPublishBytes=262144` |
| `…/Messaging/AgentMessagingTopology.cs` | topology planı (exchange/queue/binding, DLX+retry argümanları) |
| `…/Messaging/RabbitMqConnectionManager.cs` | tek uzun ömürlü `IConnection` sahibi; `AutomaticRecoveryEnabled` + heartbeat + `ClientProvidedName` |
| `…/Messaging/AgentTopologyInitializer.cs` | idempotent declare, declarer kimliğiyle, `IAsyncDisposable` |
| `…/Messaging/RabbitMqAgentPublisher.cs` | confirm'lu + mandatory publisher; `CreateChannelOptions(publisherConfirmations+Tracking)`; `BasicReturnAsync` kaydı; gövde üst sınırı; kanal erişimi `SemaphoreSlim` ile serileştirilir |
| `…/Messaging/RabbitMqAgentConsumer.cs` | consumer tabanı: `BasicQosAsync` sınırlı prefetch, manuel ACK işleme sonrası, handler hatasında `BasicNackAsync(requeue:false)` → DLX, gövde `Body.ToArray()` ile callback içinde kopyalanır ([RMQ-DOTNET#C2]) |
| `…/Messaging/RabbitMqMessagingDependencyInjection.cs` | `AddRabbitMqAgentMessaging` (settings + connection manager + initializer) |
| `src/backend/BuildingBlocks/BuildingBlocks/BuildingBlocks.csproj` | **yalnız ek:** `RabbitMQ.Client 7.2.2` (NuGet araması: latest 7.x; D012) |
| `src/backend/Presentation/Api.Tests/Messaging/Broker/` | `BrokerTestEnvironment.cs`, `AgentRabbitMqBrokerTests.cs` (8 gerçek-broker testi), `AgentMessagingBrokerContractMirrorTests.cs` (4 ayna testi) |
| `src/services/ai-agent-service/app/messaging/` | `settings.py`, `topology.py`, `connection.py`, `publisher.py`, `consumer.py`, `errors.py`, `__init__.py` (exports; docstring satırı korunarak genişletildi) |
| `src/services/ai-agent-service/tests/messaging_broker/` | `__init__.py`, `conftest.py` (provizyon + purge + sağlık), `test_topology.py`, `test_publish.py`, `test_auth.py`, `test_consumer.py` |
| `docs/ai-agent-plan/phase-reports/B2-rapor.md` | bu dosya |

Dokunulmayanlar: `src/contracts/**`, `src/backend/Core/**` (diff boş — `git diff --stat` kanıtı), `app/messaging/contracts/`, kök `tests/`, diğer agent'ların W2 paralel çalışma alanları (`app/agent_core/budget|content|graph|state`, `pyproject.toml` değişikliği A2/A3'e ait — hiçbirine müdahale edilmedi).

## 5. Çalıştırılan kontroller (gerçek çıktılar)

| Kontrol | Komut | Sonuç |
| --- | --- | --- |
| B2 RAG CONTEXT | `node docs/ai-agent-plan/source/tools/search.cjs search --stage B2 --query "RabbitMQ durable queue publisher confirms channel ve quorum" --format prompt` | 6 parça: RMQ-DOTNET#C1/C2, RMQ-RELIABILITY#C2, RMQ-DLX#C2, RMQ-QUORUM#C1, RMQ-CONFIRMS#C1, AIO-PIKA#C2; ikinci sorgu +AIO-PIKA#C1, RMQ-CONFIRMS#C2, RMQ-DLX#C1 |
| aio-pika API zemin doğrulaması | `python` + `inspect.signature` (kurulu paketten) | aio_pika **9.5.8**: `connect_robust(url, heartbeat, timeout, client_properties, reconnect_interval)`, `channel(publisher_confirms=True, on_return_raises=False)`, `Exchange.publish(mandatory=True)→Ack/Nack`, `declare_queue(passive=)`; RobustChannel `_on_open` qos'u geri yükler; `RobustQueue.restore` consumer'ı yeniden kaydeder (kaynak okundu) |
| RabbitMQ.Client sürümü | `dotnet package search RabbitMQ.Client` | latest **7.2.2** (7.x major, D012 uyumlu) |
| Broker imajı | `docker manifest inspect rabbitmq:4.2-management` | OK → `rabbitmq:4.2-management` (çalışan sürüm `rabbitmqctl version` → **4.2.9**) |
| **GATE 1** | `python -m pytest src/services/ai-agent-service/tests/messaging_broker -q` | **17 passed** (64 s) |
| **GATE 2** | `dotnet test src/backend/Presentation/Api.Tests --nologo -v q` | **72 passed** (B1'in 60'ı + B2'nin 12 broker testi; 33 s) |
| Derleme | `dotnet build` (BuildingBlocks, Api.Tests) | 0 hata 0 uyarı (NU1902/NU1903 ImageSharp/AngleSharp uyarıları B2 öncesi mevcut — yeni bağımlılıktan değil) |
| Broker sağlık | `docker inspect -f {{.State.Health.Status}} blogapp-rabbitmq` | `healthy`; compose: `rabbitmq:4.2-management Up (healthy)` — **çalışır bırakıldı** |

### Kabul ölçütleri → gerçek-broker kanıtları

| Ölçüt (plan satır 271) | Kanıt test |
| --- | --- |
| Topology tekrarlı kurulumda bozulmaz | `test_topology_declare_is_idempotent` (2× declare + pasif doğrulama), `TopologyInitializer_DeclaresIdempotently` (2× initialize; **Python'un declare ettiği kuyruğa .NET pasif doğrulama** — diller arası) + `test_mismatched_queue_arguments_are_rejected` / `TopologyInitializer_ArgumentMismatch…` (farklı argüman → PRECONDITION_FAILED, topoloji bozulmaz) |
| Bağlanmamış routing key fark edilir | `test_mandatory_unroutable_routing_key_is_reported` (aio-pika `DeliveryError` → `returned=True, confirmed=False`), `Publisher_MandatoryUnroutableRoutingKey_IsReportedNotConfirmed` (RabbitMQ.Client 7.x tracked-confirm + mandatory → `PublishReturnException` → `Returned=true`) |
| Yeniden bağlantı sonrası consumer çalışır | **Python, gerçek kesinti:** `test_consumer_recovers_after_broker_restart` — tüketim başladıktan sonra `docker restart blogapp-rabbitmq` (gerçek broker kesintisi), kesinti SONRASI taze bağlantıyla yayın → robust consumer yeniden bağlanıp mesajı işledi. **.NET:** `Consumer_RecoversAfterBrokerForcedConnectionClosure` — `rabbitmqctl close_all_connections "broker-interruption-test"` ile zorla kopma → `AutomaticRecoveryEnabled` yeniden bağlandı, mesaj işlendi |
| Yetkisiz servis yayın yapamaz | `test_restricted_service_cannot_even_connect_to_vhost` (izinsiz kullanıcı Connection.Close), `test_backend_service_cannot_publish_to_events_exchange` (ACCESS_REFUSED, broker log'unda doğrulandı), `test_agent_service_cannot_consume_backend_events_queue`, `test_agent_service_cannot_actively_declare` (K3 pasif doğrulama) |

Diğer anlamlı testler: publisher confirm + persistent + AMQP zarf tutarlılığı (message_id/correlation_id/type/content_type, `delivery_mode=2`, gövde round-trip B1 zarf modeliyle) iki dilde; prefetch=2 ile eşzamanlılık sınırı (5 mesaj, `max_in_flight ≤ 2`) iki dilde; handler hatası → hedef DLQ, rk korunur, tek işleme (`attempts==1`, requeue döngüsü yok) iki dilde; retry kuyruğu TTL sonrası orijinal exchange'e aynı rk ile döner (1 sn'lik test kademesiyle gerçek broker'da ölçüldü); payload üst sınırı yayından önce reddedilir iki dilde; ayna testleri (exchange adları = B1 registry, `MaxPublishBytes` = `MaxPayloadBytes` = contract.json 262144, her B1 routing key'inin binding karşılığı AMQP topic eşleşmesiyle — `content.sync.#` `content.sync.batch.v1`'i kapsar).

## 6. Bulgular

### F1 — RabbitMQ 4.2 izin modeli beklentiden sıkı (bilgi, severity: info → mimari karar doğurdu)
Ölçümler: (a) pasif declare, hedefte **en az bir izin** ister (resmî access-control kuralı; agent_svc commands/content exchange'lerini pasif bile göremez) → Python topology doğrulaması rol kapsamlı yapıldı (`verify_topology(exchanges=…, queues=…)`), publisher exchange kümesi rolle verilir; (b) DLX'li kuyruk **yaratımı** declarer'dan o kuyruğa **read** + DLX exchange'ine **write** ister → declarer kimliği uygulama kimliğinden ayrıldı (§3). Düzeltme doğrulandı: declarer=admin ile initializer yeşil; `backend_svc` events'e hâlâ ACCESS_REFUSED.

### F2 — Çift declarer riski diller arası ad uyuşmazlığı üretti (düzeltildi, severity: medium)
Python `_target_retry_names` ile .NET `RetryQueueFor` farklı formüldü; brokerda iki retry kuyruğu ailesi birikti. Kanıt: management `/api/queues/blogapp_dev` listesi (her iki ad ailesi). Düzeltme: tek formül `<ana>.retry.{tier}s.q`, bayat kuyruklar silindi; her iki paket aynı broker üstünde çift yönlü yeşil. **Önlem:** topology adları yalnız bu iki modülde tanımlı; değişiklik çift taraflı ayna testleriyle yakalanır.

### F3 — Test yalıtımı: management `/purge` uç noktası 405 (düzeltildi, severity: low)
RabbitMQ 4.2 management'ında `DELETE /queues/{vh}/{name}/purge` **405** döndürür (ölçüldü); kuyruk boşaltma `/contents` ile yapılır. İlk pytest koşusunda hatayı sessizce yutan `mgmt_try` kalıntı mesaj bıraktı ve sonraki testi bozdu (assert'ler kalıntıyı yakaladı — testler işini yaptı). Düzeltme: `purge_queues` `/contents` kullanır ve statü denetimi yapar.

### F4 — `.gitignore` yeni B2 testlerini de kapsıyor (işlem notu, orchestrator'a)
`.gitignore:27 tests/` kuralı `src/services/ai-agent-service/tests/messaging_broker/` için de geçerli (`git check-ignore -v` kanıtı) — A1/B1 testlerindeki gibi **`git add -f` gerekir** (L001 deseni). Commit orchestrator'dadır; bu ask'ta commit yasak.

### F5 — L002 tekrarı: paralel agent `nul` çöp dosyası bıraktı (düzeltildi, severity: low)
Oturum içinde repo kökünde 102 baytlık untracked `nul` belirdi (içerik: `dir: cannot access '/s'...` — `dir /s /b > nul` kalıntısı; oluşturulma 22:13, bu agent'ın komut geçmişinde yok). L002'deki belgelenmiş düzeltme uygulanarak silindi; dispatch prompt'larına L002 notunun taşınması gereği yeniden doğrulandı.

## 7. Sınırlamalar ve çalıştırılmamış kontroller

- Retry **yayın politikası** (hangi hatada kaç deneme, DLQ replay) B7 kapsamındadır; B2 yalnız topology + TTL dönüşünü kanıtlar. Kademeler B7'de değişirse kuyruk argümanı değişimi dev'de sil-bir-oluştur gerektirir (PRECONDITION_FAILED koruması).
- Quorum queue, prod TLS, çok düğümlü kurulum B11'e bırakıldı (plan satır 60, [RMQ-QUORUM#C1] tek düğüm HA sağlamaz).
- Producer'dan kuyruğa mesaj **boyut/çerçeve limiti** broker belgesi (K7 açık kalemi): arşiv CONTEXT'inde yok; bu fazda sözleşme üst sınırı (256 KiB) istemci iki ucunda zorlandı ve test edildi. Broker `max_message_size` varsayılan değerine dair iddia RAG kuralı gereği yazılmadı.
- B3 outbox publisher ve B4 intake consumer, bu modülleri **kullanacak**; B2'de uçtan uca iş kabulü senaryosu (HTTP→outbox→consumer) bilinçli olarak kapsam dışı.
- Proxy/policy (`max-length`, `queue-mode`) tanımlanmadı; yalnız declare argümanları kullanıldı.

## 8. Dev broker çalıştırma/recovery rehberi (kısa)

```bash
docker compose -f docker/docker-compose.yml up -d rabbitmq   # başlat (healthcheck: rabbitmq-diagnostics -q ping)
docker restart blogapp-rabbitmq                              # gerçek kesinti testi (durable topology volume'de kalır)
docker exec blogapp-rabbitmq rabbitmqctl close_all_connections "sebep"   # bağlantı-zorla-kopma testi
# kullanıcı/vhost provizyonu ve purge: tests/messaging_broker/conftest.py (management API, idempotent)
```

## 9. Kaynak kimlikleri

Bu fazda teknik iddialar için kullanılan arşiv parçaları: [RMQ-DOTNET#C1] (uzun ömürlü bağlantı/kanal), [RMQ-DOTNET#C2] (ReadOnlyMemory gövde callback içinde kopyalanır), [RMQ-CONFIRMS#C1] (confirm ↔ ACK bağımsızlığı), [RMQ-CONFIRMS#C2] (delivery tag kanal kapsamlı, manuel ACK + sınırlı prefetch), [RMQ-RELIABILITY#C2] (durable kuyruk + persistent mesaj + mandatory), [RMQ-DLX#C1/#C2] (DLX davranışı; at-least-once iç confirms), [RMQ-QUORUM#C1] (tek düğüm HA sağlamaz), [AIO-PIKA#C1/#C2] (robust bağlantı, publisher confirms). Arşiv dışı ek doğrulama: RabbitMQ resmî access-control sayfası (pasif declare izin kuralı; bu oturumda WebFetch ile alındı) ve **kurulu broker 4.2.9 üzerindeki gerçek davranış ölçümleri** (§3, F1) — API imzaları kurulu aio-pika 9.5.8 kaynak kodundan ve RabbitMQ.Client 7.2.2 derlemesinden okundu; hiçbir API imzası hafızadan yazılmadı (derleyici + çalışma zamanı doğruladı).

## 10. Sonraki adım

B3 (backend iş kabulü + transactional outbox publisher): `RabbitMqAgentPublisher` + `AgentMessagingTopology` sabitlerini kullanır; declarer kimliği appsettings'te tanımlanmalı (`RabbitMq:DeclarerUserName`), `backend_svc` runtime kimliği olarak kalır.
