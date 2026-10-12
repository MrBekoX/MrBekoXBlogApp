# Giriş noktaları — haberleşme adaptörünün çağıracağı sözleşme

Kaynak: `app/agent_core/entrypoints.py`. Adaptör (B6 worker + B9 kontrol
consumer) yalnız bu üç coroutine'i çağırır; graph iç yapısına, node'lara ve
state'e dokunmaz. Rota kararı her çalışmada BİR KEZ hesaplanır: `resume`
kararı checkpoint'ten okur, yeniden hesaplamaz (plan A1/A8).

## 1) `prepare_and_route`

```python
PreparedRun = await prepare_and_route(
    context: ExecutionContext,
    *,
    router_model: ModelProvider | None = None,   # yalnız belirsiz durumlarda çağrılır
    progress: ProgressSink | None = None,
    cancel: CancellationToken | None = None,
    checkpoint: CheckpointStore | None = None,
    execution_id: str | None = None,             # dış adaptör verebilir; biçim denetlenir
)
```

- `ExecutionContext` alanları: `run_id`, `conversation_id`, `question`,
  `language` (`tr`/`en`), `mode_preference` (`auto|fast|analysis|deep_research`),
  `budget_profile` (sunucu profili; LLM limit üretmez), makale bağlamı üçlüsü
  (`article_id`, `article_revision`, `article_content_hash`) + isteğe bağlı
  `article_snapshot`, `selected_text`, `conversation_history`.
- Snapshot verildiyse hash bağlamı YENİDEN hesaplanarak doğrulanır
  (`stale_snapshot` sözleşmesi; D008).
- Çıktı `PreparedRun(context, route, prepared_at, execution_id, collab_state)`;
  checkpoint verildiyse `prepared:run` kimliğiyle sürümlü zarfla yazılır
  (CHECKPOINT_SCHEMA_VERSION=1).
- Hatalar `PortError` kodlarıyla: `cancelled`, `stale_snapshot`,
  `validation_error` (yürütme kimliği biçimi), checkpoint yazım arızaları.

## 2) `execute_plan`

```python
AgentOutcome = await execute_plan(
    prepared: PreparedRun,
    *,
    model: ModelProvider,                        # zorunlu; rehberlik/iş birliği çağırmaz
    retriever=None,                              # SnapshotRetriever (A4/A5 makale yolu)
    content=None,                                # ContentRepository (K7 yalnız-referans)
    budget: BudgetStore | None = None,           # PolicyBudgetStore önerilir
    progress=None, cancel=None,
    qa_config: QaFlowConfig | None = None,
    analysis_config: AnalysisConfig | None = None,
    web_search=None,                             # yalnız bağlantı durumu bildirimi
    web_tools: dict | None = None,               # build_web_tools çıktısı (A6/A7)
    profile_repository=None, project_repository=None,
    article_catalog: list[ArticleCatalogEntry] | None = None,
    checkpoint: CheckpointStore | None = None,   # iş birliği için ZORUNLU
    collab_input: CollabResumeInput | None = None,
    validated_result: ValidatedActionResult | None = None,
)
```

Yol seçimi (karar `prepared.route`'tan gelir):

| Koşul | Yürütülen akış |
| --- | --- |
| `needs_clarification` | model çağrısız `needs_input` terminali (açık soru) |
| intent ∈ {profile, projects, content_suggestion} | deterministik rehberlik; onaylı kaynak yoksa `config_error` (düşme yok) |
| intent = collaboration | durum makinesi; needs_input adımlarında checkpoint ZORUNLU |
| deep_research + makale bağlı + `web_tools` | A7 araştırma graph'ı (web yoksa A5 geçiş: tek çağrı + kullanılamazlık notu) |
| makale bağlı + `retriever` + analysis | A5 analysis alt akışı |
| makale bağlı + `retriever` + fast | A4 QA akışı; yetersizlik + çok bölümlü soruda TEK kayıtlı fast→analysis yükseltmesi |
| diğer | A1 tek-çağrı yolu (adaptörün `retriever`'ı bağlamaması üretimde kalıcı olmamalı — A4-rapor F1 geçişi worker kablolamasıyla kapanır) |

`AgentOutcome`: `status` (completed/partial/needs_input/cancelled/failed),
`selected_mode`, `answer` (fast/analysis) veya `report` (deep_research),
`citations`, `source_scope`, `unresolved_questions`, `mode_upgrades`,
`usage` (model/tool/web arama sayımları + token + süre), `error_code/message`,
`action_proposal` (iş birliği önerisi).

## 3) `resume`

```python
AgentOutcome = await resume(
    request: ResumeRequest,
    *,
    checkpoint: CheckpointStore,                 # zorunlu
    model: ModelProvider,
    retriever=None, content=None, budget=None, progress=None, cancel=None,
    web_search=None, web_tools=None,
    profile_repository=None, project_repository=None, article_catalog=None,
)
```

`ResumeRequest` alanları: `run_id`, `checkpoint_id=None` (None → en son),
`execution_id` (bağ denetimi), `deadline_seconds` (kalan süre; bitince
`timeout` terminali), `current_context` (revizyon kapsamı: `FULL_REUSE` /
`EVIDENCE_STALE` sürer, `NOT_RESUMABLE` → `stale_snapshot` reddi),
`collab_input`, `validated_result`.

### İş birliği zinciri (adaptörün izleyeceği adımlar)

1. İlk çağrı: `execute_plan` (collaboration) → `needs_input` + sorular +
   checkpoint (`collab_state.stage=details_needed`).
2. `resume(ResumeRequest(run_id, collab_input=CollabResumeInput(answers={...})))`
   → öneri üretilir → `needs_input` + `action_proposal`
   (`stage=proposal_review`; özet hash'i checkpoint'te).
3. Backend kayıt onayı: `resume(ResumeRequest(run_id,
   validated_result=ValidatedActionResult(proposal_id, run_id, "accepted",
   applied_article_revision, validated_at)))` → `completed` + çözümlü state.
   **Sonuçsuz onay `validation_error` ile reddedilir** — agent asla kayıt atmaz.
4. Düzenleme: `collab_input.edited_summary/edited_proposed_content` YENİ
   sürüm üretir (proposal_content_hash yenilenir; onay sürüm bağıdır).

## Hata eşlemesi (adaptörün terminal olaylarına)

| `AgentErrorCode` | Terminal | Adaptör notu |
| --- | --- | --- |
| `cancelled` | `RunStatus.cancelled` | iptal sinyali; resume ile devam mümkün |
| `timeout` | `failed` | deadline bitimi; süreç asılı kalmaz |
| `budget_exhausted` | `failed` (araştırmada `partial`) | profil sınırı; profille çözülür |
| `stale_snapshot` | `failed` / resume reddi | bayat içerik; B8 güncelliğiyle ilişkili |
| `config_error` | `failed` | bağlı olmayan onaylı kaynak/web; düşme yok |
| `validation_error` | `failed` / resume reddi | sözleşme ihlali; retry anlamsız |
| `not_found` | `failed` | makale erişilemiyor |
| `provider_error` | `failed` | sağlayıcı arızası; retry politikası adaptörde |

Mesaj zarfı eşlemesi B1 sözleşmesindedir (`src/contracts/agent/v1`, version 1);
bu paket transport tipleri TANIMAZ (D003).
