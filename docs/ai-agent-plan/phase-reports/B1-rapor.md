# B1 Faz Raporu — Mesaj sözleşmelerini ve sürümlemeyi oluştur

- **Faz:** B1 (sürümlenmiş mesaj sözleşmeleri: zarf, 18 mesaj türü, yön/routing eşlemeleri, kategorize doğrulama)
- **Tarih:** 2026-10-11
- **Branch / temel:** `feature/ai-agent-integration`, HEAD `8f148ab` (= `origin/main`)
- **Rol:** B1 implementasyon agent'ı
- **Ön koşul girdileri:** `docs/ai-agent-plan/02-rabbitmq-haberlesme-plani.md` "Aşama B1" (satır 169-241), `docs/ai-agent-plan/phase-reports/B0-rapor.md`, `docs/ai-agent-plan/integration-architecture.md` (K6/K7, §4), `docs/ai-agent-plan/phase-reports/W0-ortak-mimari-kararlari.md` (§1, §2.3, §6), A1 iş modelleri (`src/services/ai-agent-service/app/agent_core/`)
- **Kapsam dışı bırakılanlar:** broker topology/istemci yaşam döngüsü (B2), outbox publisher (B3), intake consumer (B4), agent iş modellerinin değiştirilmesi, `progress.md`/`decisions.md`. Hiçbir commit/push yapılmadı; mevcut davranış değiştirilmedi (tek mevcut dosya değişimi: `pyproject.toml` paket listesine `messaging*` eklendi — izinli ağaç içinde).
- **Çıktı özeti:** 61 dosyalık ortak sözleşme dizini (`src/contracts/agent/`), .NET sözleşme modülü (9 üretim + 4 test dosyası), Python transport modülü (10 modül + 3 test dosyası). İki dil **aynı fixture setini** okuyup aynı beklentileri üretir.

## 1. Yapılan iş

Planın B1 bölümü satır satır uygulandı: envelope alan tablosu (satır 183-196), mesaj türleri
(satır 202-217, **18 tür** — W0 §6.1'in "17" sayımı ContentSnapshot çiftini tek saymış; plan
listesi 18 tür içerir, 18 uygulandı), yön/routing eşlemeleri (satır 219-233) ve kurallar
(satır 235-239): monoton `event_sequence`, transport tekrarı ile `execution_attempt`/
`fencing_token` ayrımı, UTC ISO 8601, AMQP header tutarlılığı, backend tarafından eklenen
kullanıcı/oturum referansının yetki kanıtı olmaması ve JSON-only çözümleme.

## 2. Sözleşme kararları

