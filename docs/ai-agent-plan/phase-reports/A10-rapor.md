# A10 Faz Raporu — Agent kalitesini değerlendir ve teslimi tamamla

- **Tarih:** 2026-10-12
- **Branch:** `feature/ai-agent-integration`
- **Kapsam:** Plan `docs/ai-agent-plan/01-agent-gelistirme-plani.md` "Aşama A10" (satır 447-475)
- **Yürütücü:** A10 implementasyon agent'ı (yalnız izinli dosyalarda çalıştı; commit/push yapılmadı — L006)
- **Ön kontroller:** `git branch --show-current` → feature/ai-agent-integration; RAG aracı `search.cjs verify` → `valid:true` (30 kaynak/60 parça/23 aşama; L008 kontrolü).

## 1. Yapılan işler

### 1.1 Değerlendirme kümesi (61 örnek; plan ölçütü ≥40)

`src/services/ai-agent-service/evals/`:

- **Gerçek içerikler** (`evals/articles.py`): üç makale BlogPost biçiminde
  (başlık + `##` bölümler + kod blokları + somut değerler) — tr "Asyncio
  Kuyruk Yönetimi ve Sınırlandırma", tr "PostgreSQL İndeksleme Rehberi",
  en "Designing Event-Driven Microservices"; onaylı profil/proje/katalog
  kayıtları; üç yerel araştırma sayfası (127.0.0.1 gerçek HTTP).
- **Bağımsız etiketler** (`evals/dataset.py`): her örneğin `expected`
  alanı elle yazılmış yargı + `rationale` gerekçesi. Küme modülü
  `agent_core.routing`'i import etmez ve kural fonksiyonu çağırmaz —
  `tests/evals/test_evals_dataset_shape.py` bunu sürekli denetler
  (plan: "örnekleri router kurallarının kopyası haline getirme").
- **Kapsam (plan listesinin tamamı):** mod seçimi 23, web ihtiyacı 9,
  retrieval 12, takip soruları 3, kaynak desteği 5, seçilen metin 3,
  makale dışı 2, profil 9, iş birliği 5, iki dil 10, iptal 2, bütçe 4,
  checkpoint 8, önbellek 5 örnek (bir örnek birden çok alanı kapsar).
- **Geliştirme fixture'larından ayrım:** eval paketi `tests.*` import
  etmez; kendi makalelerini ve sağlayıcılarını taşır. `tests/qa`'daki kısa
  makale ile hiçbir içerik paylaşılmaz ("Merhaba Dünya" makalesi eval
  kümesinde yok — testle denetlenir).

### 1.2 Ölçüm koşucusu

`evals/harness.py` + `evals/run.py`: örnekler GERÇEK giriş noktalarıyla
(`prepare_and_route` / `execute_plan` / `resume`) koşar; araştırma örnekleri
A6 araçlarıyla 127.0.0.1'deki gerçek HTTP sayfa sunucusuna bağlanır (SSRF
katmanı devrede). Planın yedi ölçü ailesinin tamamı ölçülür:

| Ölçü (plan A10) | Rapor alanı | Sonuç (2026-10-12 koşusu) |
| --- | --- | --- |
| Görev/mod karar doğruluğu | `routing.mode_accuracy` | 27/27 = **1.00** |
| Görev türü (intent) doğruluğu | `routing.intent_accuracy` | 21/22 = **0.9545** (r08 → bulgu F1) |
| Web ihtiyacı doğruluğu | `routing.web_need_accuracy` | 17/17 = **1.00** |
| Açıklama (clarification) doğruluğu | `routing.clarification_accuracy` | 2/2 = 1.00 |
| İlgili bölümün bulunması | `retrieval.section_found` | 12/12 = **1.00** (atıf hedefi: 12/12) |
| İddia–kanıt desteği | `citations.claim_support_rate` | 65/68 = **0.9559** |
| Hatalı kaynak oranı | `citations.wrong_source_rate` | 3/68 = **0.0441** |
| Fast gecikmesi | `latency.families.fast` | p50 0.016s / p95 0.024s (20 koşu) |
| Analysis gecikmesi | `latency.families.analysis` | p50 0.023s / p95 0.024s (6 koşu) |
| Araştırma kullanımı | `research_usage` | ort. 1.0 model + 2.0 web arama/koşu; kaynak okumaları BudgetStore committed görünümünde; bütçe içi koşular 2/2 (etkili araştırma örnekleri) |
| Checkpoint'ten devam | `resume.success_rate` | 10/10 = **1.00** |
| Bütçe/iptal davranışı | `budget_cancel.accuracy` | 4/4 = **1.00** |
| Önbellek sözleşmesi | `cache_policy.pass_rate` | 9/9 denetim = **1.00** |

Toplam: 61 örnek koşuldu; 232 beklenti denetiminin 231'i geçti (0.9957);
tek sapma F1 (bilinçli bağımsız etiket). **Tüm değerler
`provider="test_executor"` işaretlidir.**

### 1.3 Sağlayıcı işaretlemesi (plan: "gerçek sağlayıcıyla çalıştırılmayan sonuçları açıkça işaretle")

