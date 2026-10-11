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
