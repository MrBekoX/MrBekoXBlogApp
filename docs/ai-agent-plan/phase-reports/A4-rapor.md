# A4 Faz Raporu — Makale soru cevap akışı

- **Faz:** A4 (LangGraph üzerinde makaleye bağlı ilk çalışan soru-cevap akışı: bağlam doğrulama, ilgili bölüm retrieval'ı, yeterlilik değerlendirmesi, cevap üretimi, kaynak ve kapsam kontrolü, sonuç oluşturma)
- **Tarih:** 2026-10-11
- **Branch / temel:** `feature/ai-agent-integration`, başlangıç HEAD `501830e` (W2 kayıtları)
- **Rol:** A4 implementasyon agent'ı
- **Okunan girdiler:** `docs/ai-agent-plan/01-agent-gelistirme-plani.md` "Aşama A4" (satır 263–291, satır satır), `main-prompt.md`, `decisions.md` (D001–D013), `progress.md`, `lessons-learned.md` (L001–L006), mevcut kod: `entrypoints.py`, `graph/nodes.py`, `graph/runner.py`, `state/state.py`, `state/artifacts.py`, `state/events.py`, `budget/{guard,policy,store}.py`, `content/{index,retrieval,chunking,anchors,config,models}.py`, `models/*`, `ports/*`, `routing.py`, `adapters/test_doubles/*`, `tests/conftest.py`, `tests/content/fixtures.py`, `tests/test_entrypoints.py`
- **Yazılan dosyalar:** yalnız izinli kapsam — `src/services/ai-agent-service/app/agent_core/qa/**` (8 yeni dosya), `src/services/ai-agent-service/app/agent_core/entrypoints.py` (entegrasyon, izinli "ortak dosya"), `src/services/ai-agent-service/tests/qa/**` (5 yeni dosya), bu rapor. `src/contracts/**` ve `messaging/contracts/**` donuk kaldı; `models/`–`ports/` imzaları kırılmadı; commit/push yapılmadı.

## 1. Ortam ve ön koşul doğrulaması

| Kontrol | Komut | Sonuç |
| --- | --- | --- |
| Branch | `git branch --show-current` | `feature/ai-agent-integration` |
| Python | suite koşusu | Python 3.13.9 ortamı (W2 kaydıyla aynı) |
| A4 ön koşulları | A2 (`state`, `graph`, `budget`) + A3 (`content`) + A1 (`models`, `ports`, `entrypoints`) kod okuması | graph yürütücü, BudgetGuard/TaskContext, InMemoryContentIndex, ContentRepository/ModelProvider portları ve test double'lar mevcut |
| Kaynak arama | `node docs/ai-agent-plan/source/tools/search.cjs search --stage A4 --query "Makale sorusuna CONTEXT kaynaklarıyla cevap ve retrieval yeterliliği" --format prompt` | İlk denemede `manifest JSON ve YAML aynaları farklı` hatası (geçici, L006 paralel çalışma penceresi); `search.cjs verify` `valid:true` (30 kaynak/60 parça) sonrası aynı komut CONTEXT döndürdü: [LG-RAG#C1], [LG-RAG#C2], [ENG-CONTEXT#C1], [AC-SELF-RAG#C1], [AC-LOST-MIDDLE#C1], [AC-LOST-MIDDLE#C2] |
| L002 kontrolü | cmd aygıt adı/yönlendirmesi kullanılmadı | repo kökünde `nul` yok |
| L005 kuralı | `ls tests/qa/` | `conftest.py` AÇILMADI; yardımcılar `tests/qa/helpers.py` adlı modülde |

## 2. Oluşturulan paket yapısı

```
app/agent_core/qa/
├── __init__.py       # paket dışa açılımı (run_article_qa, SnapshotRetriever, ...)
├── models.py         # QaFlowConfig, SufficiencyVerdict, QaSectionRef, QaRunResult
├── text.py           # salient_tokens, genel-soru sınıfı, sorgu kurulum/düzenleme, seçim ilişkisi
├── sufficiency.py    # evaluate_sufficiency: deterministik yeterlilik kararı
├── guardrails.py     # atıf seçimi, atıf denetimi, bölüm bağlantıları, kaynak bloğu
├── retrieval.py      # ArticleRetriever portu + SnapshotRetriever (A3 indeks üstünde)
├── state.py          # QaState TypedDict + merge_chunks reducer'ı
├── nodes.py          # altı node: validate, retrieve, evaluate, generate, control, finalize
└── runner.py         # build_article_qa_graph + run_article_qa + terminal eşleme

tests/qa/             # A4 test sahipliği (L005: conftest yok)
├── helpers.py            # ortak fixture/double'lar (öz-yeterli, başka dizinden import edilmez)
├── test_qa_text.py       # 14 test
├── test_qa_guardrails.py # 11 test
├── test_qa_flow.py       # 14 test (kabul senaryoları)
└── test_qa_entrypoints.py# 5 test (A1/A4 entegrasyonu)
```

`entrypoints.py` değişikliği (+49/−4 satır): `execute_plan`/`resume` `retriever` ve `content` bağımlılıklarını kabul eder; makaleye bağlı fast/analysis çalışması **retriever verildiğinde** A4 QA graph'ını yürütür. Derin araştırma ve makalesiz akışlar A1 tek-çağrı yolunda kalır.

## 3. Plan A4 maddelerinin karşılıkları

| Plan A4 maddesi | Uygulama | Kanıt (test) |
| --- | --- | --- |
| Node: bağlam doğrulama | `nodes.make_validate`: snapshot hash bağlantısı yeniden hesaplanır (A0 §7.2 sözleşmesi, `entrypoints.verify_snapshot_binding` ile aynı); yalnız referanslı bağlam (K7) `ContentRepository`'den getirilip revizyon/hash'e karşı doğrulanır; `selected_text` makale içeriğiyle boşluk-normalize üyelik denetimi yapılır | `test_qa_flow.py::test_inaccessible_article_fails_with_not_found`, `::test_reference_only_context_fetches_article_through_repository`, `::test_invalid_selection_is_excluded_and_disclosed` |
| Node: ilgili bölüm retrieval'ı | `nodes.make_retrieve`: `ArticleRetriever` (yeni port, A3 `InMemoryContentIndex` üstünde `SnapshotRetriever` gerçekleştirimı); makale filtresi skorlamadan önce (A3); **revizyon savunma filtresi** bağlam revizyonundan eski kanıtı state'e sokmaz; çağrılar `TaskContext.guarded` ile TOOL_CALL bütçesinde; genel (ana fikir) sorularda başlık çapalı arama | `test_qa_flow.py::test_specific_section_cites_section_and_verified_anchor_link`, `::test_evidence_from_older_revision_is_rejected_even_if_retriever_returns_it`, `::test_new_revision_replaces_old_evidence_and_citations` |
| Node: yeterlilik değerlendirmesi | `sufficiency.evaluate_sufficiency`: genel sorular (ana fikir/özet sınıfı, `text.is_generic_question`) getirilen her bölümü kanıt sayar; belirli sorular soru terimlerinin bölüm içeriğiyle örtüşmesini ister; karar deterministiktir, model tabanlı derecelendirme için yer [AC-SELF-RAG#C1] bırakılmıştır | `test_qa_text.py::test_generic_question_is_satisfied_by_any_retrieved_section`, `::test_specific_question_without_any_support_is_insufficient` |
| Sınırlı sorgu düzenleme | `nodes.make_evaluate` + `after_evaluate` koşullu graph kenarı [LG-RAG#C1]: yetersizlikte TEK düzenleme denemesi (`QaFlowConfig.max_retrieval_attempts=2`); düzenlenmiş sorgu sorunun kendi terimlerine odaklanır; yine yetersizse ikinci arama yapılmaz | `test_qa_flow.py::test_followup_uses_history_for_retrieval_but_not_as_source` (2 arama), `::test_question_absent_from_article_reports_insufficiency_without_citations` (en fazla 2 arama, model çağrısı 0) |
| Node: cevap üretimi | `nodes.make_generate`: ortak prompt kuralları (SADECE CONTEXT, yetersizlikte belirtme, kaynak gösterme); sistem istemi bağlamı **veri** olarak ele alır, içindeki talimatları uygulamaz, web aramasını yasaklar [LG-RAG#C2]; cevap kullanıcının dilinde ister; MODEL_CALL guard'lı | `test_qa_flow.py::test_injected_instruction_cannot_change_tool_policy`, `::test_english_question_receives_answer_in_english` |
| Node: kaynak ve kapsam kontrolü | `nodes.make_control`: atıflar yalnız getirilen kanıt kayıtlarından, cevapla ≥3 anlamlı terim paylaşanlardan seçilir (`select_citations`); "makaleye/yazara göre" kalıbıyla yapılmış ve kanıtla desteklenmeyen cümle cevaptan çıkarılır (`neutralize_attributions`) — makalede olmayan görüş yazara atfedilemez; bölüm bağlantıları indeks kaydının canonical URL'sinden (doğrulanmış URL şablonu + A3 anchor) üretilir | `test_qa_guardrails.py` (11 test), `test_qa_flow.py::test_main_idea_question_grounds_answer_in_article` (URL `#python-tip-ipuclari`), `::test_specific_section_...` (URL `#kuyruk-siniri`) |
| Node: sonuç oluşturma | `nodes.make_finalize`: terminal `AgentOutcome` (status=completed, source_scope=article, atıflar, kullanım kaydı) + asistan mesajı; yetersizlikte deterministik yetersiz-bilgi yanıtı (model çağrısı yok, atıf yok, kullanıcının dilinde) | `test_qa_flow.py::test_question_absent_from_article_reports_insufficiency_without_citations` |
| Takip soruları tamamlanmış geçmişi kullanır | `text.build_retrieval_query`: soruda geçmeyen geçmiş terimleri arama sorgusuna taşınır (kanıt olarak değil); prompt'ta geçmiş ayrı blokta, "doğrulanmış kaynak değildir" etiketiyle | `test_qa_text.py::test_followup_query_absorbs_history_terms_missing_from_question`, `test_qa_flow.py::test_followup_uses_history_for_retrieval_but_not_as_source` |
| Önceki model cevabı kaynak yerine konmaz | Atıflar yapısal olarak yalnız `IndexedChunk`'lardan kurulur; konuşma turları CONTEXT bloğuna girmez | `test_qa_flow.py::test_followup_uses_history_for_retrieval_but_not_as_source` |
| Makale/revizyon değişimi dikkate alınır | İndeksleme idempotent (A3): yeni revizyon atomik değişir; retrieve düğümü bayat revizyon kayıtlarını reddeder; atıf revizyonu bağlam revizyonudur | `test_qa_flow.py::test_new_revision_replaces_old_evidence_and_citations`, `::test_evidence_from_older_revision_is_rejected_even_if_retriever_returns_it` |
| Bu aşamada web araçları çalıştırılmaz | `run_article_qa` bağımlılık kümesinde web portu YOKTUR (yapısal garanti); `usage.web_search_calls == 0` testle kanıtlı | `test_qa_flow.py::test_injected_instruction_cannot_change_tool_policy`, `::test_main_idea_question_grounds_answer_in_article` |
| Kaynak içindeki talimat araç politikasını değiştiremez | Enjeksiyon cümlesi makale bölümüne gömülü: akış tamamlanır, web çağrısı 0, cevap değişmez, atıflar kanıt alt kümesi kalır; sistem istemi bağlam-veri kuralını taşır [LG-RAG#C2] | `test_qa_flow.py::test_injected_instruction_cannot_change_tool_policy` |

Kabul ölçütlerinin tamamı plan metninden karşılaştırıldı (L003): ana fikir ✓, belirli bölüm ✓, kod açıklaması ✓ (kod çiti bütün getirilir, `test_code_explanation_cites_intact_code_chunk`), takip sorusu ✓, makalede karşılığı olmayan soru ✓, geçersiz seçim ✓ (`selected_text_ok=False` + cevapta bildirim + prompt'tan çıkarım), erişilemeyen içerik ✓ (`not_found`/`config_error` terminal), enjeksiyon ✓.

## 4. Tasarım kararları ve gerekçeleri

1. **Ayrı QA graph'ı, A2 `ResearchEffects` yerine:** A2 graph'ı derin araştırma şeklindedir (plan→subtask→collect→finalize); A4'ün altı sorumluluğu retrieval-yeterlilik döngüsü içerir ve koşullu kenarla kurulur [LG-RAG#C1]. `QaState`, A2 `AgentState` reducer desenini (merge_by_id, merge_messages) yeniden kullanır. Yürütme mekaniği (TaskContext, guard, terminal eşleme) A2'den ödünç alınır.
2. **Deterministik yeterlilik/atıf kararları:** Gerçek LLM olmadan bu fazın kabul ölçütleri ancak deterministik kurallarla kanıtlanabilir. Yeterlilik (lexikal örtüşme + genel-soru sınıfı) ve atıf seçimi (≥3 anlamlı ortak terim) `agent_core.qa` içinde sınıflandırılmıştır; gerçek model tabanlı derecelendirme devreye girdiğinde bu modüllerin yerine geçer ([AC-SELF-RAG#C1] yöntem referansı).
3. **Genel-soru sınıfı:** "Ana fikir" soruları makale terimi taşımadığından terim örtüşmesiyle yetersiz çıkar; bu sınıf için getirilen her bölüm kanıt sayılır ve arama başlık çapasıyla yapılır. Böylece "ana fikir" kabul ölçütü uydurma atıf olmadan çalışır.
4. **Atıf eşiği 3:** Varsayılan 2 iken kod çiti işaretinin (```` ```python ````) ürettiği "python" belirteci yanlış atıf verdiği gözlemlendi (test koşusunda kanıtlandı); eşik 3'e çekildi ve gerekçe `QaFlowConfig.min_citation_overlap` yorumuna yazıldı.
5. **Yetersizlikte model çağrısı yok:** Uydurma cevabın yapısal yolu kapatılır: yetersiz kararından sonra generate düğümüne kenar yoktur; deterministik mesaj kullanıcının dilinde üretilir, `citations=[]`.
6. **Bütçe eşlemesi:** Yerel bölüm araması ve idempotent indeksleme TOOL_CALL türünde guard'dan geçer; `qa_policy_for` profilin `max_tool_calls=0` tercihini WEB araçlarına ayırır ve akışın iç ihtiyacını (`max_retrieval_attempts + 1`) ayırır. Model/token/süre sınırları profili aynen uygular.
7. **QA state checkpoint'siz:** Seriye atma A8 checkpoint katmanıyla birlikte ele alınır; `QaState` tüm alanlarıyla graph içi seriyadır (BusinessModel/basit tipler).

## 5. Gerçek test sonuçları

| Komut | Sonuç |
| --- | --- |
| `python -m pytest src/services/ai-agent-service/tests/qa -q` (**faz kapısı**, son koşu) | **44 passed** (0.45s) |
| `python -m pytest src/services/ai-agent-service/tests -q --ignore=src/services/ai-agent-service/tests/intake` | **321 passed, 1 skipped** (75.31s) — A1/A2/A3/messaging contract/regresyon dahil |
| `python -m py_compile` (tüm yeni dosyalar) | OK |
| `grep -rn test_doubles app/agent_core/qa/` | eşleşme yok — üretim kodu test double importu yasak kuralı |
| `grep print(/TODO/FIXME/secret` (yeni modüller) | eşleşme yok |

Not: Geliştirme sırasında aynı komutlar önce `18 failed → ... → 44 passed` seyretti; düzeltmeler: (a) node fabrikaları `async def` → `def` (A2 deseni; coroutine graph node'u verilmişti), (b) `usage_record_from_events` eksik importu, (c) genel-soru sinyallerinin katlanmış karşılaştırması, (d) atıf eşiği 3. Tümü yukarıdaki final koşularla doğrulandı.

## 6. Bulgular

- **F1 (orta, kapatıldı) — retriever'sız makale çalışması A1 testini kırıyordu.** `entrypoints.execute_plan`'e QA yolunu zorunlu kılan ilk kurgu (`retriever` yoksa `config_error` terminal), A1'in `tests/test_entrypoints.py::test_resume_restores_route_from_checkpoint_without_rerouting` testini (makale bağlamlı çalışmayı retriever'sız resume eder) bozdu; tam suite koşusunda `1 failed` olarak görüldü. Test dosyası A4 dosya sahipliği DIŞINDA olduğundan kod tarafında geçiş davranışı seçildi: `retriever` verildiğinde QA yolu, verilmediğinde A1 tek-çağrı yolu. **Açık risk:** retriever'sız makale bağlamlı çalışma kanıtsız (atıfsız) cevap üretebilir — bu geçiş davranışıdır; A5 worker wiring'i `retriever`'ı zorunlu kılınca `config_error` terminaline dönülmelidir (`entrypoints.py` docstring'inde ve `test_qa_entrypoints.py::test_execute_plan_without_retriever_keeps_legacy_path_transitionally` içinde işaretli).
- **F2 (düşük, kabul) — atıf seçimi lexikaldır:** Model cevabı bölüm terimlerini taşımayan özdeyişler üreterek atıfsız kalabilir (yanlış-negatif yönü güvenlidir; getirilmemiş kaynak asla atıf olamaz). Gerçek sağlayıcı devreye girdiğinde model tabanlı kaynak işaretlemesi değerlendirilmelidir.
- **F3 (düşük, açık) — [AC-LOST-MIDDLE#C1/#C2] konum etkisi:** Getirilen bölümler prompt'ta arama sırasıyla verilir; bilgi konumuna duyarlılık bu fazda ölçülmedi. A5/A7 değerlendirme aşamalarında ölçüm konusu.

## 7. Ortam olayları (L006)

Faz boyunca aynı checkout'ta paralel çalışma gözlendi ve DOKUNULMADI: `src/backend/**` değişiklikleri, `app/messaging/{intake,outbox,job_store,db}.py` + `migrations/` yeni dosyaları, `pyproject.toml` ve `app/messaging/__init__.py` değişiklikleri, yeni `tests/intake/` dizini. `tests/intake` 14 test şu an ERROR vermektedir (`RuntimeError: This event loop is already running`) — bu hatalar paralel çalışmanın geliştirme devamı eden dosyalarından kaynaklanır, A4 değişiklikleriyle ilgisizdir (A4 öncesi bu dizin yoktu; A4 kapsamı `tests/qa` kapısı + intake hariç tam suite ile doğrulandı). Bir arama komutu ilk denemede geçici `manifest JSON ve YAML aynaları farklı` hatası verdi; `verify` `valid:true` sonrası aynı komut başarılı oldu. Branch/checkout/stash işlemi YAPILMADI.

## 8. Kaynak kullanımı

`search.cjs search --stage A4` çıktısındaki parçalar: [LG-RAG#C1] (ilgi değerlendirmesi + düzenlenmiş sorgu + koşullu kenarlar → `qa/nodes.py` evaluate/retrieve döngüsü), [LG-RAG#C2] (bağlam veri olarak, talimat izlenmez, bilinmiyorsa belirtilir → sistem istemi ve guardrails), [ENG-CONTEXT#C1] (ilgili bilgiyi gerektiğinde getirme → A3 normalizasyonuyla aynı terim çıkarmı), [AC-SELF-RAG#C1] (yansımalı derecelendirme → `sufficiency.py` gelecek genişleme noktası), [AC-LOST-MIDDLE#C1/#C2] (konum etkisi → F3, ölçüm A5/A7'de).

## 9. Sonraki adım

- A5: `RouteDecision` alanlarının tamamlanması ve worker wiring'inde `retriever`'ın zorunlu kılınması (F1 geçiş davranışının kapatılması).
- B3/B4 (paralel sahiplik): intake/outbox hattı; A4 QA graph'ı `execute_plan` üzerinden transport'a bağlanacak.
