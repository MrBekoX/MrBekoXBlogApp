# Değerlendirme paketi (evals) — küme, koşucu, rapor sözlüğü

## Küme

`evals/dataset.py` — **61 örnek**, plan A10 kapsam listesinin tamamı
etiketlenmiş (`AREAS`): mod seçimi, web ihtiyacı, retrieval, takip
soruLARI, kaynak desteği, seçilen metin, makale dışı soru, profil, iş
birliği, iki dil, iptal, bütçe, checkpoint, önbellek.

- Örnekler `evals/articles.py`'daki GERÇEK makale içerikleriyle (üç makale:
  tr asyncio, tr PostgreSQL, en event-driven; BlogPost biçiminde, 4-5 bölüm)
  ve onaylı profil/proje/katalog kayıtlarıyla çalışır.
- **Bağımsız etiketleme:** her örneğin `expected` alanı elle yazılmış
  davranış yargısıdır ve `rationale` gerekçesi taşır. `evals/dataset.py`
  `agent_core.routing` modülünü IMPORT ETMEZ (tests/evals
  `test_evals_dataset_shape.py` bunu sürekli denetler) — küme router
  kurallarının kopyası değildir.
- **Geliştirme fixture'larından ayrım:** `tests/` altındaki kısa makaleler
  ve helpers geliştirme testlerinedir; eval paketi `tests.*` import etmez,
  kendi makalelerini ve sağlayıcılarını taşır.

Suiteler: `routing` (18), `qa` (18), `guidance` (9), `research` (4),
`lifecycle` (7), `cache` (5).

## Koşucu

```bash
cd src/services/ai-agent-service
python -m evals.run --suite all --report out/evals   # tam küme + rapor
python -m evals.run --suite routing                   # tek suite
python -m evals.run --list                            # küme listesi
```

Örnekler `agent_core.entrypoints` (prepare_and_route / execute_plan /
resume) üzerinden GERÇEK giriş noktalarıyla koşar; araştırma örnekleri
127.0.0.1'de gerçek HTTP sayfa sunucusuna A6 araçlarıyla bağlanır (SSRF
katmanı devrede). Duman testleri: `tests/evals` (23 test).

## Ölçülen metrik aileleri (plan A10 listesi)

1. **Görev/mod karar doğruluğu:** `routing.mode_accuracy`,
   `intent_accuracy`, `web_need_accuracy`, `clarification_accuracy`,
   `source_scope_accuracy` — beklenen/gerçek eşleşmesi (route kararında;
   execute örneklerinde terminal etkin mod).
2. **İlgili bölümün bulunması:** `retrieval.section_found` (doğrudan
   retrieval sonda) + `section_cited` (atıf hedefi).
3. **İddia–kanıt desteği + hatalı kaynak oranı:** `citations` — her atıf,
   cevapla ≥2 anlamlı terim paylaşan bölüme mi işaret ediyor.
4. **Fast/analysis gecikmesi:** `latency.families` p50/p95 — TEST
   SAĞLAYICIYLA bu değerler orkestrasyon süresidir; gerçek model gecikmesi
   değildir (yapay gecikmeli deadline senaryosu hariçtir).
5. **Araştırma başına araç/model kullanımı:** `research_usage` — model
   çağrısı, web araması, araç olayları + bütçe profili uyumu
   (`within_budget`); kaynak sayfası okumaları BudgetStore committed
   görünümünden (`min_source_reads`).
6. **Checkpoint'ten devam başarısı:** `resume.success_rate` — 10 senaryo
   (iptal sonrası devam, deadline, evidence_stale, not_resumable, yanlış
   execution_id, iş birliği 3-adımlı zincir).
7. **Bütçe/iptal davranışı:** `budget_cancel.accuracy` — terminal
   doğruluğu (cancelled/timeout/budget_exhausted/kısmi).
8. **Önbellek sözleşmesi:** `cache_policy.pass_rate` — içerik hash/dil/
   kapsam/sürüm anahtar denetimleri + konuşma-bağı dışlama.

## Sağlayıcı işaretlemesi

Her örnek sonucu ve rapor `provider="test_executor"` taşır; rapor başında
"GERÇEK sağlayıcı ile çalıştırılmadı" beyanı vardır. Test sağlayıcı
(`is_test_double=True`) sonuçları gerçek sağlayıcı başarısı SAYILMAZ.

## Bilinen sapma ve gözlemler (2026-10-12 koşusu)

- **F1 — `recommend` sinyal çakışması (r08):** "What upper bound does the
  *article recommend* …?" makale sorusu, öneri sinyali (`recommend`)
  yüzünden `content_suggestion` niyetine düşüyor. Bağımsız etiket
  `article_qa`; sinyalin soru bağlamına bakması gerekir. agent_core
  davranışı A10 kapsamında değiştirilmez (kapsam dışı); router sahibine
  not edildi. Etki: intent_accuracy 21/22.
- **F2 — İngilizce yeterlilik kapısı tek işlev sözcüğüyle açılabiliyor:**
  yeterlilik belirteç-örtüşmesine dayalı (`MIN_MATCHED_TOKENS=1`); "without"
  gibi dolgu olmayan işlev sözcüğü makaleyle kazara örtüşünce makale-dışı
  soru üretime sarktı (q11'in ilk sitemi). Ölçüm için soru, kazara örtüşme
  taşımayacak biçimde yeniden yazıldı; davranış gözlemi burada kayıtlı.
- **F3 — "sıfır arama" profili politika düzeyinde ifade edilemez:**
  `BudgetPolicy.from_budget_profile` arama sınırını `max(profile, 1)`
  tabanına sabitler; profil 0'da bile bir arama yapılıyor, kota dolunca
  akış zarif `partial` terminalinde kalıyor (s04 ölçümü). Sınırın gerçekten
  0 olabilmesi politika değişikliğidir (kapsam dışı; bütçe sahibine not).

## Rapor

- `out/evals/eval-report.json` — makine-okur (örnek başına denetim kayıtları).
- `out/evals/eval-report.md` — insan-okur özet + kapsam tablosu + örnek
  başına etiket gerekçeleri.
- `docs/evals-report.md` — teslim anındaki son koşumun kopyası.
