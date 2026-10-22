# Blog agent mesaj sözleşmeleri (v1)

Backend (.NET) ile Python agent arasındaki RabbitMQ mesaj sözleşmesinin **tek kaynak
dizini**. Plan: `docs/ai-agent-plan/02-rabbitmq-haberlesme-plani.md` "Aşama B1" (satır
169-241); sahiplik kararları: `docs/ai-agent-plan/integration-architecture.md` (K6/K7) ve
`docs/ai-agent-plan/phase-reports/W0-ortak-mimari-kararlari.md` (§2.3, §6).

> **Konum notu:** W0 §2.3 şema konumunu `docs/ai-agent-plan/contracts/` olarak önermişti;
> integration-architecture.md:6 konumları "öneridir" diye işaretlediği ve B1 görevinin izinli
> dosya listesi `src/contracts/**` gösterdiği için sözleşmeler `src/contracts/agent/` altına
> yazıldı. Taşınırsa yalnız iki taraftaki yol sabiti değişir (.NET: `Api.Tests/Messaging/ContractPaths.cs`,
> Python: `tests/contract_paths.py`).

## Düzen

| Yol | İçerik |
| --- | --- |
| `v1/contract.json` | Sürüm, `max_payload_bytes`, üretici kimlikleri, 18 mesaj türünün yön/exchange/routing eşlemesi |
| `v1/envelope.schema.json` | Zarf şeması (13 alan; `schema_version` sabiti 1) |
| `v1/common.schema.json` | Paylaşılan `$defs`: uuid, utc_iso, hash_hex, language_code, traceparent, usage_record, source_reference, action_proposal, conversation_turn, enum kümeleri |
| `v1/payloads/<message_type>.schema.json` | Tür bazlı payload şemaları (18 dosya) |
| `fixtures/manifest.json` | Ortak doğrulama case listesi: `expect` (valid/invalid), `reason` (kategori), `schema_expect` (pass/fail/skip) |
| `fixtures/valid/` | 21 geçerli örnek; her mesaj türünün en az bir geçerli örneği var |
| `fixtures/invalid/` | 17 reddedilen örnek; her biri tek kategori tetikler |
| `fixtures/_generate.py` | Fixture setini üreten tek seferlik betik (provenance) |

## Zarf alanları ve zorunluluk

Zorunlu: `message_id`, `message_type`, `schema_version`, `correlation_id`, `occurred_at`,
`producer`, `payload`. Opsiyonel: `run_id`, `conversation_id`, `causation_id`, `deadline_at`,
`trace_context`, `delivery_attempt` (varsayılan 0). **Null taşınmaz** — opsiyonel alan
çıkarılır; iki doğrulayıcı da açık null'u `wrong_type` ile reddeder.

