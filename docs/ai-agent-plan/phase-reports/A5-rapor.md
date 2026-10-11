# A5 Faz Raporu — Auto router ve analiz modu

- **Faz:** A5 (Görev türü, çalışma derinliği ve web ihtiyacını seçen router; RouteDecision alan kümesi; kurallar + belirsizlikte yapılandırılmış router modeli; analysis alt akışı; sınırlı/kayıtlı mod yükseltmesi)
- **Tarih:** 2026-10-12
- **Branch / temel:** `feature/ai-agent-integration`, başlangıç HEAD `468d83e` (A4)
- **Rol:** A5 implementasyon agent'ı
- **Okunan girdiler:** `docs/ai-agent-plan/01-agent-gelistirme-plani.md` "Aşama A5" (satır 293–323, satır satır), `main-prompt.md`, `decisions.md` (D001–D013), `progress.md`, `lessons-learned.md` (L001–L006), `phase-reports/A4-rapor.md`, mevcut kod: `agent_core/{entrypoints,routing}.py`, `models/*`, `ports/{model,budget,web_search}.py`, `budget/{policy,guard}.py`, `qa/{runner,nodes,models,state,retrieval,text,sufficiency,guardrails}.py`, `graph/nodes.py`, `adapters/test_doubles/*`, `tests/{conftest,test_entrypoints,test_models_validation,test_models_serialization}.py`, `tests/qa/*`, `messaging/contracts/payloads.py` (donuk sözleşme teyidi)
- **Yazılan dosyalar:** yalnız izinli kapsam — `app/agent_core/routing.py` (yeniden), `app/agent_core/models/{routing,enums,outcome,__init__}.py` (genişletme), `app/agent_core/entrypoints.py` (entegrasyon), `app/agent_core/analysis/**` (5 yeni dosya), `tests/routing/**` (3 yeni dosya), `tests/qa/{helpers.py + test_analysis_flow.py + test_a5_entrypoints.py}`, bu rapor. `src/contracts/**` ve `app/messaging/contracts/**` donuk kaldı; commit/push/reset yapılmadı.

## 1. Ortam ve ön koşul doğrulaması

