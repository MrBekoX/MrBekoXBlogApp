# AI agent uygulama aşamaları ilerleme kaydı

Aktif uygulama aşaması: W4 (A6→A7, B5)

Plan ve kaynak araçlarının hazırlanması tamamlandı; aşağıdaki durumlar ürün kodu geliştirmesini gösterir. Durumlar yalnız gerçek implementasyon ve çalıştırılmış kontrollerle güncellenir.

| Aşama | Durum | Sonuç ve kontroller |
| --- | --- | --- |
| A0 | Doğrulandı | 2026-10-11. Salt okunur denetim: agent çekirdeği için yeşil alan `src/services/ai-agent-service/app/agent_core`; makale modeli BlogPost (ham markdown Content, PostStatus, Slug VO) net ama `BlogPost.Version` (xmin rowversion) revizyon DEĞİL; profil verisi statik, proje verisi yok; model/embedding ayarı yok. Raporlar: phase-reports/A0-rapor.md + agent-architecture.md. Bağımsız inceleyici onayı + `search.cjs verify` valid:true (30 kaynak/60 parça/23 aşama). |
| B0 | Doğrulandı | 2026-10-11. Hosting/Extensions, JWT auth, EF Core 10 + Npgsql, PublicCacheHub + bağlantı limiti, 2 background service, docker/deploy dosya-satır kanıtıyla incelendi. RabbitMQ/outbox/inbox kodu yok; kaldırılan Messaging modülü (3dbdef8) referans olarak işlendi. Kararlar integration-architecture.md K1–K8; test executor üç katmanlı işaretleme. Rapor: phase-reports/B0-rapor.md. Bulgular: `docs/` .gitignore'da (L001 ile çözüldü), appsettings.Development.json'da gerçek görünümlü dev parolaları mevcut (açık risk — kullanıcı kararı). |
| A1 | Doğrulandı | 2026-10-11. 13 iş modeli + RunStatus (completed/partial/needs_input/cancelled/failed, extra=forbid, UTC ISO 8601), 11 port (Protocol), model çağrısız deterministik router, üç giriş noktası (prepare_and_route/execute_plan/resume). Sağlayıcı yapılandırma hataları anlaşılır config_error; test double'lar ayrı pakette is_test_double işaretli. Commit b232966. Orchestrator doğrulaması: pytest → 171 passed, 1 skipped. Rapor: phase-reports/A1-rapor.md. |
| B1 | Doğrulandı | 2026-10-11. Tek sözleşme kaynağı `src/contracts/agent/v1` (envelope + 18 payload şeması + contract.json), 38 ortak fixture (21 valid/17 invalid) + manifest, .NET sözleşme modülü (9 dosya) + Api.Tests/Messaging (4 dosya), Python `app/messaging/contracts` (10 modül). Envelope'a `delivery_attempt` uzantısı; transport retry ↔ execution_attempt/fencing_token ayrımı; kategorize reddetme iki dilde birebir. Commit 4a887cb. Orchestrator doğrulaması: pytest 171 passed/1 skipped; dotnet test 60/60. Not: plan 18 mesaj türü listeler. Rapor: phase-reports/B1-rapor.md. |
| A2 | Doğrulandı | 2026-10-11. LangGraph ortak state (reducer'lar, checkpoint-dışı artifact deposu), atomik rezervasyonlu PolicyBudgetStore, BudgetGuard (sınırlı retry, tahmin/belirsiz kullanım işaretleri), Send fan-out'lu graph yürütücü. langgraph 1.0.6. Gate: tests/state 34 passed; tam suite 277 passed/1 skipped. Rapor: phase-reports/A2-rapor.md. |
| A3 | Doğrulandı | 2026-10-11. Markdown hiyerarşisi + kod bloğu koruyan bölümleyici; Türkçe + tekrarlanan başlık anchor sözleşmesi (ortak fixture'lar); cosine+BM25+RRF hibrit arama, skorlamadan-önce filtreler; content_hash ile idempotent/atomik indeksleme; kaldırma iş modeli + önbellek geçersizleme. pgvector: şema DDL + adaptör sözleşmesi belgelendi, gerçek entegrasyon B8'de. Gate: tests/content 55 passed. Rapor: phase-reports/A3-rapor.md. |
| B2 | Doğrulandı | 2026-10-11. RabbitMQ 4.2.9 broker compose'a salt-ekleme ile kuruldu (healthy, 127.0.0.1'e bound, vhost blogapp_dev, yetki regex'li servis kullanıcıları, ayrı declarer kimliği). BuildingBlocks.Messaging RabbitMQ.Client 7.2.2 ile sıfırdan (confirm+mandatory publisher, idempotent topology initializer, prefetch'li consumer); Python aio-pika 9.5.8 robust connection/topology. Dört kabul ölçütü gerçek broker'da kanıtlandı (tekrarlı kurulum, unroutable rk, kesinti sonrası reconnect, yetkisiz yayın engeli). Gate: messaging_broker 17 passed; dotnet test 72 passed. Rapor: phase-reports/B2-rapor.md (F1 izin modeli bulgusu → D013). |
| A4 | Doğrulandı | 2026-10-11. Makale soru-cevap akışı: altı node (validate/retrieve/evaluate/generate/control/finalize), SnapshotRetriever (A3 indeks üstünde), deterministik yeterlilik kararı, atıf seçimi/denetimi ve bölüm bağlantı guardrail'leri; yedi kabul senaryosu + kaynak-içi talimat senaryosu testli. Gate: tests/qa 44 passed. Rapor: phase-reports/A4-rapor.md. |
| A5 | Doğrulandı | 2026-10-12. RouteDecision 8 alan kümesi + RunIntent; 7 ölçütlük kural seti + belirsizlikte yapılandırılmış router modeli (limitler politika profiline eşlenir, LLM limiti doğrudan uygulanmaz); analysis alt graph'ı (plan/gather/evidence/generate); sınırlı+kayıtlı mod yükseltmesi (ModeUpgradeRecord); web yoksa doğru 'kullanılamaz' durumu. Gate: tests/qa+tests/routing 95 passed (iki sırayla). Bulgu: RAG aracı ayna hatası → L008 ile onarıldı. Rapor: phase-reports/A5-rapor.md. |
| B3 | Doğrulandı | 2026-10-11. AgentRun/OutboxMessage entity'leri, AcceptAgentRunCommand (oturum→makale erişimi→idempotency→sahiplik+kota→turn_sequence→immutable snapshot (D008/L004)→commit-öncesi zarf doğrulama→tek transaction), lease/claim'li outbox relay (confirm sonrası işaretleme, kayıp confirm'de republish, MaxAttempts), EF migration (additive). Gerçek broker+postgres ile entegrasyon testleri. Rapor: phase-reports/B3-rapor.md. |
| B4 | Doğrulandı | 2026-10-11. Intake consumer: B1 doğrulama→tür/üretici politikası→inbox benzersizliği→run_id+payload hash idempotency→AgentJob+accepted outbox TEK transaction→commit→ACK; graph callback içinde çalıştırılmaz (B6 bağlantı noktası). JobStore/IntakeService/OutboxRelay; **Alembic 1.20.0 kilitlendi** (async/asyncpg env, version_table_schema='agent' — D014), asyncpg+sqlalchemy+alembic pyproject'e eklendi. Gerçek broker + scratch DB (blogdb_agent_test) ile 14 test iki kez koşuldu. Tam suite: 386 passed/1 skipped. Rapor: phase-reports/B4-rapor.md. |
| A6 | Başlanmadı | — |
| A7 | Başlanmadı | — |
| A8 | Başlanmadı | — |
| A9 | Başlanmadı | — |
| A10 | Başlanmadı | — |
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
- W2 (2026-10-11): A2/A3/B2 paralel + bütünleştirme incelemesi. 3/3 faz doğrulandı. Commit'ler: 4a19604 (A2), b93ae3c (A3), 259ed6c (B2), f0fb3aa (test paketi + raporlar force-add; L001'in tests/ için tekrarı). Orchestrator doğrulaması: tam pytest + dotnet test ayrıca koşuldu. Ortam olayı: W2 sırasında aynı checkout'ta main'e geçilip d72a607 commit'lenip geri dönüldü ve task kapsamı dışı 6ed4cc7 (web fix) feature branch'e girdi — kullanıcı paralel çalışması olarak kaydedildi (L006); veri kaybı yok (reflog + A2 raporu §6 kanıtlı).
- W3 (2026-10-11/12): A4→A5 zinciri + B3/B4 paralel + bütünleştirme. 4/4 faz doğrulandı, bütünleştirme incelemesi 0 bulgu. Commit'ler: 468d83e (A4), 0a6b951 (A5), dc81ed9 (B3), 64d3f1f (B4). Tam suite: pytest 386 passed/1 skipped; dotnet test yeşil. Run kazası: sweep adımındaki `git add -f src` node_modules'a dalıp timeout+stale index.lock üretti (L007); dört faz commit'i zarar görmeden geldi, faz raporları orchestrator tarafından tamamlandı. Temizlik: takip edilmiş 78 .pyc + 492 bin/obj dosyası index'ten çıkarıldı; .gitignore'a agent servis test istisnası eklendi (L001 kalıcı çözüm). RAG aracı CRLF ayna bozulması L008 ile onarıldı (rebuild-metadata + .gitattributes eol=lf).
- Ortam notları: RabbitMQ 4.2.9 broker çalışıyor; postgres compose servisi B3/B4 tarafından kullanıldı (agent scratch DB: blogdb_agent_test). Alembic 1.20.0 kurulu.

## Açık riskler ve karar bekleyenler

- appsettings.Development.json içinde gerçek görünümlü dev parolaları repo geçmişinde duruyor (B0 bulgusu). Temizlik/rotasyon kullanıcı kararıdır; implementasyon buna dokunmadı.
- Kullanıcı paralel çalışması: feature branch'te 6ed4cc7 (fix(web) Quick Actions) ve main'de d72a607 (ignore chore) commit'leri implementasyon kapsamı dışı; PR öncesi kullanıcı teyidi önerilir.
- `article_revision` üretimi B8'de backend tarafında tanımlanacak; BlogPost.Version kullanılmayacak (D008).
- Python migration aracı kilitlendi: Alembic 1.20.0 (D014). A3'ün gerçek pgvector entegrasyonu B8'de.
- Gerçek LLM/embedding sağlayıcısı hâlâ devrede değil; fixture/test-double başarısı gerçek sağlayıcı başarısı sayılmaz.
- B2 gerçek broker doğrulaması yerel Docker broker'la yapıldı; üretim quorum/TLS kurulumu B11'de.

## Aşama sonu kayıt formatı

Aşama kimliği, yapılan işler, değişen dosyalar, kullanılan [KAYNAK#C1] kimlikleri, gerçek test çıktıları, belirsizlikler ve sonraki adım kaydedilir.
