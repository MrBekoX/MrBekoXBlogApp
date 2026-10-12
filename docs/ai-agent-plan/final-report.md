# AI agent entegrasyonu — Nihai rapor

Tarih: 2026-10-12 · Branch: `feature/ai-agent-integration` (taban `8f148ab` = origin/main) · Kapsam: docs/ai-agent-plan/main-prompt.md — A0–A10, B0–B11, W0–W7 dalgaları

## 1. Kullanıcı açısından tamamlanan davranışlar

- **Makale soru-cevap:** Yayınlanmış makale bağlamında soru sorma; cevap yalnız getirilen kanıtlara dayanır (atıf denetimi, bölüm bağlantıları canonical URL'den), yetersizlikte tek sorgu düzenleme denemesi, kullanıcı dilinde yanıt (TR/EN).
- **Özetleme, seçilen paragraf ve kod açıklaması** akışları (A4 graph'ı).
- **Auto mod seçimi:** 7 ölçütlük kural seti + belirsizlikte yapılandırılmış router modeli; LLM limitleri politika profiline eşlenir; fast/analysis ayrı adım+bütçe ile çalışır; mod yükseltmesi sınırlı ve kayıtlı.
- **Makale merkezli derin araştırma:** ≤4 alt soru, paralel worker'lar, destekleyen/karşı çıkan kanıt kaydı, ikinci tur bütçe koşullu, programatik kanıt doğrulaması (uydurma kaynak ID yapısal olarak dışlanır), tam/kısmi/iptal/başarısız rapor.
- **Web araçları:** search/read/extract/assess ayrı adaptörler; SSRF koruması (DNS+redirect pin'li metadata/özel adres engeli), boyut/tür/timeout sınırları, bütçeli denemeler.
- **Profil/proje rehberi ve içerik önerileri:** onaylı statik kayıtlardan (uydurma yasak, negatif testle), TR/EN.
- **İş birliği talebi:** alan çıkarımı → kısa tamamlama soruları → düzenlenebilir hash'li ActionProposal → needs_input'ta checkpoint → açık backend onayı (idempotent) → AgentActionResultV1 ile doğrulanmış sonuç; başarı metni yalnız doğrulanmış kayıttan sonra.
- **Taşıma ve güvenilirlik:** Backend kabul+outbox tek transaction → RabbitMQ (confirm+mandatory, retry kademeleri, DLQ) → Python intake (inbox, idempotent) → worker (lease/fencing/recovery, checkpoint resume) → olay yayın hattı (atomik event_sequence, seyrekleştirilmiş progress) → backend projection (terminal-öncelik, duplicate engeli) → SignalR + GET replay.
- **İçerik güncelliği:** backend-atanan content_revision, kaldırma tombstone'u, stale komut reddi, sunum öncesi yayın erişim denetimi.
- **UI:** Next.js agent paneli (mod tercihi, durum ayrımı, kaynak kartları, TR/EN, aria-live), sayfa yenileme sonrası replay, admin gözlem sayfası + endpoint'i.
- **Operasyon:** ayrık health endpoint'leri (live/ready/agent-backlog), additive CI workflow, Docker compose final durumu, yerel çalıştırma/topology/migration/DLQ/backup/rollout rehberleri.

## 2. Aşama durumları (A0–A10, B0–B11)

Tümü **Doğrulandı**: her faz bağımsız inceleyici onayı + gerçek test kapısından geçti (pytest + dotnet; W5'ten itibaren faz başına izole vhost + koşum-başına benzersiz scratch DB). Ayrıntılı kanıt: `docs/ai-agent-plan/phase-reports/` (A0–A10, B0–B11, W0-ortak-mimari-kararlari) ve `progress.md` dalga kaydı. W7 birleşik kapısı: **pytest 824 passed/1 skipped, dotnet 205/205** (orchestrator bağımsız seri doğrulaması, 2026-10-12).

## 3. Temel mimari ve sözleşme kararları

Karar kaydı: `decisions.md` D001–D016. Başlıcaları: D007 yeşil alan `src/services/ai-agent-service`; D008 article_revision/content_hash anlamı (BlogPost.Version xmin kullanılmaz); D009 Pydantic iş modelleri + 11 port; D010 tek sözleşme kaynağı `src/contracts/agent/v1` (envelope+delivery_attempt, 18 tür, 38 ortak fixture); D011 migration sahipliği ayrımı; D012 BuildingBlocks.Messaging RabbitMQ.Client 7.x yeniden yazımı; D013 declarer kimliği ayrımı; D014 Alembic 1.20 kilitli; D015 donuk sözleşmelere daraltma köprüleri; D016 dosya tabanlı checkpoint (B11'e değerlendirme bırakıldı). Ortak mimari: `phase-reports/W0-ortak-mimari-kararlari.md`.

## 4. Gerçek çalıştırılan kontroller

- **Birleşik kapı (final):** pytest **824 passed/1 skipped**, dotnet test **205/205** — seri, orchestrator bağımsız.
- **Gerçek broker+DB:** Tüm B fazlarının entegrasyon testleri gerçek RabbitMQ 4.2.9 + PostgreSQL 18 üzerinde (faz bazlı izole vhost + koşum-başına benzersiz scratch DB). B11 E2E: 4 bileşik test (kabul→relay→sözleşme→projection→GET+replay; iptal; kaldırılan içerik maskelemesi; broker kesintisi).
- **Kaynak arşivi:** `search.cjs verify` → valid:true (30 kaynak/60 parça/23 aşama).
- **B11 hata senaryoları:** 12 senaryonun tamamı senaryo→test→sonuç tablosunda PASS (B11-rapor.md).
- **A10 değerlendirme:** 61 örneklik küme + koşucu gerçek giriş noktalarıyla koşuldu; metrikler test sağlayıcıyla ve işaretli.

## 5. Çalıştırılamayan kontroller (engel/ortam)

- **Gerçek LLM/embedding sağlayıcısı:** anahtar/yapılandırma kullanıcıda; tüm model çağrıları test sağlayıcı+double ile (test_executor işaretli). A10'un gerçek-sağlayıcı metrikleri yapılandırma sonrası koşulmalı.
- **Gerçek pgvector:** postgres:18-alpine uzantısız; B11 düşük-riskli bulmadı — karar+adımlar+rollback `operations/pgvector-karari.md`'de (compose imge değişimi gerektirir).
- **GitHub Actions koşumu:** workflow eklendi; Actions çalıştırması yerel ortamdan tetiklenemez (push sonrası ilk koşum CI'ı doğrular).
- **Canlı deployment / production migration / üretim TLS+quorum:** yapılmadı — insan onayı gerekir.
- **Gerçek e-posta bildirimi:** kapsam dışı (kayıt+sonuç bildirimi backend kaydıyla sınırlı).
- **Tarayıcı-otomasyonlu manuel E2E:** kapsamda uçtan uca otomatik testler var; görsel/manuel deneme kullanıcıya rehberlerle bırakıldı.

## 6. Açık risk ve bulgular

- **appsettings.Development.json içinde gerçek görünümlü dev parolaları repoda** (B0 bulgusu; önceden var olan durum) — temizlik+rotasyon kullanıcı kararı.
- **A10 kalite adayları:** F1 'recommend' sinyali makale sorusunu content_suggestion'a düşürebiliyor (routing.py:156); F2 EN yeterlilik kapısı tek sözcükle açılabiliyor (sufficiency.py:24); F3 'sıfır arama' profili ifade edilemiyor (policy.py:58). Davranış değiştirilmedi; gerçek sağlayıcı devredeyken A10 ölçümleriyle değerlendirilmeli.
- **Kullanıcının paralel commit'leri** (`6ed4cc7` web fix feature branch'te, `d72a607` main'de) implementasyon kapsamı dışı — PR öncesi teyit önerilir.
- **Tek düğümlü broker** yüksek erişilebilirlik sağlamaz (plan notu; üretim için quorum değerlendirmesi B11 rehberinde).
- Dersler: `lessons-learned.md` L001–L009 (gitignore/force-add, nul, plan-sayımı, xmin-revizyon, conftest gölgeleme, paralel checkout, geniş force-add+CRLF aynalar, paylaşılan broker/DB çakışması).

## 7. Kullanılan ve eklenen kaynaklar

Arşivdeki 30 kaynak/60 parça kullanıldı (her fazda `search.cjs search --stage ...` CONTEXT'i; verify valid). Yeni dış kaynak eklenmedi — mevcut arşiv yeterli kaldı; gerektiğinde resmî belgelere (Alembic, RabbitMQ 4.2 access-control, pgvector imge manifest) doğrudan doğrulama yapıldı ve bu, faz raporlarına işlendi.

## 8. Commit/branch

Branch `feature/ai-agent-integration`; faz bazlı ~30 commit (A0–A11/B0–B11 raporları ve temizlikler dâhil). PR bağlantısı: bu raporun sunulduğu konuşmayı izleyen PR açılışında paylaşılır (bkz. PR açıklaması).

## 9. Merge/deployment için gereken insan kararları

1. PR incelemesi ve **main'e merge onayı** (otomatik merge yok).
2. `appsettings.Development.json` parolalarının temizliği/rotasyonu.
3. `6ed4cc7` ve `d72a607` commit'lerinin sahiplik teyidi.
4. Gerçek LLM/embedding sağlayıcı yapılandırması (anahtarlar) — sonrasında gerçek-sağlayıcı A10 koşusu.
5. pgvector kararı (operations/pgvector-karari.md) ve üretim broker topolojisi (quorum/TLS).
6. Deployment onayı (merge onayı deployment onayı değildir).

## 10. Yerel kurulum, çalıştırma ve recovery

Rehberler: `docs/ai-agent-plan/operations/` (yerel-çalistirma.md, topology-ve-migration.md, dlq-inceleme.md, backup-restore.md, rollout-rollback.md, pgvector-karari.md). Kısa: `docker compose -f docker/docker-compose.yml up -d postgres rabbitmq` → backend EF migration'ları (RunMigrationsOnStartup) → `alembic upgrade head` (agent şeması, AGENT_DB_PASSWORD env) → backend + python intake/worker/relay başlat → frontend `npm run dev`. Recovery: broker kapalıyken kabul outbox'ta birikir (toparlanma otomatik), worker kesintisinde A8 checkpoint'ten devam, DLQ incelemesi ve replay adımları rehberde.
