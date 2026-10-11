# AI agent planı karar kaydı

Bu kayıt kullanıcının onayladığı tasarım kararlarını korur. Uygulama aşamalarının tamamlandığı anlamına gelmez.

| Kimlik | Karar | Durum |
| --- | --- | --- |
| D001 | Agent Python ve LangGraph ile geliştirilecek. | Kullanıcı kararı |
| D002 | Backend ile agent uygulama haberleşmesi RabbitMQ üzerinden olacak. | Kullanıcı kararı |
| D003 | Agent çekirdeği ve haberleşme ayrı planlarda tutulacak; diyagramlar korunacak. | Kullanıcı kararı |
| D004 | Geliştirme referansları için 20–30 güvenilir kaynak ve kaynak arama aracı hazırlanacak. | Kullanıcı kararı |
| D005 | Geliştirme RAG promptu yalnız verilen CONTEXT'e dayanacak, eksikte yetersiz bilgi diyecek ve her iddiada kaynak gösterecek. | Kullanıcı kararı |
| D006 | Yerel kaynak aracı mevcut Node.js ile bağımlılıksız çalışır; üretim agent'ının Python seçimini değiştirmez. | Bu teslimin uygulama kararı |
| D007 | A0: Agent çekirdeği yeşil alan olarak `src/services/ai-agent-service/app/agent_core` altına kurulur; 3dbdef8'te silinen eski FastAPI/LangChain servisi birebir geri getirilmez. | Bu teslimin uygulama kararı |
| D008 | A0/W0: `article_revision` backend'in atadığı, makale başına monoton, yayımlanmış içerik anı kimliğidir; mevcut `BlogPost.Version` (xmin rowversion) bu anlamda KULLANILMAZ. `article_content_hash` sunulan Content'in UTF-8 SHA-256 özetidir. | Bu teslimin uygulama kararı |
| D009 | A1: 13 iş modeli + RunStatus (completed/partial/needs_input/cancelled/failed) Pydantic v2 extra=forbid ile `agent_core/models` altında; 11 port Protocol olarak `ports/` altında; test double'lar `adapters/test_doubles` altında `is_test_double` işaretli; test sağlayıcısı environment != test'te reddedilir. | Bu teslimin uygulama kararı |
| D010 | B1: Tek sözleşme kaynağı `src/contracts/agent/v1` (W0'ın `docs/ai-agent-plan/contracts/` önerisi, `docs/` .gitignore'da olduğundan versiyonlanamaz gerekçesiyle `src/contracts`'a alındı). Envelope planın 12 alanı + `delivery_attempt` uzantısı; zorunlu 7 alan; `MaxPayloadBytes` 256 KiB; 18 mesaj türü; kategorize reddetme (8 kategori) iki dilde aynı fixture'larla birebir. | Bu teslimin uygulama kararı |
| D011 | B0/W0: Backend şeması EF Core ile Infrastructure assembly'den yönetilir (tek konsolide migration); agent tablolarının tek sahibi Python'dur, `agent` schema'sında kendi aracıyla (Alembic adayı; B4 öncesi kurulu sürüm belgesiyle kilitlenir) yönetir; schema'lar arası FK kurulmaz. | Bu teslimin uygulama kararı |
| D012 | B2 öncesi mimari karar: BuildingBlocks.Messaging yeniden eklenir — RabbitMQ.Client 7.x API'leriyle, kaldırılan 3dbdef8 kodu birebir kopyalanmadan, `src/backend/BuildingBlocks/BuildingBlocks/Messaging` altında. Bu, `.claude/rules/building-blocks.md`'in "yeniden eklenmesi gerekirse önce dur ve mimari karar al" kuralının gereğini olan karardır. | Bu teslimin uygulama kararı |
| D013 | B2: Topology declarer kimliği, uygulama servis kimliklerinden ayrı operasyonel bir kimliktir (RabbitMQ 4.2'de DLX'li kuyruk yaratımı declarer'dan kuyruğa read + DLX'e write ister; pasif declare hedefte en az bir izin ister). Uygulama kimlikleri (backend_svc/agent_svc) yalnız kendi rol kapsamında publish/consume yapar; declarer uygulama mesajı yayınlamaz. Retry/DLX kuyruk adları B1 registry'sinden türetilir (diller arası tek kaynak). | Bu teslimin uygulama kararı |

## Yeni karar formatı

Tarih, ilgili aşama, karar, gerekçe, kullanılan kaynak kimlikleri ve kullanıcı talimatıyla ilişkisini kaydet. Akademik öneriyi sessizce yeni ürün gereksinimi haline getirme.

### 2026-10-11 — W0+W1 uygulama kararlarının gerekçeleri

- **D007 (A0):** Çalışma ağacında hiç agent kodu yoktu; eski servis 3dbdef8'de bilinçli silinmişti. Mevcut .NET Onion ve Next.js yapısı agent çekirdeği için yer sunmuyor; planın önerdiği `src/services/ai-agent-service` konumu yeşil alan olarak seçildi. Kanıt: A0-rapor.md §5. Kullanıcı ilişkisi: D001'in (Python/LangGraph) konum sonucu; yeni ürün gereksinimi yaratmaz.
- **D008 (A0/W0):** `BlogPostConfiguration.cs:32-34` Version'ı xmin concurrency token olarak tanımlıyor; DTO'ya çıkmıyor ve yayın anını tanımlamıyor. Revizyon anlamı B8'de ayrı üretilecek. Kanıt: W0-ortak-mimari-kararlari.md §1.4 anlam sözlüğü. İçerik güncelliği hatalarını (eski snapshot'ın canlı sayılması) önler.
- **D009 (A1):** Plan A1'in model/port listesinin birebir uygulaması; transport kavramlarının iş modellerine sızmaması ve test double ayrımı plan kabul ölçütleridir. Kanıt: A1-rapor.md + pytest 171 passed.
- **D010 (B1):** `docs/` kök dizini .gitignore'da olduğundan W0'ın şema konumu önerisi versiyonlanamazdı; `src/contracts/agent/v1` iki dilin erişebileceği tracked tek konum olarak seçildi (taşınırsa yalnız iki yol sabiti değişir: `ContractPaths.cs`, `contract_paths.py`). `delivery_attempt` planın "transport retry ile agent yürütme denemesi ayrı alanlarda" kuralının zarftaki karşılığıdır. Kanıt: B1-rapor.md K1/K3; fixture 38/38 iki dilde yeşil.
- **D011 (B0/W0):** Mevcut proje tek konsolide EF migration politikası kullanıyor (src/backend/CLAUDE.md); agent tabloları backend şemasına karışırsa sahiplik ve rollback ayrımı bozulur. Kanıt: W0-ortak-mimari-kararlari.md §3.
- **D012 (B2 hazırlığı):** Kural dosyası yeniden eklemeyi mimari karara bağlıyor; karar RabbitMQ.Client 7.x ile temiz yeniden yazım yönündedir (eski client 6.x API'leri). Kanıt: B0-rapor.md F1; `.claude/rules/building-blocks.md` "Mevcut moduller" bölümü.