- Zamanlar UTC ISO 8601 (`Z` sonekli, takvim geçerli); kimlikler kanonik küçük harf tireli UUID.
- `run_id` + `conversation_id` run kapsamlı 13 tür için zorunludur; `content.*` türleri bunları taşımaz.
- `deadline_at` yalnız `agent.execute.requested` için zorunludur (B0 K6: deadline backend'de üretilir).
- `delivery_attempt`, aynı `message_id`nin transport tekrar yayınlarında artan sayacıdır;
  agent yürütme denemesi payload'taki `execution_attempt` ve `fencing_token`'dır — iki alan
  birbirinin yerine kullanılmaz (plan satır 237). Transport tekrarının fark edilmesi broker
  teslimat mekanizmasıyla (redelivered flag) desteklenir; dedup uygulama sorumluluğudur
  [RMQ-RELIABILITY#C2].
- `trace_context` W3C traceparent biçimindedir.
- `producer` ∈ `backend-net | agent-py | test-executor`; yön uyumu registry'de uygulanır
  (komut/içerik → backend-net, olaylar → agent-py; `test-executor` iki yönde de test
  executor'u için izinlidir — B0 §4 üç katmanlı işaretleme).

## Reddetme kategorileri (iki dilde aynı)

`missing_field`, `unknown_version`, `unknown_type`, `oversized` (gövde > `max_payload_bytes`,
varsayılan 256 KiB), `wrong_type`, `bad_format`, `extra_field`, `producer_mismatch`.

Doğrulama sırası: boyut → JSON çözümü → zarf kuralları → sürüm → tür kaydı → run kimliği/
deadline/üretici → payload kuralları → çapraz kurallar. Gövde **yalnız JSON** olarak
çözümlenir; pickle veya keyfi nesne deserialization yoktur (plan satır 239).

## Tüketim

- .NET: `BlogApp.Core.Application.Common.Messaging` (`AgentContractValidator`,
  `AgentMessageTypeRegistry`, DTO'lar). Şema motoru kullanmaz; registry şema dosyalarının
  yansımasıdır ve `Api.Tests/Messaging/AgentContractSchemaMirrorTests` denkliğini sabitler.
- Python: `app/messaging/contracts` (Pydantic modelleri + `parse_envelope`). Fixture'lar
  ayrıca gerçek JSON Schema dosyalarına karşı (jsonschema, Draft 2020-12) doğrulanır.

## Sürümleme

Major sürüm dizin adındadır (`v1`); envelope `schema_version` bu major sürümü taşır. Yeni
major sürüm = yeni dizin; `v1` dondurulur. Bilinmeyen sürüm `unknown_version` ile kontrollü
reddedilir.

## v2 (Who am I) — D015 genişletmesi

**Karar:** D015'in donmuş article/web `SourceReference` kapsamı, v1'e alan eklenmeden yeni bir
major sürümle genişletildi. `v1/` dosyaları değişmedi; v1 run'ları ve backlog'u v1 olarak
okunmaya devam eder. Gerekçe: v1 doğrulayıcıları katı ve tek sürümlüdür; v1'e alan eklemek
eski worker'ları ve bekleyen v1 backlog'unu kırar. Bu yüzden v2 ayrı dizin, ayrı kuyruklar ve
run bazında sürüm kaydıyla (`jobs.wire_version`) yürür.

| Yol | İçerik |
| --- | --- |
| `v2/` | v1'in run kapsamlı 13 türü; routing key `<type>.v2`; `content.*` yalnız v1'de |
| `_generate_v2.py` | v2 şemalarını v1'den türeten betik (provenance; tekrar çalıştırılabilir) |
| `fixtures/v2/` | v2 ortak fixture'ları + `manifest.json`; üretici `fixtures/_generate_v2.py` |

v2 farkları:

- `agent.execute.requested`: `conversation_topic` (`auto|who_am_i`, zorunlu) ve
  `profile_snapshot` (`{profile_id, revision, content_hash}`). `who_am_i` olduğunda
  `profile_snapshot` zorunludur; makale üçlüsü ve `selected_text` yasaktır.
- `agent.run.mode_selected`: `run_intent` ve `source_scope` zorunludur. `run_intent=profile`
  ise web kullanılmaz ve snapshot zorunludur.
- `agent.run.completed` ve `partially_completed`: `run_intent` zorunludur. `run_intent=profile`
  ise `profile_snapshot` zorunlu, kapsam `profile`, citation'lar yalnız `profile` türünde olur
  ve `action_proposal` bulunmaz.
- `source_reference.kind=profile`: `profile_id`, `profile_revision`, `profile_content_hash`,
  `section_id`, `chunk_index`, `title`, `source_id` ve `url` alanları.
- Çapraz kurallar şemayla ifade edilemez; iki doğrulayıcı da `bad_format` olarak uygular:
  - `source_id = profile:{profile_id}:{revision}:{content_hash}:{section_id}:{chunk_index}`
  - `url = /about#{section_id}`
  - citation sürümü payload `profile_snapshot` ile aynı olmalıdır.
- v1'de geçersiz-sürüm örneği olan `fixtures/invalid/unknown_schema_version.json` artık
  `schema_version=99` taşır, çünkü 2 geçerli sürümdür.

### Run sürümü ve izolasyon

Bir run'ın wire sürümü kabul anında belirlenir; o run'ın bütün mesajları (execute, cancel,
resume, action_result, accepted, mode_selected, progressed, needs_input, terminal olaylar,
deadline/reaper/attempt-exhaustion finalizer'ları) aynı sürümü taşır.

- .NET kalıcı run bağlamına `ContextSnapshotJson.wire_version` yazar. Python `agent.jobs.wire_version`
  kolonunu tutar.
- v2 komutları ayrı kuyruklara gider: `agent.execute.v2.q` ve `agent.control.v2.q`. Eski worker bu
  kuyrukları tüketmez.
- Python migration 0005 iki trigger ekler:
  - Eski worker (bağlantıda `agent.worker_wire_max` ayarı yok) v2 `jobs` satırını claim edemez
    ve güncelleyemez.
  - `outbox_events` tablosuna run sürümüyle uyuşmayan bir olay yazılamaz.

### Dağıtım bariyeri (sıra önemlidir)

1. Python servisini yükselt ve migration'ı çalıştır (`alembic upgrade head`). Yeni worker v1 ve
   v2 kuyruklarını tüketir. Bu adımdan sonra eski worker v2 işi claim edemez.
2. Backend'i yükselt. Backend v1 ve v2 olaylarını okur, ama hâlâ v1 üretir.
3. Üretici anahtarını aç: `AgentWireV2__Enabled=true`. Backend her v2 kabulünden önce iki kuyruğun
   varlığını ve en az birer tüketicisini doğrular (`IAgentWireV2Readiness`, 30 sn cache). Kuyruk ya
   da tüketici yoksa:
   - `who_am_i` isteği 503 `capability_unavailable` alır;
   - `auto` isteği v1 olarak üretilir.

### Geri dönüş / drain

1. `AgentWireV2__Enabled=false`: yeni v2 run üretilmez; `auto` v1'e döner. `who_am_i` 503 alır.
2. Başlamış v2 run'ları yeni worker'lar bitirir. Python'u geri almadan önce şunlardan birini çalıştır:
   - `python -m messaging.wire_drain --check`: aktif v2 iş sayısını raporlar; sıfır değilse
     exit 1 döner.
   - `--cancel`: kalan v2 işlerini v2 `agent.run.cancelled` olayıyla kontrollü kapatır.
3. Ancak bundan sonra eski worker'a dön. Okunamaz v2 backlog kalmaz; backend v2 olay okuyucusu
   geri dönüşte de korunur.