| Kontrol | Komut / yöntem | Sonuç |
| --- | --- | --- |
| Branch | `git status` + başlangıç snapshot | `feature/ai-agent-integration` (checkout/branch/stash işlemi YAPILMADI — L006) |
| A5 ön koşulları | A1 `routing.py`, A2 `state/budget`, A4 `qa/**` kod okuması | RouteDecision iskeleti, BudgetGuard/PolicyBudgetStore, QA graph + retriever mevcut; A4 geçiş notu (F1) rapordan alındı |
| Kaynak arama | `node docs/ai-agent-plan/source/tools/search.cjs search --stage A5 --query "Soru karmaşıklığına göre mod seçimi ve koşullu yönlendirme" --format prompt` | **HATA:** `manifest JSON ve YAML aynaları farklı.` `verify` de aynı hatayı verdi (A4'teki geçici durumdan farklı olarak kalıcı) |
| Ayna hatası teşhisi | Salt-okunur node betiği: `library.cjs` `yaml()` çıktısı ile `manifest.yaml`/`stage-map.yaml` byte karşılaştırması | İçerik farkı YOK; yalnız satır sonu farkı: ayna dosyaları CRLF, üretilen beklenen LF. Neden: `core.autocrlf=true` (`.gitattributes` bu dosyalar için nötr); dosyalar izin kapsamım DIŞINDA olduğundan DÜZELTİLMEDİ |
| RAG CONTEXT üretimi | Aynı `library.cjs` `search()` fonksiyonu, ayna kontrolü atlanarak (arşive YAZMADAN) çağrıldı | `matched`; 6 parça: [LG-WORKFLOWS#C1], [LG-WORKFLOWS#C2], [LG-RAG#C1], [LG-RAG#C2], [ENG-AGENTS#C1], [ENG-AGENTS#C2] |
| L002 kontrolü | `ls D:/MrBekoXBlogApp/nul` | dosya yok; cmd aygıt adı/yönlendirmesi kullanılmadı |
| L005 kuralı | `tests/routing/` içinde conftest.py AÇILMADI | yardımcılar `routing_helpers.py` adlı BENZERSİZ adlı modülde (bkz. F3) |

## 2. Oluşturulan yapı

```
app/agent_core/
├── models/routing.py     # RouteDecision A5 alan kümesi + ModeUpgradeRecord (A1 takma adları korundu)
├── models/enums.py       # RunIntent (article_qa|summarize|explain|compare|research|general)
├── models/outcome.py     # AgentOutcome.mode_upgrades: list[ModeUpgradeRecord] = []
├── routing.py            # 7 ölçüt kural seti + belirsizlikte yapılandırılmış router modeli + profil eşleme
├── entrypoints.py        # prepare_and_route(router_model=…), analysis dispatch, yükseltme, needs_input, web notu
└── analysis/
    ├── __init__.py       # paket dışa açılımı
    ├── models.py         # AnalysisConfig, AnalysisPlan, HeadingCoverage, AnalysisRunResult
    ├── planning.py       # build_analysis_plan (başlık ayrıştırma + takip geçmişi sorgu bağlamı)
    ├── state.py          # AnalysisState TypedDict (A4 reducer deseni)
    ├── nodes.py          # plan/validate(A4 yeniden kullanım)/gather/evidence/generate/control/finalize
    └── runner.py         # build_analysis_graph + run_article_analysis + terminal eşleme

tests/routing/            # A5 test sahipliği (L005: conftest yok; BENZERSİZ modül adı)
├── routing_helpers.py    # ScriptedRouterModel/ExplodingRouterModel/FailingRouterModel + bağlam fabrikaları
├── test_routing_rules.py # 19 test (7 ölçüt + kabul senaryoları + RouteDecision sözleşmesi)
└── test_router_model.py  # 17 test (yapılandırılmış çıktı, sıkma, profil eşleme, arıza yolları)

tests/qa/
├── test_analysis_flow.py   # 9 test (başlık araması, kapsam artırma, kanıt kontrolü, bütçe)
└── test_a5_entrypoints.py  # 6 test (needs_input, kayıtlı yükseltme, web kullanılamazlık, dispatch)
```

`tests/qa/helpers.py` değişikliği: `ScriptedRetriever.top_ks` kaydı (mod-bütçe farkı kanıtı için) — mevcut davranış değişmedi.

## 3. Plan A5 maddelerinin karşılıkları

| Plan A5 maddesi | Uygulama | Kanıt (test) |
| --- | --- | --- |
| RouteDecision alanları: intent, selected_mode, source_scope, needs_web, needs_clarification, clarification_question, brief_reason, budget_profile_id | `models/routing.py` — 8 plan alanının tamamı; A1 `reason`/`requires_web_search` okuma takma adı + kurucu girdisi olarak uyumlu (JSON çıktısı yalnız A5 adları); eski checkpoint payload'ı (`reason` alanlı) da yüklenir | `test_routing_rules.py::test_route_decision_serializes_all_eight_plan_fields`, `::test_route_decision_legacy_field_names_are_accepted_but_not_serialized`, `test_router_model.py::test_prepared_run_checkpoint_roundtrips_a5_route_fields` |
| Karar ölçütleri (7 soru) | `routing.py` sinyal kümeleri: doğrudan bilgi→fast; çok bölüm→analysis; karşılaştırma/uyarlama→analysis (COMPARE); güncellik→deep_research+needs_web; alt sorular/araştırma sinyali→deep_research; açık tercih→tercihe uyulur; makale bağlamı yokluğu+kişisel bilgi eksikliği→needs_clarification | `test_routing_rules.py` (test adları ölçüt numaralarıyla işaretli) |
| Kesin durumda kural, belirsiz durumda router modeli | `_is_ambiguous` geçidi: kesin sinyaller model çağrısız; belirsiz (açık makale göndermesi + bağlam yok; sinyalsiz uzun soru) + `router_model` verildiyse `build_router_request` ile yapılandırılmış JSON önerisi [LG-WORKFLOWS#C1]; `parse_router_suggestion` doğrular | `test_router_model.py::test_confident_rule_decision_skips_router_model`, `::test_ambiguous_question_consults_router_model_and_merges_suggestion` |
| LLM limitleri DOĞRUDAN uygulanmaz; doğrulanmış politika profiline eşlenir | `RouterSuggestion` sayısal alan İÇERMEZ; modelin ürettiği limit anahtarları okunmaz; `budget_profile_id` daima `context.budget_profile.name` (sunucu onaylı profil); sıkma: `needs_web` yalnız deep_research'te, açıklama sorusu yalnız soru metniyle | `test_router_model.py::test_model_numeric_limits_are_never_applied`, `::test_model_web_suggestion_without_research_mode_is_dropped`, `::test_parse_drops_clarification_without_question_text` |
| Analysis alt akışı: başlıklara ayır, bölümleri getir, kapsamı artır, örneklerle açıkla, kanıt kontrolü | `analysis/`: `split_answer_headings` (deterministik bölücü, `MAX_ANSWER_HEADINGS=4` sınırı) → başlık başına arama → karşılıksız başlıkta TEK kapsam artırma turu (başlık+başlık sorgusu, 2×top_k) [LG-RAG#C1] → `HeadingCoverage` kanıt kontrolü (karşılıksız başlık için uydurma yok, deterministik kapsam notu) → örneklerle/başlıklar halinde üretim (SADECE CONTEXT; bağlam veri [LG-RAG#C2]) → A4 guardrails ile atıf/bağlantı kontrolü | `test_analysis_flow.py` 9 test |
| Mod farkı farklı adımlar/bütçeler | fast: A4 QA akışı, top_k=4, tek arama; analysis: başlık başına arama + kapsam artırma, top_k=6 (artırmada 12), `analysis_policy_for` araç üst sınırı `max_headings×(1+expansion)+1`; araç çağrıları guard'dan (TOOL_CALL) | `test_analysis_flow.py::test_analysis_flow_retrieves_per_heading_and_cites_sections` (top_ks=[6,6], tool_calls=3), `::test_analysis_expands_retrieval_scope_for_uncovered_heading` (top_ks son=12), `::test_analysis_budget_policy_covers_heading_steps_but_stays_under_profile` |
| Mod yükseltmesi sınırlı ve KAYITLI | `execute_plan`: fast yetersiz + çok bölümlü soru → TEK KEZ `ModeUpgradeRecord` (yalnız fast→analysis; model doğrulayıcı geri düşüş/deep'e yükseltmeyi reddeder) kaydı; `AgentOutcome.mode_upgrades` + `MODE_SELECTED` ilerleme olayı ("mod yükseltmesi") ile taşınır | `test_a5_entrypoints.py::test_fast_run_upgrades_to_analysis_once_and_records_it`, `::test_single_part_fast_run_never_upgrades_even_when_insufficient`; `test_routing_rules.py::test_mode_upgrade_record_is_bounded_to_fast_to_analysis` |
| Eksik kişisel bilgi tahminle tamamlanmaz | Router kuralı kişisel bağlam göndermelerini yakalar → `needs_clarification` + yerelleştirilmiş açık soru; `execute_plan` model çağrısı YAPMADAN `needs_input` terminali döner (`unresolved_questions` dolu) | `test_routing_rules.py::test_missing_personal_context_asks_clarification_instead_of_guessing`, `::test_english_personal_context_gets_english_clarification`; `test_a5_entrypoints.py::test_needs_clarification_run_returns_needs_input_without_model_call` |
| Web araçları bağlı değilse doğru durum | `needs_web` kararlarında (A5'te yalnız deep_research — donuk B1 değişmezi) `execute_plan` rapora yerelleştirilmiş kullanılamazlık notu ekler: bağlantısızsa "araçlar bağlı değil, özellik kullanılamıyor"; bağlantılıysa bile "araştırma akışı henüz uygulanmadı (A7), dış kanıt toplanmadı"; `web_search` portu hiç çağrılmaz | `test_a5_entrypoints.py::test_freshness_question_routes_deep_and_reports_web_unavailable`, `::test_wired_web_search_provider_is_not_called_and_flow_gap_is_disclosed` |

Kabul ölçütleri (plan metninden, L003): kısa karmaşık soru ✓ (çok bölümlü→analysis), uzun basit soru ✓ (>240 karakter tek parça fast'ta kalır; A1'in yalnız-uzunluk kuralı bilinçli değişti), güncellik sorusu ✓ (needs_web+deep_research+intent=research), açık mod tercihi ✓, eksik bağlam ✓ (needs_clarification), analiz cevabı makale kaynaklarıyla ilişkilendirilir ✓ (atıf + doğrulanmış canonical URL bölüm bağlantıları).

## 4. Tasarım kararları ve gerekçeleri

1. **`needs_web` değişmezi korundu:** B1 `AgentRunModeSelectedV1` (DONUK) "web bayrağı yalnız deep_research'te true olabilir" der; A1 doğrulayıcı testi (`tests/test_models_validation.py:148-151`, sahiplik dışı) de aynısını sabitler. Bu yüzden güncellik sorusu `deep_research` moduna yönlendirilir; fast/analysis'e web bayrağı eklenmez. A5 çıktısı: doğru kullanılamazlık bildirimi.
2. **Belirsizlik geçidi dar tutuldu:** Kesin sinyaller (tercih, seçim, araştırma, güncellik, karşılaştırma, çok bölüm, açıklama, kişisel bilgi) model çağrısız karar verir; yalnız açık makale göndermesi + bağlam yokluğu ve sinyalsiz uzun sorular modele gider. `router_model=None` iken belirsiz durumlar deterministik kuralla çözülür (geçiş davranışı; worker wiring B4'te router_model bağlanınca daralır).
3. **Uzunluk kuralının değişimi:** A1 "uzunluk > 240 → deep_research" kuralı kabul ölçütündeki "uzun basit soru"yu ihlal ediyordu; A5'te uzunluk tek başına yetmez, çok bölümlülük de aranır. `DEEP_RESEARCH_QUESTION_THRESHOLD` dışa açılımı korundu.
4. **Yükseltme tetikleyici empiriktir:** Router'da değil, yürütmede: fast QA akışı kanıt bulamadıysa (sufficiency) VE soru başlıklara ayrılıyorsa. Sınır: çalışma başına bir kayıt, yalnız fast→analysis (`ModeUpgradeRecord` doğrulayıcı); terminal sonuç ve MODE_SELECTED olayı kaydı taşır.
5. **Analysis, A4 mekanizmasını yeniden kullanır:** validate düğümü birebir `qa.nodes.make_validate`; control düğümü `qa.guardrails` (atıf seçimi ≥3 terim, atıf denetimi, canonical URL bağlantıları); yetersiz-bilgi mesajı `qa.nodes.insufficient_answer`. Yeni graph yalnız plan/gather/evidence adımlarını ekler — iki modun farkı adım ve bütçe şeklinde kalır, kaynak sözleşmesi tek olur.
6. **Kapsam artırma sınırlıdır:** `max_expansion_rounds=1`, başlık başına tek genişletme (`analysis:expand:<tur>:<başlık>` eylem kimliği — tekrar yürütmede kopya kullanım olayı üretmez), top_k iki katına çıkar.
7. **Kararlılık:** Tüm kural kararları model çağrısız ve deterministiktir; router modeli yalnız kategorik öneri üretir ve çıktısı doğrulanamıyorsa/arıza varsa (iptal hariç) kural kararına geri düşülür, gerekçe metninde belirtilir.

## 5. Gerçek test sonuçları

| Komut | Sonuç |
| --- | --- |
| `python -m pytest src/services/ai-agent-service/tests/qa src/services/ai-agent-service/tests/routing -q` (**GATE**, repo kökünden) | **95 passed** (1.46s) |
| Aynı komut ters sırayla (`tests/routing tests/qa`) | **95 passed** (0.98s) — modül adı çakışması olmadığının kanıtı |
| `python -m pytest tests -q --ignore=tests/intake` (tam regresyon) | **372 passed, 1 skipped** (83.42s) — A1/A2/A3/A4 + messaging sözleşme + state/content dahil; A4 sonrası 321 → 372 (+51) |
| `python -m pytest tests/routing -q` ve `tests/qa -q` | 36 passed / 59 passed |
| `python -m py_compile` (tüm yeni/değişen modüller) | OK |
| `grep -rn "test_doubles" app/agent_core/{routing,entrypoints}.py app/agent_core/analysis/ app/agent_core/models/` | yalnız entrypoints docstring'i (önceden var olan); üretim koda test double importu YOK |
| `grep TODO/FIXME/print(/api_key/secret` (yeni modüller) | eşleşme yok |
| `git status --short src/contracts/ app/messaging/contracts/` | boş — donuk sözleşmeler dokunulmadı |

Geliştirme sırasında yakalanan ve düzeltilen hatalar: (a) `Field` import eksikliği, (b) `tests/qa/helpers.py` ile `tests/routing/helpers.py` modül adı çakışması (tek pytest koşusunda yanlış modül çözümleniyordu → `routing_helpers.py`'e taşındı; F3), (c) yükseltilmiş analysis çalışmasının `AgentOutcome.selected_mode`'unu fast bırakması → alt akışa yükseltilmiş modu taşıyan route kopyası verildi.

## 6. Bulgular

- **F1 (orta, açık — devir): A4'ün retriever'sız makale çalışması geçiş davranışı A5'te KAPANAMADI.** Kapatmak (`config_error` terminali) A1'in sahiplik dışı testini (`tests/test_entrypoints.py::test_resume_restores_route_from_checkpoint_without_rerouting`, retriever'sız resume başarı bekler) kırar. A4-rapor.md §6 F1'deki devir yerine B4 worker wiring'i güncellendi; `execute_plan` docstring'i buna göre işaretli. Açık risk aynıdır: retriever'sız makale çalışması kanıtsız cevap üretebilir.
- **F2 (düşük, açık): `AgentOutcome.mode_upgrades` taşıma sözleşmesine henüz yansımaz.** B1 `AgentRunCompletedV1` (donuk) yükseltme kaydı alanı taşımaz; kayıt şu an ilerleme olayı + iş modelinde yaşar. Transport görünürlüğü sözleşme revizyonu gerektirir — karar orchestrator'a/kullanıcıya ait.
- **F3 (düşük, kapatıldı — ders adayı): Aynı adlı test yardımcı modülleri tek pytest koşusunda çakışıyor.** `tests/qa/helpers.py` yüklendikten sonra `tests/routing/helpers.py`'in `import helpers`'ı yanlış modüle çözümleniyordu (rootdir-relative import modu). Düzeltme: benzersiz ad (`routing_helpers.py`); her iki dizin sırasıyla da GATE yeşil. Kontrol: GATE'in iki sıra koşusu. L005'in kapsamını genişleten ders: conftest kuralının yanına "yardımcı modül adları da dizinler arası benzersiz olmalı" eklenmelidir.
- **F4 (ortam, KAPANDI — 2026-10-12 yeniden doğrulama geçişi): kaynak arşiv aynaları CRLF'e dönmüştü.** `manifest.yaml`/`stage-map.yaml` çalışma ağacında CRLF (byte-farklı), `search.cjs verify` başarısız: `manifest JSON ve YAML aynaları farklı.` Neden: `core.autocrlf=true` + dosyaya özgü `.gitattributes` kuralı yok. Bu faz için CONTEXT, arşive yazmayan salt-okunur yeniden üretimle alındı (§1). **Kapanış:** `1a09c3c` (L008) aynaları LF'e normalize edip `.gitattributes` ile korudu; yeniden doğrulama geçişi `search.cjs verify` → `valid:true` (30 kaynak/60 parça/23 aşama) ve standart `--stage A5` arama komutunu doğruladı (§10).

## 7. Ortam olayları (L006)

Aynı checkout'ta paralel çalışma sürüyor: `src/backend/**` değişiklikleri, `app/messaging/{intake,outbox,job_store,db}.py` + `migrations/`, `pyproject.toml` değişiklikleri ve `tests/intake/` bu fazda DOKUNULMADI. `tests/intake` koşusu bilgi amaçlı yapıldı: `2 failed, 9 passed, 3 errors` — paralel çalışmanın geliştirme devamı eden dosyalarından kaynaklanır, A5 değişiklikleriyle ilgisizdir (`app/messaging`'e hiç dokunulmadı) ve GATE kapsamı dışındadır. Branch/checkout/stash işlemi YAPILMADI; hiçbir commit/reset yapılmadı.

## 8. Kaynak kullanımı

`--stage A5` aramasının 6 parçası: [LG-WORKFLOWS#C1] (yönlendirme: girdi sınıflandırma + yapılandırılmış model çıktısı + koşullu geçişler → `routing.py` yapılandırılmış öneri sözleşmesi ve `analysis/runner.py` koşullu kanıt kenarı), [LG-WORKFLOWS#C2] (orchestrator–worker, Send API → başlık başına paralel arama A7'ye not; bu fazda sıralı), [LG-RAG#C1] (ilgi değerlendirme + düzenlenmiş/genişletilmiş sorgu + koşullu kenar → `analysis` gather/evidence döngüsü), [LG-RAG#C2] (bağlam veri olarak, talimat izlenmez → analysis sistem istemi), [ENG-AGENTS#C1] (basit/birleştirilebilir desenden başlama → kurallar önce, model yalnız belirsizde), [ENG-AGENTS#C2] (desen seçimi → fast/analysis/deep ayrımı). RAG aracı ayna hatası nedeniyle standart komutla alınamadı; CONTEXT aynı kütüphane kodunun salt-okunur çağrısıyla üretildi (§1, F4).

## 9. Sonraki adım

- **A6:** `WebSearchProvider`/`SourceReader` gerçekleştirimi; A5'in `web_search` parametresi ve kullanılamazlık notları A6 bağlandığında gerçek akışla değişir.
- **A7:** deep_research graph'ı; A1 legacy tek-çağrı rapor yolu A7 ile kapanır; başlık aramalarının `Send` fan-out'a taşınması (LG-WORKFLOWS#C2) orada değerlendirilir.
- **B4:** worker wiring `router_model` + `retriever`'ı zorunlu kılınca A4 F1 ve A5 geçiş davranışları kapanır; `AgentRunModeSelectedV1`/`AgentRunCompletedV1`'in A5 alanlarıyla eşlenmesi sözleşme revizyonu konusudur (F2).
- Orchestrator'a: F3 dersi için lessons-learned kaydı (yardımcı modül adı benzersizliği) ve F4 için kaynak sahibi aksiyonu önerilir.

## 10. Yeniden doğrulama eki (2026-10-12, ikinci A5 dispatch'i)

A5 implementasyonu `0a6b951` commit'iyle zaten çalışma ağacındaydı; bu geçiş sıfırdan yeniden yazmak yerine plan metnini satır satır kodla karşılaştırıp mevcut teslimi doğruladı, bozuk/eksik bulmadı ve tüm kontrolleri yeniden koştu. Çalışma ağacı `git diff HEAD --stat -- src/services/ai-agent-service/` ile boş çıktı: test edilen kod commit'lenen A5 kodudur.

| Kontrol | Komut | Sonuç |
| --- | --- | --- |
| **GATE** (repo kökünden) | `python -m pytest src/services/ai-agent-service/tests/qa src/services/ai-agent-service/tests/routing -q` | **95 passed** (0.61s) |
| Tam regresyon (intake hariç) | `python -m pytest src/services/ai-agent-service/tests -q --ignore=src/services/ai-agent-service/tests/intake` | 372 passed, 1 skipped (59.63s) |
| Tam paket (intake dahil) | `python -m pytest src/services/ai-agent-service/tests -q` | **386 passed, 1 skipped, 1 warning** (89.91s) |
| Intake (B4 sahipliği, bilgi amaçlı) | `python -m pytest src/services/ai-agent-service/tests/intake -q` | 14 passed (B4 paralel işi commit'lendi; §7'deki geçici intake kırmızıları kapandı) |
| Kaynak arşivi | `node docs/ai-agent-plan/source/tools/search.cjs verify` | `valid:true` (30 kaynak/60 parça/23 aşama) — **F4 kapandı** (`1a09c3c`, L008) |
| RAG CONTEXT (standart komut) | `node docs/ai-agent-plan/source/tools/search.cjs search --stage A5 --query "Soru karmaşıklığına göre mod seçimi ve koşullu yönlendirme" --format prompt` | prompt üretildi; parçalar: [LG-WORKFLOWS#C1], [LG-WORKFLOWS#C2], [LG-RAG#C1], [LG-RAG#C2], [ENG-AGENTS#C1], [ENG-AGENTS#C2] (§8 eşlemesi geçerli) |
| Üretim kodu saflığı | `grep -rn "test_doubles" app/agent_core/{routing,entrypoints}.py app/agent_core/analysis/ app/agent_core/models/` | yalnız entrypoints docstring'i (§5 ile aynı) |
| Donuk sözleşmeler | `git status --short src/contracts/ src/services/ai-agent-service/app/messaging/contracts/` | boş — dokunulmadı |
| Ortam | `docker ps` | blogapp-rabbitmq healthy, blogapp-postgres healthy |

Plan A5 karşılaştırması (bu geçişte yeniden yürütülen okuma): 8 RouteDecision alanı (`models/routing.py:63-73`), 7 karar ölçütü (`routing.py:208-235` sinyal sırası + `routing.py:401-449` kural kararı), kesin kural/belirsiz model ayrımı (`routing.py:277-298` `_is_ambiguous`, `routing.py:509-536` model çağrısı + sıkma), limit eşleme (`routing.py:331-343` RouterSuggestion sayısal alan yok; `budget_profile_id` daima sunucu profili), analysis alt akışı beş adımı (`analysis/nodes.py:140-183` plan/evidence, `:201-289` gather+kapsam artırma, `:78-90` SADECE CONTEXT sözleşmesi, `:399-453` kanıt/atıf kontrolü), mod farkı (`analysis/runner.py:54-62` bütçe politikası; top_k 6/12 vs fast 4), sınırlı-kayıtlı yükseltme (`models/routing.py:28-49` doğrulayıcı; `entrypoints.py:379-412` tek kayıt), tahminsiz eksik bilgi (`entrypoints.py:343-345` + `_clarification_outcome`), web kullanılamazlık durumu (`entrypoints.py:226-253`) — tümü mevcut ve testleriyle sabit. Kabul ölçütlerinin beşi + kaynak ilişkilendirmesi §3'teki testlerle kanıtlı; bu geçiş yeni kod gerektirmedi.

Açık bulgu durumu bu ekten sonra: **F1 açık** (geçiş davranışı `entrypoints.py:325-328`'de duruyor; kapanış B4 worker wiring'inde), **F2 açık** (donuk B1 taşıma sözleşmesi kararı orchestrator'a ait), **F3 kapatıldı**, **F4 kapandı**. Hiçbir commit/push/branch işlemi yapılmadı (L006).