- Ortamda GERÇEK LLM/embedding/web-arama sağlayıcısı yoktur (progress.md
  açık riski). `evals/providers.py`'daki her sağlayıcı `is_test_double=True`
  taşır; her CaseResult ve rapor `provider="test_executor"` taşır ve rapor
  başında "GERÇEK sağlayıcı ile çalıştırılmadı" beyanı vardır.
- Gecikme metrikleri test sağlayıcıyla ORKESTRASYON süresidir; rapor bunu
  açıkça yazar. Gerçek model sadakati/gerçek gecikme bu koşudan ölçülemez
  ve başarı yazılmamıştır.

### 1.4 Önbellek anahtar sözleşmesi (plan madde 5)

`evals/cache_policy.py`: anahtar = SHA-256(sürüm + **içerik hash'i** +
**dil** + **soru kapsamı** + **yapılandırma parmak izi** [embedding model
id, akış config'leri, bütçe profili, CHECKPOINT/STATE şema sürümleri, prompt
sürümü]); `is_shared_cache_eligible()` konuşma geçmişi/seçili metin
taşıyan istekleri ortak önbellek dışı bırakır. 5 senaryo + 9 denetim
koşucuda ölçülür; mevcut üretim içi retrieval önbelleğinin anahtar bileşimi
belgelendi (`content/index.py:354`, `content/retrieval.py:51`).
agent_core davranışı DEĞİŞTİRİLMEDİ (kapsam dışı) — sözleşme referans
gerçekleştirim + ölçüm + dokümantasyon olarak teslim edildi.

### 1.5 Son teslim paketi (plan: kullanım örnekleri, portlar, yapılandırma, rapor, sürümler, giriş noktaları)

- `src/services/ai-agent-service/README.md` — hızlı başlangıç, üç giriş
  noktasının yerel test girdisiyle kullanım örneği, kapı komutları.
- `docs/entry-points.md` — haberleşme adaptörünün çağıracağı üç giriş
  noktası + çağrı sözleşmeleri + iş birliği 3-adımlı zincir + hata eşlemesi.
- `docs/port-contracts.md` — 11 port sözleşme özeti, D015 daraltma
  köprüleri, RouteDecision 8 alan, hata sözleşmesi.
- `docs/configuration.md` — bütçe profilleri, akış config'leri, web
  ayarları, checkpoint, önbellek kuralı, eval koşucusu.
- `docs/state-schema-versions.md` — CHECKPOINT=1, STATE=1, COLLAB_STATE=1,
  mesaj sözleşmesi v1, ANSWER_CACHE_KEY_VERSION, Alembic 0001-0003, D008
  revizyon anlamı + uyumluluk kuralları.
- `docs/evals.md` + `docs/evals-report.md` — değerlendirme raporu sözlüğü
  ve son koşumun kopyası.

## 2. Bulgular (agent_core davranışı A10 kapsamında DEĞİŞTİRİLMEDİ)

- **F1 (orta) — `recommend` öneri sinyali makale sorusunu yakalıyor.**
  Dosya: `app/agent_core/routing.py:156-160` (`_SUGGESTION_SIGNALS`).
  Trigger: "What upper bound does the article **recommend** for the
  queue?" (eval örneği r08, en). Etki: niyet `article_qa` yerine
  `content_suggestion`; kullanıcı makale sorusuna katalog önerisi alır.
  Kanıt: eval koşusu `r08(content_suggestion≠article_qa)`. Öneri: sinyal
  eşleşmesinin soru bağlamıyla ("does the article" kalıbı) negatif
  filtrelenecek şekilde router sahibince gözden geçirilmesi. A10 dosya
  sahipliği dışında olduğundan uygulanmadı.
- **F2 (düşük) — İngilizce yeterlilik kapısı tek işlev sözcüğüyle
  açılabiliyor.** Dosya: `app/agent_core/qa/sufficiency.py:24`
  (`MIN_MATCHED_TOKENS=1`). Trigger: "…basmati rice **without** a cooker?"
  — "without" makale metninde geçtiği için makale-dışı soru üretime
  sarktı. Ölçüm amacıyla q11 sorusu kazara örtüşme taşımayan biçimde
  yeniden yazıldı; davranış gözlemi kayda geçti. Öneri: EN dolgu sözcük
  kümesinin genişletilmesi (qa/text sahibi).
- **F3 (düşük) — "sıfır arama" profili politika düzeyinde ifade
  edilemez.** Dosya: `app/agent_core/budget/policy.py:58`
  (`max_search_calls=max(profile.max_web_search_calls, 1)`). Trigger:
  `max_web_search_calls=0` profili (eval örneği s04). Etki: bir arama
  yine yapılıyor; kota dolunca akış zarif `partial` terminalinde kalıyor
  (bu kısım doğru davranış). Öneri: gerçek 0 üst sınırı isteniyorsa
  politika eşlemesinin gözden geçirilmesi (bütçe sahibi).

Hepsi ölçüm tablosuyla kanıtlıdır; hiçbiri A10 kapsamında sessizce
"düzeltme" maskesiyle değiştirilmedi.

## 3. Gerçek çalıştırılan kontroller

