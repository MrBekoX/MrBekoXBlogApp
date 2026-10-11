# AI agent uygulama aşamaları ilerleme kaydı

Aktif uygulama aşaması: W2 (A2, A3, B2)

Plan ve kaynak araçlarının hazırlanması tamamlandı; aşağıdaki durumlar ürün kodu geliştirmesini gösterir. Durumlar yalnız gerçek implementasyon ve çalıştırılmış kontrollerle güncellenir.

| Aşama | Durum | Sonuç ve kontroller |
| --- | --- | --- |
| A0 | Doğrulandı | 2026-10-11. Salt okunur denetim: agent çekirdeği için yeşil alan `src/services/ai-agent-service/app/agent_core`; makale modeli BlogPost (ham markdown Content, PostStatus, Slug VO) net ama `BlogPost.Version` (xmin rowversion) revizyon DEĞİL; profil verisi statik, proje verisi yok; model/embedding ayarı yok. Raporlar: phase-reports/A0-rapor.md + agent-architecture.md. Bağımsız inceleyici onayı + `search.cjs verify` valid:true (30 kaynak/60 parça/23 aşama). |
| B0 | Doğrulandı | 2026-10-11. Hosting/Extensions, JWT auth, EF Core 10 + Npgsql, PublicCacheHub + bağlantı limiti, 2 background service, docker/deploy dosya-satır kanıtıyla incelendi. RabbitMQ/outbox/inbox kodu yok; kaldırılan Messaging modülü (3dbdef8) referans olarak işlendi. Kararlar integration-architecture.md K1–K8; test executor üç katmanlı işaretleme. Rapor: phase-reports/B0-rapor.md. Bulgular: `docs/` .gitignore'da (L001 ile çözüldü), appsettings.Development.json'da gerçek görünümlü dev parolaları mevcut (açık risk — kullanıcı kararı). |
| A1 | Doğrulandı | 2026-10-11. 13 iş modeli + RunStatus (completed/partial/needs_input/cancelled/failed, extra=forbid, UTC ISO 8601), 11 port (Protocol), model çağrısız deterministik router, üç giriş noktası (prepare_and_route/execute_plan/resume). Sağlayıcı yapılandırma hataları anlaşılır config_error; test double'lar ayrı pakette is_test_double işaretli. Commit b232966. Orchestrator doğrulaması: pytest → 171 passed, 1 skipped. Rapor: phase-reports/A1-rapor.md. |
| B1 | Doğrulandı | 2026-10-11. Tek sözleşme kaynağı `src/contracts/agent/v1` (envelope + 18 payload şeması + contract.json), 38 ortak fixture (21 valid/17 invalid) + manifest, .NET sözleşme modülü (9 dosya) + Api.Tests/Messaging (4 dosya), Python `app/messaging/contracts` (10 modül). Envelope'a `delivery_attempt` uzantısı; transport retry ↔ execution_attempt/fencing_token ayrımı; kategorize reddetme iki dilde birebir. Commit 4a887cb. Orchestrator doğrulaması: pytest 171 passed/1 skipped; dotnet test 60/60. Not: plan 18 mesaj türü listeler. Rapor: phase-reports/B1-rapor.md. |
| A2 | Başlanmadı | — |
| A3 | Başlanmadı | — |
| A4 | Başlanmadı | — |
| A5 | Başlanmadı | — |
| A6 | Başlanmadı | — |
| A7 | Başlanmadı | — |
| A8 | Başlanmadı | — |
| A9 | Başlanmadı | — |
| A10 | Başlanmadı | — |
| B2 | Başlanmadı | — |
| B3 | Başlanmadı | — |
| B4 | Başlanmadı | — |
| B5 | Başlanmadı | — |
| B6 | Başlanmadı | — |
| B7 | Başlanmadı | — |
| B8 | Başlanmadı | — |
| B9 | Başlanmadı | — |
| B10 | Başlanmadı | — |
| B11 | Başlanmadı | — |

## Dalga kaydı

- W0+W1 (2026-10-11): Dinamik workflow ile A0/B0 paralel denetim → W0 ortak mimari kararları (phase-reports/W0-ortak-mimari-kararlari.md) → A1 → B1. 5/5 faz bağımsız inceleyici onaylı; kapılar: pytest (171/1 skip), dotnet test (60/60). Commit'ler: b232966 (A1), 4a887cb (B1). W0 dokümanları L001 nedeniyle orchestrator tarafından force-add ile commit edildi.
- Ortam notları: dotnet 10.0.400, Python 3.13.9 (pydantic 2.11.7, pytest 8.3.3, langgraph, aio-pika, jsonschema 4.23.0 kurulu), Node 24.16.0, Docker 29.8.2 + Compose v5.5.1. docker/docker-compose.yml'de postgres var, rabbitmq henüz yok (B2 ekleyecek).

## Açık riskler ve karar bekleyenler

- appsettings.Development.json içinde gerçek görünümlü dev parolaları repo geçmişinde duruyor (B0 bulgusu). Temizlik/rotasyon kullanıcı kararıdır; implementasyon buna dokunmadı.
- `article_revision` üretimi B8'de backend tarafında tanımlanacak; BlogPost.Version kullanılmayacak (D008).
- Python migration aracı (Alembic adayı) B4 öncesi kurulu sürüm belgesiyle kilitlenecek (D011).
- Gerçek LLM/embedding sağlayıcısı ve gerçek RabbitMQ henüz uçtan uca devrede değil; fixture/test-double başarısı gerçek sağlayıcı/broker başarısı sayılmaz.
- B2 gerçek broker doğrulamasını Docker ile yapacak; broker erişilemezse faz kısmi kaydedilir.

## Aşama sonu kayıt formatı

Aşama kimliği, yapılan işler, değişen dosyalar, kullanılan [KAYNAK#C1] kimlikleri, gerçek test çıktıları, belirsizlikler ve sonraki adım kaydedilir.
