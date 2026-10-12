# A9 Faz Raporu — Site rehberliğini ve iş birliği hazırlığını ekle

Tarih: 2026-10-12 · Faz: A9 (W6) · Branch: `feature/ai-agent-integration`
Sorumlu: A9 implementasyon agent'ı (site rehberliği ve iş birliği hazırlığı)
Plan kaynağı: `docs/ai-agent-plan/01-agent-gelistirme-plani.md` "Aşama A9" (satır 413–445), plan metni asıl alınmıştır (L003).

## 1. Ortam ve ön koşul doğrulaması

- RAG aracı faz başında doğrulandı: `node docs/ai-agent-plan/source/tools/search.cjs verify` → `"valid": true, "sources": 30, "chunks": 60, "stages": 23` (L008 kontrolü; faz sonunda tekrar koşuldu, aynı sonuç).
- A9 CONTEXT'i alındı: `search.cjs search --stage A9 --query "İş birliği teklifinde interrupt onay ve resume" --format prompt` → [LG-INTERRUPTS#C1] (interrupt kalıcı checkpointer + kararlı thread_id + resume girdisiyle aynı yürütmenin sürdürülmesi), [LG-INTERRUPTS#C2] (devam eden node baştan çalışır → yan etkiler yeniden yürütmeye dayanıklı tasarlanmalı). İkinci sorgu "agent tasarım ilkeleri" → [ENG-AGENTS#C1] (basit, birleştirilebilir desenlerden başlama), [ENG-AGENTS#C2] (routing deseni; araç arayüzlerinin anlaşılırlığı).
- Okunan plan/karar dosyaları: main-prompt.md, decisions.md (D001–D016), progress.md, lessons-learned.md (L001–L009), plan A9 bölümü, haberleşme planı B9 bölümü (sınır hizalaması), B1 `agent.action.proposed/result` sözleşme şemaları.
- Üzerine kurulduğu doğrulanan fazlar: A5 router (`routing.py` kural seti), A8 checkpoint (`save_checkpoint`/`load_resume_payload` zarf sözleşmeleri), B5 `ProgressKind.ACTION_PROPOSED` olay türü (enums'ta hazır bekliyordu, ilk kez bu fazda yayınlanıyor).

## 2. Gerçek veri kararı (uydurma yasağının somut karşılığı)

Dispatch'in gerçek veri kararı uygulanarak onaylı statik kayıtlar yalnız repo içi GERÇEK kaynaklardan derlendi (`app/agent_core/adapters/static_records.py` modül docstring'i kaynakları satır düzeyinde listeler):

| Kaynak dosya | Kullanılan gerçek değerler |
| --- | --- |
| `src/frontend/blogapp-web/src/lib/site-config.ts` | `AUTHOR_NAME`="Berkay Kaplan", `AUTHOR_JOB_TITLE`="Software Developer", `AUTHOR_DESCRIPTION`, `SITE_URL`="https://mrbekox.dev", `GITHUB_URL`, `TWITTER_URL`, `LINKEDIN_URL`, `SITE_KEYWORDS` (18 yetkinlik) |
| `src/backend/Presentation/API/Seo/SeoDocuments.cs:18-21` | `SiteName`, `AuthorName`, `SiteDescription` |
| `README.md:3,92-129` | platform tanım cümlesi, teknoloji yığını (.NET 10, Next.js 16, PostgreSQL, RabbitMQ, LangGraph…) |
| `docs/ai-agent-plan/main-prompt.md:13-15` | repo (`github.com/MrBekoX/MrBekoXBlogApp`) ve site URL'leri |
| `decisions.md` (D012) + B2 raporu | BuildingBlocks.Messaging açıklaması |

- **Bilinçli eksikler:** deneyim süresi, ücret/fiyat, müsaitlik repoda hiçbir kaynakta bulunmadığından kayıtlarda TUTULMAZ; bu alanlara soru geldiğinde `guidance.detect_missing_info_fields` yakalar ve akış `needs_input` ile dürüstçe durur (`test_profile_record_contains_no_invented_missing_info` kayıt düzeyinde sabitler, `test_missing_experience_is_reported_and_never_invented` cevap düzeyinde kanıtlar).
- **Proje rehberi kapsamı:** MrBekoXBlogApp + repo içi gerçek projeler (ai-agent-service, BuildingBlocks.Messaging) — dispatch kuralı gereği.
- **Makale önerisi kataloğu (`APPROVED_ARTICLE_CATALOG`):** repoda gerçek yayınlanmış makale listesi YOKTUR; uydurma kayıt girilmedi, katalog boş bırakıldı. Öneri motoru çağıranın verdiği onaylı `ArticleCatalogEntry` listesiyle çalışır; boş katalogta dürüst `partial` "kullanılamaz" sonucu döner (A5 web-kullanılamazlık deseninin aynısı). B8 içerik senkronu bağlandığında katalog gerçek içerikle beslenir — motor değişmez.