| Komut | Sonuç |
| --- | --- |
| `node docs/ai-agent-plan/source/tools/search.cjs verify` | `valid:true` (30 kaynak/60 parça/23 aşama) |
| `python -m evals.run --suite all --report out/evals` (hizmet kökünden) | 61 örnek; 60 örnekte tüm denetimler geçti; 1 sapma (r08/F1); rapor `out/evals/eval-report.{json,md}` |
| `python -m pytest src/services/ai-agent-service/tests/evals -q` (repo kökünden — GATE) | **23 passed** |
| Tam regresyon (GATE): `python -m pytest src/services/ai-agent-service/tests -q --ignore=.../messaging_broker --ignore=.../intake --ignore=.../events --ignore=.../worker --ignore=.../control --ignore=.../content_sync --ignore=.../collab` (repo kökünden, SERİ — L009) | **651 passed, 1 skipped** (30.8s) |

Koşum sırası seridir; broker/DB isteyen dizinler kapı komutunda zaten hariçtir.

## 4. Kullanılan kaynak kimlikleri (SADECE CONTEXT)

A10 aşama CONTEXT'i (`search.cjs search --stage A10`): [AC-SELF-RAG#C2]
(kaynak/cevap değerlendirmesi kavramsal referans — "genel modele kaynaklı
cevap promptu vermek özel eğitimle aynı değildir"; koşucunun ölçtüğü
şeyin sınırını belirler), [AC-LOST-MIDDLE#C2] (uzun bağlamda bilgi konumu
— ilgili bölüm bulma ölçümünün gerekçesi), [LG-RAG#C2] (bağlam veri olarak
ele alınır, içindeki talimat izlenmez — GroundedTestModel ve QA prompt
sözleşmesi), [ENG-CONTEXT#C1] (sınırlı bağlamda ilgili bilgiyi getirme),
[ENG-CONTEXTUAL#C1], [AC-SELF-RAG#C1]; gecikme/iptal davranışı için planın
A10 kaynak listesindeki [PY-ASYNCIO#C2] (entrypoints deadline
gerçekleştiriminde mevcut).

## 5. Değişen/oluşan dosyalar (tamamı izinli)

```
src/services/ai-agent-service/evals/__init__.py
src/services/ai-agent-service/evals/_paths.py
src/services/ai-agent-service/evals/articles.py
src/services/ai-agent-service/evals/providers.py
src/services/ai-agent-service/evals/cache_policy.py
src/services/ai-agent-service/evals/dataset.py
src/services/ai-agent-service/evals/metrics.py
src/services/ai-agent-service/evals/harness.py
src/services/ai-agent-service/evals/report.py
src/services/ai-agent-service/evals/run.py
src/services/ai-agent-service/tests/evals/evals_bootstrap.py
src/services/ai-agent-service/tests/evals/test_evals_dataset_shape.py
src/services/ai-agent-service/tests/evals/test_evals_cache_policy.py
src/services/ai-agent-service/tests/evals/test_evals_runner_smoke.py
src/services/ai-agent-service/tests/evals/test_evals_metrics.py
src/services/ai-agent-service/README.md
src/services/ai-agent-service/docs/entry-points.md
src/services/ai-agent-service/docs/port-contracts.md
src/services/ai-agent-service/docs/configuration.md
src/services/ai-agent-service/docs/state-schema-versions.md
src/services/ai-agent-service/docs/evals.md
src/services/ai-agent-service/docs/evals-report.md        (üretilen raporun kopyası)
src/services/ai-agent-service/out/evals/                  (üretilen çıktı; commit dışı kalabilir)
docs/ai-agent-plan/phase-reports/A10-rapor.md             (bu dosya — L001: force-add gerekir)
```

Üretilen çıktı (`out/evals/`) tekrar üretilebilirdir:
`python -m evals.run --suite all --report out/evals`.

## 6. Belirsizlikler ve sonraki adım

- **Ölçülemeyenler (açık):** gerçek model sadakati, gerçek sağlayıcı
  gecikmesi, gerçek web arama kalitesi ve gerçek pgvector davranışı bu
  koşudan ölçülemedi (sağlayıcı yok; pgvector B11). İlgili metrikler
  test_executor işaretli; hiçbiri başarı iddiası olarak yazılmadı.
- F1-F3 agent_core sahiplerine (router / qa.text / budget) geçirilmek
  üzere kaydedildi; A10 kapsamında davranış değişikliği yapılmadı.
- Birleşik uçtan uca kapı: A10 değerlendirmesi B10-B11 ile birlikte
  gerçek sağlayıcı + gerçek pgvector + gerçek broker üzerinden tekrar
  koşulmalıdır (main prompt: "Tam uçtan uca başarı iddiasını eksik
  bileşenle verme").
- Orchestrator notu: `docs/` altındaki YENİ dosyalar (A10-rapor.md)
  L001 gereği `git add -f docs/ai-agent-plan/phase-reports/A10-rapor.md`
  ile alınmalıdır; `src/services/ai-agent-service/tests/` istisnası
  .gitignore'da mevcut (L007 çözümü), `evals/` ve `docs/` (hizmet altı)
  tracked alandadır.
