# A7 Faz Raporu — Makale merkezli derin araştırma graph'ı

- **Faz:** A7 (makale ve araştırma amacından kaynaklı rapor üreten alt graph; A6 web araçlarının tüketimi)
- **Tarih:** 2026-10-12
- **Branch / temel:** `feature/ai-agent-integration` (checkout/branch/stash işlemi YAPILMADI — L006)
- **Rol:** A7 implementasyon agent'ı
- **Okunan girdiler:** `docs/ai-agent-plan/01-agent-gelistirme-plani.md` "Aşama A7" (satır 352–370, satır satır), `main-prompt.md`, `decisions.md` (D001–D014), `progress.md`, `lessons-learned.md` (L001–L008), `phase-reports/{A4,A5,A6}-rapor.md` (başlıklar), mevcut kod: `agent_core/{entrypoints,errors,routing}.py`, `models/{research,sources,context,outcome,progress,enums,base,routing}.py`, `ports/{web_search,cancellation,progress,budget}.py`, `budget/{guard,policy,store}.py`, `graph/nodes.py`, `state/{state,events,artifacts}.py`, `qa/{runner,nodes,models,state,text,sufficiency}.py`, `analysis/{runner,nodes,models,state}.py`, `web/{tools,models,assess,settings,__init__}.py`, `adapters/test_doubles/*`, `tests/{conftest}.py`, `tests/{qa,web}/*`
- **Yazılan dosyalar:** yalnız izinli kapsam — `app/agent_core/research/**` (8 yeni dosya), `tests/research/**` (5 yeni dosya, `__init__.py`'li paket), `app/agent_core/entrypoints.py` (ortak dosya: research dispatch entegrasyonu, +35/−8), bu rapor. `src/contracts/**`, `app/messaging/contracts/**`, A6 web dosyaları, messaging/.NET ve tests/qa değiştirilmedi; commit/push/reset yapılmadı.

## 1. Ortam ve ön koşul doğrulaması

| Kontrol | Komut / yöntem | Sonuç |
| --- | --- | --- |
| RAG aracı bütünlüğü (L008 kontrolü) | `node docs/ai-agent-plan/source/tools/search.cjs verify` | `valid: true` (30 kaynak / 60 parça / 23 aşama) |
| A7 RAG CONTEXT | `node … search.cjs search --stage A7 --query "Derin araştırma orchestrator worker araç kullanımı ve kanıt değerlendirmesi" --format prompt` | 6 parça: [LG-WORKFLOWS#C2], [ENG-AGENTS#C1], [ENG-AGENTS#C2], [AC-SELF-RAG#C2], [AC-REACT#C2], [AC-RAG#C2] |
| Ön koşul kod okuması | A6 `web/tools.py` (`build_web_tools` "A7 graph katmanı bunu kullanır" sözleşmesi), A1 `models/research.py` (ResearchPlan/ResearchFinding), DONMUŞ `models/sources.py`, A2 `BudgetGuard`/`TaskContext`, A4/A5 graph desenleri | tamam; `ResearchPlan.sub_questions` `max_length=8`, politika `max_sub_questions=4` (asıl sınır) |
| L002 kontrolü | cmd aygıt adı/yönlendirme kullanılmadı; `git status --short` beklenmeyen untracked üretmedi (`.video_agent/`, `.zcode/`, `tests/events/` başlangıç snapshot'ında zaten vardı — bu agent'ın üretimi değil) | temiz |
| L005 kuralı | `tests/research/` `__init__.py`'li paket olarak açıldı (dispatch talimatı) | conftest.py güvenli; testler `from .conftest import …` (tests/intake B4 deseni) |
| L006 | Yazma penceresi öncesi/sonrası dosya varlığı doğrulandı; hiçbir checkout/branch işlemi yapılmadı | çakışma yok |

## 2. Oluşturulan yapı

```
app/agent_core/research/
├── __init__.py     # paket dışa açılımı (run_deep_research vb.)
├── models.py       # ClaimRecord, SourceLedgerEntry, ClaimEvidenceRecord (→ EvidenceItem daraltma),
│                   # CoverageAssessment, ComparisonNote, ResearchReport, ResearchFlowConfig, GatherTask, SupportKind
├── state.py        # ResearchState TypedDict (A4/A5 reducer deseni; merge_strings eki)
├── planning.py     # extract_claims (kod bloğu/başlık hariç cümle iddiaları) + build_sub_questions (≤ politika sınırı)
├── evaluation.py   # locate_span + classify_support (sezgisel) + build/verify_claim_evidence (programatik)
│                   # + evaluate_claims + assess_coverage
├── report.py       # strip_fabricated_sources + build_findings + build_comparison_notes + assemble_report
├── nodes.py        # validate/extract/plan/gather_worker(Send)/evaluate/coverage/compare/report/control/finalize
└── runner.py       # build_deep_research_graph + research_policy_for + run_deep_research + terminal eşleme

tests/research/     # A7 test sahipliği (L005: __init__.py'li paket, conftest güvenli)
├── __init__.py
├── conftest.py     # gerçekçi fixture'lar: localhost MockWebServer (gerçek HTTP), RoutingSearchProvider,
│                   # FixedModelProvider, CancelAfterToken, build_web_bundle (ortak BudgetStore)
├── test_research_flow.py        # 8 test: normal akış, uydurma kimlik, giriş noktası dispatch + geçiş yolu,
│                                 # config_error, ikinci tur, ilerleme, kapsam doğrulama
├── test_research_evidence.py    # 16 test: iddia çıkarma, destek sınıflaması, programatik reddetme nedenleri,
│                                 # idempotent kanıt, rapor kaynak ayıklaması
└── test_research_limitations.py # 6 test: çelişki, yetersiz kaynak (404), bütçe bitişi, baştan/sırasında iptal, sayfa bütçesi

app/agent_core/entrypoints.py     # execute_plan/resume'a `web_tools` parametresi + deep_research dispatch'i
```

## 3. Plan A7 adımlarının karşılıkları

| Plan adımı | Uygulama | Kanıt (test) |
| --- | --- | --- |
| 1. Makale ve araştırma kapsamını doğrula | `research/nodes.py:make_validate` — snapshot hash bağlantısı (A0 §7.2 sözleşmesi), K7 içerik getirme (`content` deposu), makale bağlılığı (`validation_error`), `search_web/read_source/assess_source` aracı bağı (`config_error`) | `test_research_flow.py::test_research_without_article_context_fails`, `::test_unwired_search_tool_fails_with_config_error` |
| 2. İlgili makale iddialarını çıkar | `planning.extract_claims` — deterministik cümle bölücü (kod blokları/markdown başlıkları hariç), soru terimi ilgisi A3/A4 normalizasyonuyla (`fold_text`+`salient_tokens` [ENG-CONTEXT#C1]); `claim_id = claim:{article_id}:{revision}:{n}`; aralıklar makale içi | `test_research_evidence.py::test_claim_extraction_is_bounded_and_relevant` (span↔metin birebir) |
| 3. ResearchPlan + sınırlı alt sorular (≤4) | `nodes.make_plan` — soru + iddia doğrulama soruları, `BudgetPolicy.max_sub_questions` (4) ile kırpılır; ilk tur `guard.track(RESEARCH_ROUND)` ile bütçeye yazılır | `test_research_evidence.py::test_sub_questions_are_bounded`; `test_second_round_runs_for_uncovered_claim` (tur olayları) |
| 4. Kaynak adaylarını bul/oku (A6) | `nodes.make_gather_worker` — LangGraph `Send` ile alt soru başına paralel worker [LG-WORKFLOWS#C2]; `SearchWebTool`/`ReadSourceTool` (`events_sink` ile olaylar state'e); `AssessSourceTool` tür/öncelik/kopya; sayfa metinleri `ArtifactStore`'a (state'e metin girmez); her dış deneme aracın kendi guard yolundan ORTAK bütçeye yazılır (atomik rezervasyon — paralel worker bütçeyi aşamaz) | `test_research_flow.py::test_normal_research…` (web_search_calls>0), `test_research_limitations.py::test_source_page_budget_cap_limits_reads`, `::test_budget_exhaustion…` |
| 5. İddia başına destekleyen/KARŞI çıkan kanıt | `evaluation.evaluate_claims` — iddia×kaynak matrisi; `locate_span` en çok örtüşen cümle aralığı; `classify_support` sayısal çelişki + olumsuzlama işaretleri + ortak terim eşiğiyle supports/contradicts/unclear; `ClaimEvidenceRecord` içerik adresli `evidence_id` (tekrar değerlendirme kopyasız) | `test_research_evidence.py::test_support_classification_supports_matching_text`, `::test_support_classification_flags_numeric_contradiction`, `::test_evaluate_claims_are_idempotent_on_rerun` |
| — Programatik kontrol | `evaluation.verify_claim_evidence`: (1) kaynak ID kayıt defterinde, (2) URL eşleşmesi, (3) content_hash eşleşmesi, (4) aralık sınırları, (5) aralığın kaynak metninde birebir varlığı; hatalı kayıt kanıt havuzuna GIRMEZ, hata izine düşer | `test_research_evidence.py::test_verify_rejects_fabricated_source_id`, `::test_verify_rejects_url_mismatch`, `::test_verify_rejects_span_out_of_bounds`, `::test_verify_rejects_excerpt_mismatch`, `::test_verify_rejects_content_hash_mismatch`, `::test_verify_reports_missing_source_text` |
| 6. Eksik kapsam ve çelişki değerlendirmesi | `evaluation.assess_coverage` — hiç SUPPORTS kanıtı olmayan iddialar `uncovered`; CONTRADICTS taşıyanlar `contradicted`; karşılanmayan alt sorular; kanıtsız iddia bulguya bağlanmaz, belirsizlik bölümüne düşer (plan: "çıkarılır veya belirsizleştirilir") | `test_research_limitations.py::test_contradiction_is_detected_and_reported`, `::test_insufficient_sources_yields_partial_report_without_sources` |
| 7. Bütçe varsa ikinci tur | `nodes.make_coverage` + `after_coverage` koşullu kenarı: karşılanmayan iddia metinleri düzeltilmiş sorgu olarak TEK tur daha (dedupe: verilmiş sorgular); `guard.track(RESEARCH_ROUND)` reddi (`budget_exhausted`) → `coverage.budget_note` + mevcut kanıtla rapor; tur sınırı `policy.max_research_rounds` | `test_research_flow.py::test_second_round_runs_for_uncovered_claim` (2 tur olayı), `test_research_limitations.py::test_budget_exhaustion…` (kısmi + budget_note) |
| 8. Makaleyle ve alternatiflerle karşılaştırma | `report.build_comparison_notes` (iddia başına agrees/contradicts/unclear + gerekçe) + `build_findings` (kanıtlı alt soru başına ResearchFinding; güven: ≥2 bağımsız yayıncı grubu→high, 1→medium, yok→low) | `test_research_limitations.py::test_contradiction…` (comparison.relation=contradicts) |
| 9. Rapor üretimi + iddia–kaynak eşleşme kontrolü | `nodes.make_report` — TEK MODEL_CALL, SADECE CONTEXT (yalnız doğrulanmış supports/contradicts kanıtı; bağlam veridir [LG-RAG#C2], model etiketleri kayıt defteriyle eşlenir); `nodes.make_control` — `strip_fabricated_sources` taslaktaki kayıt defteri DIŞI `[web:…]` kimliklerini ÇIKARIR ve hata izine yazar; `assemble_report` bölüm kümesi: kısa sonuç, kapsam, tarih, makaleyle ilişki, karşılaştırma, bulgular, belirsizlikler, kaynaklar, tamamlanma durumu | `test_research_flow.py::test_report_contains_no_fabricated_source_ids` (raporda kayıt defteri dışı kimlik YOK + hata izi), `::test_normal_research…` (9 bölüm kümesi + gerçek URL'ler) |
| 10. Tam/kısmi/iptal/başarısız | `runner._terminal_outcome` + `nodes.make_finalize`: tüm alt sorular kanıta bağlı ve tüm iddialar sınıflandıysa `completed`; aksi `partial` (rapor + tamamlanma notu); `CANCELLED`→`cancelled`, beklenmeyen `PortError`→`failed` (A4/A5 eşlemesi); model bütçesi biten raporda deterministik özet fallback'i | `test_research_limitations.py::test_cancellation_before_run…`, `::test_cancellation_mid_research…` (raporsuz cancelled), `::test_insufficient_sources…` (partial) |
| EvidenceItem alan kümesi | DONMUŞ `EvidenceItem`/`SourceReference` (A1) genişletİLEMEZ; A6 `record_to_evidence` deseniyle yerel `ClaimEvidenceRecord` zengin alanları taşır (claim_id, source_id, char_start/char_end aralığı, source_content_hash, destek türü, gerekçe) ve `to_evidence_item(collected_at=…)` DONMUŞ sözleşmeye daraltır | `test_research_flow.py::test_normal_research…` (to_evidence_item turu), `models.py` docstring'lerinde tasarım notu |
| "Anlamsal destek hatasız değildir" tasarım notu | `evaluation.classify_support` gerekçelerinde "sezgisel sınıflama" etiketi; `report._COMPLETION_TAIL` her raporun belirsizlik bölümüne "Kanıt destek sınıflaması sezgiseldir; hatasız doğruluk garantisi yoktur." satırını yazar; modül docstring'leri [AC-SELF-RAG#C2] ile sınırı bildirir | `test_research_evidence.py::test_support_classification_supports_matching_text` ("sezgisel" gerekçede) |
| İlerleme: yalnız kullanıcıya yararlı aşamalar | Yayınlanan türler: RESEARCH_STARTED, RESEARCH_ROUND_COMPLETED, RETRIEVAL_COMPLETED (tur özeti), GENERATION_STARTED/COMPLETED; kaynak başına olay yayılmaz | `test_research_flow.py::test_progress_publishes_only_user_useful_stages` (tür kümesi + ≤8 olay) |

## 4. Giriş noktası entegrasyonu (ortak dosya)

`entrypoints.execute_plan`/`resume` yeni `web_tools` parametresi aldı. Dispatch kuralı: `selected_mode is DEEP_RESEARCH` **ve** makaleye bağlı bağlam **ve** `web_tools is not None` → `run_deep_research` koşar ve `outcome` döner. `web_tools` verilmediğinde A5 geçiş davranışı KORUNUR (tek model çağrısı + web kullanılamazlık notu) — bunun nedeni, `tests/qa/test_a5_entrypoints.py`'deki iki A5 testinin (dosya sahipliğim dışında) `web_search` sağlayıcısı bağlıyken dahi "akış uygulanmadı" notu ve `call_count==0` beklemesidir; A7 dispatch'i yalnız A6 `build_web_tools` **araç kümesi** (search+read+assess+ayarlar) verildiğinde devreye girer. `web_search` parametresinin anlamı değişmedi (yalnız bağlantı durumu bildirimi). B6 worker wiring'i hem `web_search` hem `web_tools`'ü aynı kurulumdan geçirebilir. Kanıt: `test_entrypoint_dispatches_deep_research_when_web_tools_wired`, `test_entrypoint_keeps_legacy_note_when_web_tools_absent`; regresyon: `tests/qa` 59 passed (bkz. §5).

## 5. Doğrulama (gerçek koşumlar)

| Kapı | Komut (repo kökünden) | Sonuç |
| --- | --- | --- |
| **GATE (dispatch'te istenen)** | `python -m pytest src/services/ai-agent-service/tests/research src/services/ai-agent-service/tests/web -q` | **157 passed** (research 30 + web 127), 6.3 sn |
| Tam suite (çekirdek) | `python -m pytest src/services/ai-agent-service/tests -q --ignore=…/tests/intake --ignore=…/tests/messaging_broker --ignore=…/tests/events` | 512 passed, 1 skipped (A1'den beri bilinen skip) |
| Broker/DB bağlı paketler | `python -m pytest …/tests/intake …/tests/messaging_broker …/tests/events -q` | 44 passed (gerçek RabbitMQ 4.2.9 + scratch DB; bu fazın değişikliği bu paketlere dokunmaz, orchestror tam kapısı için ayrıca koşuldu) |
| tests/qa regresyonu (A4/A5 sözleşmeleri) | `python -m pytest tests/qa tests/research -q` (servis dizininden) | 89 passed — A5 `web kullanılamazlık` testleri A7 dispatch'iyle KIRILMADI (bkz. §4) |
| Statik kontrol | `python -m pyflakes app/agent_core/research tests/research` | 0 bulgu |
| İlk-koşumda bulunan ve düzeltilen hatalar | (1) `_norm_numbers` `rstrip("0")` "1000"→"1" indiriyordu (100≠1000 çelişkisi görünmez oluyordu) → ondalık-normalizasyon yeniden yazıldı; (2) refactor artığı `NameError: queries` → `claim_queries` eşlemesiyle düzeltildi; (3) `to_evidence_item` DONMUŞ `SourceReference` web sözleşmesinin `accessed_at` zorunluluğunu eksik veriyordu → `collected_at` kaynağa da yazılıyor; (4) modül docstring'inde `resume` maddesi yanlışlıkla silinmişti → geri getirildi | hepsi yukarıdaki koşumlarla doğrulandı |

## 6. Bulgular

| Kimlik | Severity | Yer | Bulgü | Önerilen düzeltme | Durum |
| --- | --- | --- | --- | --- | --- |
| F1 | low | `app/agent_core/web/tools.py:302` (`AssessSourceTool.assess_many`) | `assess_many(records)` tüm listeyi `others` olarak geçtiğinden her kayıt KENDİ içerik hash'iyle karşılaştırılıp `duplicate_of=kendi source_id`, `duplicate_kind=exact` olarak işaretleniyor; bu işaretle consumer'ın (`research/evaluation.evaluate_claims`) kopya süzgeci tüm kayıtları düşürürdü | `assess_many`'in `others` kümesinden kaydın kendisini çıkarması (A6 sahipliğinde tek satırlık düzeltme + test) | **AÇIK** — A6 dosyaları bu fazda kapsamı dışı; consumer tarafında workaround: worker her kaydı `others=[kendi hariç]` ile değerlendirir (`research/nodes.py:make_gather_worker` içi not). A6 sahibine devredilir |
| F2 | info | `app/agent_core/research/evaluation.py` | Destek sınıflaması kural tabanlıdır (ortak terim + sayısal çelişki + olumsuzlama işaretleri): yanlış pozitif/negatif üretebilir; planın "hatasız doğruluk garantisi yok" kaydının uygulama karşılığıdır | Model tabanlı sınıflandırma ancak gerçek sağlayıcı devredeyken değerlendirilir (plan A10 kalite ölçümleri) | Tasarım gereği; rapor/belirsizlik metniyle bildirilir |
| F3 | info | `entrypoints.execute_plan` | Paralel worker'lar aynı URL'i aynı turda iki kez okuyabilir (Send görevleri birbirinin ledger yazımını görmez); maliyet azami `max_candidates_per_query × görev sayısı` ile sınırlı, ledger hash-dedupe ile tek kanıt kümesi kalır | A8 checkpoint/collect katmanında tur arası URL seti state'ten görevlere taşınabilir | Bilinen ve sınırlandırılmış davranış |

## 7. Kullanılan kaynak kimlikleri (RAG)

[LG-WORKFLOWS#C2] (orchestrator-worker, Send, paralel sonuç birleşimi — reducer sözleşmesinin gerekçesi), [ENG-AGENTS#C1] (workflow/agent ayrımı — önceden tanımlı graph yolları seçimi), [AC-SELF-RAG#C2] (kaynak/cevap değerlendirmesinde kavramsal referans; genel modele prompt vermek yöntemi uygulamaz — sezgisel sınıflama sınırı notunun gerekçesi), [AC-REACT#C2] ve [AC-RAG#C2] (değerlendirme kapsamı: sonuçlar deney koşullarına aittir), [ENG-AGENTS#C2] (desen seçimi). Plan metni ve repo kodu asıl kayıttır; RAG parçaları tasarım gerekçesidir.

## 8. Kabul ölçütleri karşılama tablosu (plan metni)

| Plan kabul ölçütü | Durum | Kanıt |
| --- | --- | --- |
| Normal araştırma gerçekçi fixture'la çalışır | ✅ | gerçek HTTP mock sunucu + A6 araç zinciri ile `test_normal_research_completes_with_evidence_backed_report` |
| Çelişki senaryosu çalışır | ✅ | `test_contradiction_is_detected_and_reported` (100 vs 1000 sayısal çelişki → contradicted_claim_ids + rapor) |
| Yetersiz kaynak senaryosu çalışır | ✅ | `test_insufficient_sources_yields_partial_report_without_sources` (404 → partial, kaynak bölümü doğru durum bildirimi) |
| Bütçe bitişi senaryosu çalışır | ✅ | `test_budget_exhaustion_stops_research_and_reports_partial` (search/page bütçesi → partial + hata izi), `test_source_page_budget_cap_limits_reads` |
| İptal senaryosu çalışır | ✅ | `test_cancellation_before_run…` ve `test_cancellation_mid_research…` (cancelled, raporsuz) |
| Raporda uydurma kaynak ID'si BULUNMAZ | ✅ | programatik kontrol testleri (§3 tablo) + uçtan uca `test_report_contains_no_fabricated_source_ids` (model çıktısına eklenen uydurma kimlik raporda yer almaz, hata izine düşer) |
| İkinci tur bütçe varsa koşar | ✅ | `test_second_round_runs_for_uncovered_claim` (2 RESEARCH_ROUND olayı, round=2) |
| web regresyonu (gate dahil) | ✅ | tests/web 127 passed |

## 9. Sınırlar ve kapsam dışı kalanlar

- **Gerçek LLM/arama sağlayıcısı kullanılmadı:** model double'ı (`FixedModelProvider`) ve arama double'ı (`RoutingSearchProvider`) kullanıldı; HTTP katmanı gerçektir (localhost mock). Double başarısı gerçek sağlayıcı başarısı SAYILMAZ (W0 kuralı).
- **Makaleye bağlı olmayan derin araştırma** bu fazın kapsamı değildir; `web_tools` verilse bile makale bağlamı yoksa graph `validation_error` ile durur (plan: "makale merkezli").
- Checkpoint/resume kalıcılığı, worker wiring ve iptal transportu A8/B6 kapsamındadır; `resume` yalnız `web_tools`'ü geçirir.
- `RunStatus.NEEDS_INPUT` yolu derin araştırmada router fazındadır (A5); bu graph'ta ayrı yolu yoktur.

## 10. Ortam olayları

Yazma penceresi içinde paylaşılan checkout'ta dış müdahale gözlenmedi (`git status` başlangıç snapshot'ındaki kullanıcı değişiklikleri dışında temiz). `tests/intake/test_migrations_smoke.py` çalışma ağacındaki mevcut değişiklik bu agent'ın değildir; dokunulmadı.