## 3. Oluşturulan/Değişen yapı

| Dosya | İçerik |
| --- | --- |
| `app/agent_core/guidance/__init__.py` + `models.py` + `compose.py` + `runner.py` | Rehberlik paketi: `ArticleCatalogEntry`/`ArticleSuggestion`/`MissingInfoField` yerel iş modelleri; onaylı kayıttan deterministik tr/en kompozisyon (`compose_profile_answer`, `compose_projects_answer`, `suggest_articles` — kısa uygunluk gerekçesi + kaynak bağlantısı); `run_guidance` (model çağrısı YOK; port hataları dürüst terminale; bağlı olmayan onaylı kaynak `config_error`, kayıtsız model yoluna DÜŞÜLMEZ) |
| `app/agent_core/collab/__init__.py` + `models.py` + `extract.py` + `proposal.py` + `runner.py` | İş birliği paketi: `CollaborationDetails`/`CollaborationState` (COLLAB_STATE_SCHEMA_VERSION=1)/`CollabResumeInput`; deterministik tr/en çıkarım (amaç kategorisi, kapsam, takvim, opsiyonel bütçe, iletişim; çıkarılamayan alan TAHMİN EDİLMEZ); içerik hash'li `ActionProposal` üretimi; durum makinesi `run_collaboration` |
| `app/agent_core/adapters/static_records.py` | `StaticProfileRepository`/`StaticProjectRepository` (gerçek adaptör, `is_test_double=False`, port Protocol uyumlu; kopya döner) + `APPROVED_PROFILE`/`APPROVED_PROJECTS`/`APPROVED_ARTICLE_CATALOG` |
| `app/agent_core/models/enums.py` | **Additive**: `RunIntent.PROFILE/PROJECTS/CONTENT_SUGGESTION/COLLABORATION` (donuk sözleşmelerde `intent` değeri geçmiyor — `src/contracts` ve backend grep'i boş; mevcut üyeler değişmedi) |
| `app/agent_core/routing.py` | **Additive**: 4 sinyal kümesi (fold_text kuralıyla katlanmış biçimde), `classify_guidance_intent`, `GUIDANCE_INTENTS`; `_intent_for`'a genel-soru sonrası bağlama (kişisel bağlam sinyali ÖNDE — "Benim projemde…" rehberliğe gitmez); AUTO tercihte mod FAST'a sabitleme + niyet gerekçesi + `source_scope` eşlemesi (PROFILE/PROJECTS/GENERAL); `_is_ambiguous`'ta bu niyetler kesin karar sınıfı (router modeline danışılmaz); `_merge_suggestion` kapsam eşlemesi |
| `app/agent_core/entrypoints.py` | **Additive**: `PreparedRun.collab_state`, `ResumeRequest.collab_input`/`validated_result`; `execute_plan`'a 6 seçime bağlı kwarg + intent güdümlü 2 dal (rehberlik/iş birliği); iş birliği dalı checkpoint'siz `config_error`, `needs_input`'ta PreparedRun'ı A8 zarfıyla `prepared:run` kimliğine yeniden yazar; `resume` girdileri geçirir |
| `app/agent_core/adapters/__init__.py` | Statik adaptör dışa aktarımları (separation testi kuralı korunur: kökte test double yok) |
| `tests/guidance/` | `__init__.py`'li paket (L005); 9 dosya, 66 test, kendi conftest'i |

## 4. Plan A9 yapılacakların karşılıkları

| Plan maddesi | Karşılık |
| --- | --- |
| ProfileRepository/ProjectRepository onaylı kayıtları | `StaticProfileRepository`/`StaticProjectRepository` (§2 kaynak tablosu); test double DEĞİL |
| Proje amacı, teknolojiler, katkı, doğrulanmış bağlantılar | `compose_projects_answer`: kayıt başına açıklama (README'den amaç; "repo sahibi tarafından geliştirilmektedir" katkı cümlesi), teknolojiler, `links` kayıttan aynen |
| Eksik deneyim/ücret/müsaitlik uydurulmaz | Alanlar kayıtlarda yok; soru sinyali → `needs_input` + "tahminle doldurulmaz" notu; cevapta "N yıl" kalıbı testle yasaklanır |
| İlgiye göre makale önerisi: kısa gerekçe + kaynak bağlantısı | `suggest_articles` + `ArticleSuggestion.relevance_reason` (yalnız girdi konularından: "eşleşen konular: …") + `url` girdiden aynen; kataloğu olmayan çalışmada uydurma yok |
| Türkçe ve İngilizce cevap | Tüm kompozisyonlar `language` güdümlü çift şablon; `test_language_switch.py` 3 senaryo |
| Amaç/kapsam/takvim/opsiyonel bütçe/iletişim çıkarımı | `extract.py`: kapalı küme amaç sinyalleri, tırnak/"hakkında"/makale-başlığı kapsamı, ISO/süre/adli takvim, bütçe yalnız geçiyorsa ("yok" → None), e-posta/iletişim ifadesi |
| Gerekli eksik alanları KISA sorularla tamamlama | `questions_for_missing_fields`: zorunlu alan başına 1 kısa soru (bütçe sorulmaz); `answers` ile resume'da tamamlanır (bilinmeyen alan `validation_error`) |
| Düzenlenebilir özet + içerik hash'li ActionProposal | `build_collab_proposal`: `summary` (düzenlenebilir) + `proposed_content`; `base_content_hash` makale revizyonunu, ayrıca öneri METNİNİN SHA-256'sı (`proposal_content_hash`) onay SÜRÜMÜNÜ sabitler (B9 "belirli proposal sürümü" bağı) |
| needs_input'ta dur + checkpoint'i sakla (A8) | `execute_plan` iş birliği dalı: her adımdan sonra güncel `PreparedRun` (`collab_state` dâhil) `save_checkpoint(kind=PREPARED, "prepared:run", execution_id)` ile yazılır; checkpoint'siz çalışma `config_error` ile reddedilir (saklama sözleşmenin parçası); restart benzetimi testli |
| Devam girdisinde doğrulanmış onay/sürüm veya düzenleme işleme | Onay: `approved_proposal_id` (checkpoint'tekiyle eşleşmek zorunda) + isteğe bağlı `approved_content_hash` (sürüm; eski hash red) VEYA yalnız backend `ValidatedActionResult` (proposal_id/run_id bağlamı checkpoint'e karşı denetlenir — B9 `AgentActionResultV1` sözleşmesi); düzenleme: `edited_summary/edited_proposed_content` → YENİ proposal kimliği + yeni içerik hash'i (yeni sürüm) |
| Gerçek kayıt sonucunu ValidatedActionResult ile alma | `run_collaboration(validated_result=...)`: `accepted` → başarı; `rejected` → "KAYDEDİLMEDİ + gerekçe"; sonucun proposal/run bağlamı uyuşmazsa `validation_error` |
| Başarıyı yalnız doğrulanmış işlem sonucundan sonra bildirme | Sonuçsuz onay `validation_error` ("backend kayıt sonucu olmadan graph sürdürülmez"); "kaydedildi" metni YALNIZ `outcome=="accepted"` dalında üretilir (`test_rejection_is_reported_honestly_without_success_claim`) |

## 5. Router ve giriş noktası entegrasyonu (imza kırılmadan)

- `routing.py`: mevcut A5 karar yolları (tercih/araştırma/güncellik/çok bölüm/karşılaştırma/açıklama) korunur — `tests/routing` 33 test yeşil; rehberlik sınıflaması genel-soru kontrolünden SONRA ve kişisel bağlam EZEREN koşulla eklenir; `decide_mode` imzası değişmedi.
- `entrypoints.py`: `prepare_and_route` imzası değişmedi; `execute_plan`/`resume` yalnız seçime bağlı kwarg aldı; mevcut QA/analysis/research dalları ve `needs_clarification` önceliği aynı satırda kaldı.
- A5 desen hizası: profil/proje/öneri/iş birliği niyetleri kesin karar sınıfıdır — `ExplodingModelProvider` ile "model çağrısı yapmaz" kanıtlanır (`test_profile_intro_answered_from_approved_record_without_model`, `test_guidance_questions_never_consult_router_model`, checkpoint testinde 3 resume boyunca `call_count==0`).
- `ProgressKind.ACTION_PROPOSED` (B5'te tanımlı, kullanılmayı bekliyordu) ilk kez yayınlanır: öneri üretiminde `action_proposed` ilerleme olayı (testli).

## 6. Doğrulama (gerçek koşumlar)

Komutlar depo kökünden, sırayla:

```
python -m pytest src/services/ai-agent-service/tests/guidance -q
→ 66 passed in 0.31s

python -m pytest src/services/ai-agent-service/tests -q \
  --ignore=src/services/ai-agent-service/tests/messaging_broker \
  --ignore=src/services/ai-agent-service/tests/intake \
  --ignore=src/services/ai-agent-service/tests/events \
  --ignore=src/services/ai-agent-service/tests/worker \
  --ignore=src/services/ai-agent-service/tests/control \
  --ignore=src/services/ai-agent-service/tests/content_sync
→ 626 passed, 1 skipped, 1 warning in 18.75s
```

- Faz kapısı 66 testin dağılımı: profil davranışı 5 (onaylı cevap/eksik deneyim/ücret+müsaitlik/bağlı olmayan depo/port arızası), proje rehberi 5, makale önerisi 5, dil değişimi 3, çıkarım 8, iş birliği durum makinesi 15, checkpoint+resume entegrasyonu 3, router A9 bağları 10, statik kayıt/kaynak doğrulaması 8 (+ konfigürasyon).
- Tam regresyonda (A8 koşumunda 553) mevcut davranışlar yeşil: `tests/routing` (33), `tests/test_entrypoints.py`, `tests/state`, `tests/checkpoint`, `tests/qa`, `tests/research`, `tests/web`, `tests/content`, `tests/integration` — imza kırılması yok. +7 test farkı önceki koşumlara göre paralel fazların çalışma ağacına eklediği testlerden gelir (bu fazın değişikliği değil).
- Tek uyarı önceden mevcut Alembic `path_separator` DeprecationWarning'idir (`tests/integration/test_cancel_fencing_integration.py::test_real_migration_schema_is_in_effect`); bu fazın değişikliğiyle ilgisiz.
- Broker testleri bu fazın kapısında DEĞİLDİR (dispatch kuralı, L009); koşulmadı. `messaging.worker`/`messaging.events` import'u additive değişikliklerle doğrulandı (`import messaging.worker` → OK).

## 7. Kabul ölçütleri senaryoları (plan metni) → kanıt

| Senaryo (plan: "profil, eksik bilgi, proje rehberi, öneri, dil değişimi, talep düzenleme ve onay bekleyen state test edilir") | Test |
| --- | --- |
| Profil | `test_profile_intro_answered_from_approved_record_without_model` — onaylı kayıttan tr cevap; isim/bağlantılar kaynak değerleriyle |
| Eksik bilgi | `test_missing_experience_is_reported_and_never_invented`, `test_rate_and_availability_questions_report_missing` — needs_input + uydurma yasağı (regex ile "N yıl" yasağı) |
| Proje rehberi | `test_real_projects_listed_with_technologies_and_verified_links` — 3 gerçek repo projesi, teknoloji + doğrulanmış bağlantılar; `test_no_matching_interest_lists_all_with_honest_note` |
| Öneri | `test_suggestion_carries_relevance_reason_and_source_link` — gerekçe + link girdiden; `test_empty_catalog_returns_honest_partial_without_invention` — boş katalogta dürüst partial |
| Dil değişimi | `test_language_switch.py` — profil + eksik bilgi + öneri tr/en |
| Talep düzenleme | `test_edit_creates_new_proposal_version_with_new_hash` — yeni sürüm (yeni kimlik + hash) ve ESKİ hash'le onayın reddi; `test_edit_without_existing_proposal_is_rejected` |
| Onay bekleyen state | `test_complete_details_build_proposal_awaiting_explicit_approval` — needs_input + `action_proposal` ekli + açık onay sorusu + `action_proposed` olayı; `test_needs_input_persists_checkpoint_and_resume_completes` — checkpoint yazımı, restart benzetimiyle okuma, resume ile cevap→öneri→doğrulanmış onay→terminal zinciri |
| Ek: sonuç işleme | `test_verified_acceptance_reports_success_only_after_result` (başarı + r4), `test_rejection_is_reported_honestly_without_success_claim`, `test_approval_without_backend_result_is_rejected`, `test_backend_result_alone_completes_approved_proposal` (B9 şekli), `test_resolved_state_cannot_be_continued`, iptal (`PreCancelledToken`) |

## 8. Kullanılan kaynak kimlikleri (RAG — SADECE CONTEXT)

[LG-INTERRUPTS#C1] (interrupt kalıcı checkpointer + kararlı thread_id + resume girdisi — iş birliği needs_input checkpoint'inin ve `CollabResumeInput` sözleşmesinin deseni), [LG-INTERRUPTS#C2] (devam eden adımın yeniden yürütülebilirliği — durum makinesi adımlarının idempotent yeniden sunumu: `test_proposal_review_state_is_idempotent_on_repeat_call`), [ENG-AGENTS#C1] (basit/birleştirilebilir desenden başlama — model çağrısız deterministik kompozisyon kararı), [ENG-AGENTS#C2] (routing deseni — niyet güdümlü dal seçimi).

## 9. Bulgular

- **F1 (orta, tasarım kararı olarak kayıtlı):** `ActionProposal` sözleşmesi (DONMUŞ A1 modeli + B1 şeması) `article_id/article_revision/base_content_hash` zorunlu tuttuğundan iş birliği önerisi MAKALEYE BAĞLIDIR; makale bağlamı olmayan iş birliği talebi `needs_input` ile hangi içerik olduğu sorulur, uydurma bağlam üretilmez (`test_proposal_without_article_context_asks_which_content`). Site-geneli "içeriksiz" iş birliği kaydı B9 backend şemasıyla yeniden değerlendirilmelidir.
- **F2 (düşük):** Router sinyal kümelerinde mevcut kod tabanının tutarsız kuralı gözlendi: `_RESEARCH_SIGNALS`/`_ANALYSIS_SIGNALS` içindeki Türkçe karakterli sinyaller ("araştır", "açıkla") katlanmış metinle asla eşleşmez (yalnız ASCII üyeleri çalışır). A9 sinyalleri KATLANMIŞ biçimde yazıldı (kural: "arastir"); mevcut kümelere dokunulmadı (davranış değişikliği bu fazın dosya sahipliği sınırını aşar) — orchestrator takibi önerilir.
- **F3 (düşük, kapsam):** Broker yolu (worker) profil/proje deposu ve checkpoint'i `execute_plan`'e henüz bağlamaz (messaging katmanı bu fazın dosya sahipliği DIŞI). Broker üzerinden gelen rehberlik/iş birliği niyeti dürüst `config_error` ile biter; gerçek bağlama B9/B10 dispatch'inindedir. Kanıt: `execute_plan` iş birliği dalının `checkpoint is None` kolu + `test_collab_without_checkpoint_store_fails_with_config_error`.
- **F4 (bilgi):** B9'un "aynı onay için ikinci resume üretme" koruması çekirdekte `RESOLVED` state'in devam reddiyle desteklenir (`test_resolved_state_cannot_be_continued`); idempotent kayıt korumasının asıl sahibi B9 backend'idir.

## 10. Sınırlar ve kapsam dışı bırakılanlar

- Agent backend'e talep KAYDEtmez, e-posta GÖNDERMEZ: akış yalnız öneri üretir, `needs_input`'ta durur; kayıt/onay/tekrar koruması B9, UI B10'dadır (plan A9 son paragrafı). Sınır testlerle kanıtlı: başarı metni yalnız doğrulanmış `accepted` sonucunda; gönderim ifadesi öneri metninde "açık onaydan sonra" diye şartlı.
- Backend proposal saklama (B9), REST/UI (B10), messaging consumer değişikliği, `src/contracts/**`: DOKUNULMADI.
- Donmuş modüller (web/research/qa/analysis/checkpoint) değişmedi; `models/ports` yalnız additive (enums'a 4 `RunIntent` üyesi; imza kırılması yok — tam regresyon kanıtı §6).
- Gerçek LLM sağlayıcısı devrede değil: rehberlik/iş birliği akışları zaten model çağırmaz; fixture/test-double başarısı gerçek sağlayıcı başarısı sayılmaz (ana prompt kuralı).

## 11. Ortam olayları

- Yok. `git checkout/switch/stash` kullanılmadı (L006); `nul` dosyası üretilmedi (L002); commit/push yapılmadı (orchestrator'a ait). Faz sonunda `git status`: yalnız izinli dosyalar (4 M + 4 yeni yol); beklenmeyen untracked yok.

## 12. Sonuç

A9 plan listesindeki iki blok (profil/proje davranışı + iş birliği hazırlığı) ve router bağlaması gerçek implementasyonla tamamlandı; yedi kabul senaryosu testle kanıtlandı. Faz kapıları: `tests/guidance` 66 passed; broker-dışı tam regresyon 626 passed/1 skipped. Durum: **doğrulanmayı bekliyor** (orchestrator bağımsız incelemesi).