| # | Karar | Gerekçe (kanıt) |
| --- | --- | --- |
| K1 | **Tek sözleşme kaynağı `src/contracts/agent/v1/`.** W0 §2.3 `docs/ai-agent-plan/contracts/` önermişti; integration-architecture.md:6 konumları "öneridir" diye işaretlediği ve B1 görevinin izinli dosya listesi `src/contracts/**` gösterdiği için bu konuma yazıldı. Taşınırsa yalnız iki yol sabiti değişir (`Api.Tests/Messaging/ContractPaths.cs`, `tests/contract_paths.py`) | Görev izin listesi + integration-architecture.md:5-6; `src/contracts/agent/README.md` konum notu |
| K2 | **Sürümleme:** major sürüm dizin adında (`v1`), `schema_version: 1`; bilinmeyen sürüm `unknown_version` ile kontrollü reddedilir; yeni sürüm = yeni dizin, eski şema dondurulur | W0 §6.2; plan satır 188, 241 |
| K3 | **Envelope:** 12 plan alanı + **`delivery_attempt` uzantısı** (int ≥0, varsayılan 0). Transport tekrar yayını sayacı zarfta, agent yürütme denemesi (`execution_attempt` ≥1) ve lease fencing (`fencing_token`) payload'tadır — "ayrı alanlar" kuralının doğrudan uygulaması (plan satır 237). Redelivery normal karşılanır; dedup uygulama sorumluluğudur [RMQ-RELIABILITY#C2] | Plan satır 183-196, 237; W0 Ç6/K6 |
| K4 | **Zorunluluk kümesi:** zorunlu 7 alan (message_id, message_type, schema_version, correlation_id, occurred_at, producer, payload); run kapsamlı 13 türde `run_id`+`conversation_id` zorunlu, `content.*` 5 türde yasak; `deadline_at` yalnız `agent.execute.requested` için zorunlu (B0 K6: deadline backend'de üretilir). **Null taşınmaz** — opsiyonel alan çıkarılır; açık null iki tarafta `wrong_type` | Plan satır 183-198; B0 K6/K7; `envelope.schema.json` |
| K5 | **Biçimler:** kanonik küçük harf tireli UUID; UTC ISO 8601 `Z` sonekli **ve takvim geçerli** (`2026-13-99` reddedilir); SHA-256 hex; dil kodu; W3C traceparent | Plan satır 239; `v1/common.schema.json` |
| K6 | **18 mesaj türü + routing:** `routing_key = message_type + ".v1"`; exchange'ler plan tablosundan (`blog.agent.commands/events`, `blog.content.events`); yön registry'de kodlanmış ve `contract.json` ile ayna testiyle eşlenmiş. `test-executor` iki yönde de izinli (B0 §4); `backend-net` yalnız komut/içerik, `agent-py` yalnız olay üretir → `producer_mismatch` | Plan satır 202-233; B0 §4; `AgentMessageTypeRegistry.cs` ↔ `contracts/registry.py` |
| K7 | **Payload eşlemesi A1 modellerine:** EC alanları → `AgentExecutionRequestedV1` (içerik gömülmez: `article_id/revision/hash` referansı + `context_snapshot_reference` + `budget_profile` adı — K7); AO → 5 terminal olay; DomainProgress → `AgentRunProgressedV1` (+`event_sequence`, W0 Ç6); ActionProposal/ValidatedActionResult → `AgentActionProposedV1`/`AgentActionResultV1`. Eşlenebilirlik pytest ile kanıtlı (alan kümesi + enum denkliği testleri) | Plan satır 235; W0 §1 tablo; `tests/test_messaging_contracts_rules.py` |
| K8 | **Kategorize reddetme:** `missing_field, unknown_version, unknown_type, oversized, wrong_type, bad_format, extra_field, producer_mismatch`. Doğrulama sırası iki dilde aynı: boyut → JSON → zarf → sürüm → tür → run kimliği/deadline/üretici → payload → çapraz kurallar. `oversized` her şeyden önce uygulanır (publisher ve consumer iki uçta) | Plan kabul ölçütü satır 241; B0 K7 (`MaxPayloadBytes` 256 KiB başlangıç) |
| K9 | **Çapraz kurallar:** makale referans üçlüsü hep-ya-da-hiç; `accepted` → `applied_article_revision` zorunlu; `requires_web_search` yalnız `deep_research`; answer/report tam-ikisi-değil-biri; `usage.run_id`/`proposal.run_id` = zarf `run_id`; `updated` → `content_hash` zorunlu, `unpublished` → yasak; `batch_index < total_batches`. Kategoriler .NET/Python arasında birebir (ör. accepted-revision → iki tarafta `missing_field`) | A1 model doğrulamalarının taşıma yansıması; `AgentContractValidator.ValidateCrossRules` ↔ `validator.py` |
| K10 | **user_ref yetki kanıtı değildir:** payload'da opak string; değeri değiştirmek sözleşme geçerliliğini etkilemez (test kanıtı). Yetkilendirme backend run sahipliğinde ayrı karardır | Plan satır 198; `test_user_ref_is_carried_opaquely`, `AgentMessagingRuleTests` belgeleme |
| K11 | **JSON-only:** gövde yalnız JSON metni/baytı olarak çözümlenir; `parse_envelope` nesne girdiyi `TypeError` ile reddeder; paket kaynaklarında pickle kullanım yoklaması testi var | Plan satır 239 |
| K12 | **AMQP tutarlılığı:** `AgentAmqpProperties.FromEnvelope` / `to_amqp_properties` → `message_id`, `correlation_id`, `content_type: application/json`, `type = message_type`; iki dilde test edildi | Plan satır 233 |
| K13 | **JSON Schema dosyaları gerçek doğrulamada kullanılır (Python):** fixture'lar jsonschema 4.23.0 Draft 2020-12 ile şemalara karşı da doğrulanır (manifest `schema_expect`). .NET tarafı şema motoru **kullanmaz** (mevcut csproj'lara bağımlılık eklenemez); registry şemaların yansımasıdır ve `AgentContractSchemaMirrorTests` required/enum/additionalProperties/routing denkliğini sabitler | [JSON-SCHEMA#C1], [JSON-SCHEMA#C2]; görev izin listesi |

## 3. Yazılan dosyalar

### Ortak sözleşme (tek kaynak) — `src/contracts/agent/` (61 dosya)

- `README.md` — sözleşme kararlarının özeti (yukarıdaki tablonun tüketiciye dönük hali)
- `v1/contract.json`, `v1/envelope.schema.json`, `v1/common.schema.json`
- `v1/payloads/*.schema.json` — 18 payload şeması
- `fixtures/manifest.json`, `fixtures/valid/` (21), `fixtures/invalid/` (17), `fixtures/_generate.py` (üretici betik, provenance)

Kategoriler fixture'larla karşılanır: eksik alan (4 fixture), bilinmeyen sürüm, bilinmeyen tür,
aşırı boyut (300 KB soru), hatalı tür (4), biçim (3), fazladan alan (2), üretici-yön uyuşmazlığı.

### .NET — `src/backend/Core/Application/Common/Messaging/` (8 dosya) + Options (1)

- `AgentContractError.cs` (kategori enum + kayıt), `AgentContractFormats.cs` (UUID/UTC/hash/dil/traceparent; GeneratedRegex + takvim çözümlemesi)
- `AgentFieldRule.cs` (kural DSL), `AgentMessageTypeRegistry.cs` (18 tür: yön/exchange/routing/üretici/payload kuralları/DTO tipi)
- `AgentEnvelope.cs`, `AgentRunMessagePayloads.cs` + `AgentContentMessagePayloads.cs` + `AgentPayloadValueObjects.cs` (18 DTO, `required` üyeler, `[JsonExtensionData]` ile bilinmeyen alan yakalama)
- `AgentContractValidator.cs` (kategorize pipeline + `TryValidateAs<TPayload>`), `AgentAmqpProperties.cs`, `AgentEventSequenceGuard.cs` (monoton sequence koruması)
- `Common/Options/AgentMessagingSettings.cs` (`AgentMessaging:SchemaVersion/MaxPayloadBytes/ProducerName`; **DI kaydı yapılmadı** — mevcut `DependencyInjection.cs` bu fazın izin listesinde değil; B2/B3 kaydedecek)

### .NET testleri — `src/backend/Presentation/Api.Tests/Messaging/` (4 dosya)

`ContractPaths.cs`, `AgentContractFixtureTests.cs` (38 fixture + kapsam testleri + typed doğrulama + boyut kapısı), `AgentContractSchemaMirrorTests.cs` (şema↔registry denkleşmesi: zarf, 18 payload, contract.json routing), `AgentMessagingRuleTests.cs` (çapraz kurallar, AMQP tutarlılığı, sequence guard, delivery/execution ayrımı).

### Python — `src/services/ai-agent-service/`

- `app/messaging/contracts/` (10 modül): `enums.py`, `errors.py`, `formats.py` (Strict tipler + takvim geçerli UTC), `payloads.py` (18 model + ortak değer nesneleri, `extra="forbid"`, null reddi), `envelope.py`, `registry.py`, `validator.py` (`parse_envelope`), `amqp.py`, `sequence.py` (`EventSequenceTracker`), `__init__.py`
- `tests/test_messaging_contracts_fixtures.py`, `tests/test_messaging_contracts_rules.py`, `tests/contract_paths.py`
- `pyproject.toml`: paket listesine `messaging*` eklendi (mevcut satırlar değiştirilmedi)

İthalat yönü kuralı korundu: `messaging` → `agent_core` bağımlılığı **yok** (transport kendi
StrEnum ve değer modellerini tanımlar; denklik testlerle sabitlenir — W0 Ç2'nin tersi yön yasağı aynen geçerli).

## 4. Çalıştırılan kontroller (gerçek çıktılarla)

| Kontrol | Komut | Sonuç |
| --- | --- | --- |
| Kaynak arşivi | `node docs/ai-agent-plan/source/tools/search.cjs verify` | `"valid": true, "sources": 30, "chunks": 60, "stages": 23` |
| B1 teknik CONTEXT | `node docs/ai-agent-plan/source/tools/search.cjs search --stage B1 --query "JSON Schema required properties ve mesaj DTO doğrulama" --format prompt` | 5 parça: [JSON-SCHEMA#C1/#C2], [PYDANTIC-MODELS#C1/#C2], [RMQ-RELIABILITY#C2] |
| Fixture ↔ şema tutarlılığı (geliştirme sırası denetimi) | `python src/contracts/agent/fixtures/_generate.py` + şema çapraz kontrol | `valid: 21 invalid: 17 total cases: 38` / `OK: all 38 fixture schema expectations met` (denetim scripti kalıcı testlere geçtikten sonra silindi) |
| **Python test paketi** | `python -m pytest src/services/ai-agent-service/tests -q` | `171 passed, 1 skipped in 1.10s` (1 skip = `malformed_json` şema kontrolünün bilinçli atlanması; A1'in 74+ testi dahil geriye dönük yeşil) |
| Pyflakes | `python -m pyflakes src/services/ai-agent-service/app src/services/ai-agent-service/tests` | temiz (çıktı yok) |
| **.NET test paketi** | `dotnet test src/backend/Presentation/Api.Tests --nologo -v q` | `Başarılı! - Başarısız: 0, Başarılı: 60, Atlanan: 0, Toplam: 60, Süre: 278 ms` (38 fixture + 20 kural/ayna/davranış testi + mevcut SeoDocumentsTests) |
| Dosya sahipliği | `git status --short` | Yalnız izinli yeni yollar + `pyproject.toml`; `.video_agent/`, `.zcode/`, `.zcodeignore` dokunulmadı |

Geliştirme sırasında yakalanıp düzeltilen gerçek hatalar: şemada `usage` eksikliği ve fixture'ta
eksik `source_scope` (jsonschema denetimi), `missing_envelope_field` fixture'ının null yazması
(anahtar çıkarılacak şekilde düzeltildi), `JsonNode.TryGetValue` ve payload `JsonElement`
üretim hataları, xunit 2.9 `TheoryData` uyumu, `additionalProperties:false` ayna karşılaştırması,
`required` dizisi olmayan `agent.cancel.requested` şeması ve `$ref` ile tanımlı enum'ların ayna
çözümlemesi. Hepsi yukarıdaki nihai koşularda yeşil.

## 5. Kabul ölçütleri eşlemesi (plan satır 241)

| Ölçüt | Durum | Kanıt |
| --- | --- | --- |
| İki dil aynı fixture'ları okuyabilir | **Karşılandı** | Aynı `manifest.json`; Python `test_fixture_matches_validator_expectation` (38 case) ve .NET `Fixture_Matches_Expectation` (38 theory case) aynı dosyaları aynı beklentilerle geçti; ayrıca her iki dilde aynı kategori üretimi (ör. `missing_envelope_field` → `missing_field`, her iki paket çıktısında) |
| Eksik alan kontrollü reddedilir | **Karşılandı** | `missing_required_field`, `missing_envelope_field`, `missing_run_identity`, `missing_deadline_for_execute` → `missing_field` (iki dil) |
| Bilinmeyen sürüm kontrollü reddedilir | **Karşılandı** | `unknown_schema_version` → `unknown_version` (iki dil) |
| Aşırı boyut kontrollü reddedilir | **Karşılandı** | `oversized_payload` (300 KB) → `oversized`; sınır `AgentMessaging:MaxPayloadBytes`/`MAX_PAYLOAD_BYTES` = 262144; ayarlanabilir sınır testi: .NET `Size_Gate_Applies_Configured_Limit_Before_Parsing`, Python `test_size_gate_uses_configured_limit_before_parsing` |
| Hatalı tür kontrollü reddedilir | **Karşılandı** | `payload_not_object`, `wrong_field_type`, `bad_enum_value`, `answer_and_report` → `wrong_type`; `unknown_message_type` → `unknown_type`; `producer_direction_mismatch` → `producer_mismatch` (iki dil) |

## 6. Kullanılan kaynak kimlikleri (yalnız bu oturumda gelen CONTEXT parçaları)

- [JSON-SCHEMA#C1] — properties/required/additionalProperties anlamları → tüm payload/envelope şemalarının yapısı (`required` listeleri, `additionalProperties: false`).
- [JSON-SCHEMA#C2] — allOf + kapalı şema kompozisyon uyarısı → `allOf if/then` dalları yalnız `required`/`not required` ekler, yeni alan tanımlamaz; properties tepede tek yerde tanımlıdır (beklenmeyen reddetme riski kapanır).
- [PYDANTIC-MODELS#C1] — doğrulama model sınırında → `parse_envelope` tek giriş noktası, yapılandırılmış `ValidationError` → kategori eşlemesi.
- [PYDANTIC-MODELS#C2] — zorunluluk ve ek-alan politikasının açık yapılandırılması + strict mod → `extra="forbid"`, `Strict()` tamsayı/float/bool (lax koersiyonla .NET'ten sapma kapanır).
- [RMQ-RELIABILITY#C2] — teslim sorumluluklarının ayrılığı ve redelivery'nin normal karşılanması → `delivery_attempt`/`execution_attempt` ayrımı ve dedup'un uygulama sorumluluğu notu (kalıcı iş kabulü B4'te).

JSON Schema Draft 2020-12 davranışı (if/then, oneOf, `not.required`) hafızadan değil, kurulu
jsonschema 4.23.0 ile 38 fixture üzerinden gerçek koşumla doğrulandı.

## 7. Sınırlamalar ve çalıştırılmayan kontroller

1. **Gerçek broker/topology yok:** B1 sözleşme katmanıdır; exchange/kuyruk kurulumu, publisher
   confirm, ACK ve bağlantı yaşam döngüsü B2 kapsamındadır. AMQP properties eşlemesi yalnız
   saf veri olarak test edildi; RabbitMQ.Client üzerinden yayın denenmedi.
2. **.NET tarafında JSON Schema motoru yok:** mevcut test projesine bağımlılık eklenemediğinden
   şemalar .NET'te runtime doğrulanmaz; denklik ayna testleri + ortak fixture'larla sabitlenir
   (K13). Şema motoru istenirse B2'de bağımlılık kararıyla `JsonSchema.Net` değerlendirilebilir.
3. **Ayna testlerinin kapsamı:** required/enum/additionalProperties/routing düzeyindedir; iç içe
   `$defs` (source_reference, usage_record) alan-by-alan aynalanmaz — bu denkleşme ortak
   fixture'ların iki dilde aynı sonucu vermesiyle kanıtlanır.
4. **W0 §2.2'deki `IOutboxService`/`IAgentCommandPublisher`/`IAgentEventConsumer` soyutlamaları
   yazılmadı:** imzaları B3 (outbox) ve B4 (consumer) sahipliğiyle birlikte anlam kazanır; bu
   teslimin isteği DTO + doğrulama + testti. W0 tablosundaki "B1/B3" etiketi B3'e sarktı.
5. **`AgentMessagingSettings` DI kaydı ve appsettings girişi yapılmadı:** mevcut
   `DependencyInjection.cs`/`appsettings.json` bu fazda değiştirilemez; B2/B3 bağlayacak.
6. **Docker/broker ve uçtan uca akış test edilmedi:** B0'daki K8 notları (compose'a broker
   eklenmesi) B2 kapsamında. Test double/broker başarısı gerçek entegrasyon sayılmaz.
7. **NU1902/NU1903 paket uyarıları** (Microsoft.OpenApi, ImageSharp, AngleSharp, OpenTelemetry.Api)
   mevcut bağımlılıkların bilinen açık uyarılarıdır; B1 kapsamı dışındadır, burada kayda geçti.
8. **Şema konumu W0 sapması (K1):** `docs/ai-agent-plan/contracts/` yerine `src/contracts/agent/`;
   gerekçe README ve raporda. Ana orkestratör isterse `git mv` + iki yol sabitiyle taşınabilir.

## 8. Sonraki adım

- **B2:** `contract.json`/registry'deki exchange-adlarıyla topology initializer; publisher
  confirm; `AgentMessagingSettings` DI kaydı; broker sürümüyle çerçeve/boyut limiti doğrulaması (B0 K7 açık kalemi).
- **B3/B4:** outbox kaydı `AgentContractValidator` üzerinden yayın öncesi doğrulanır;
  `backend.agent.events.q` consumer'ı `TryValidateAs<T>` + `AgentEventSequenceGuard` ile projection yazar.
