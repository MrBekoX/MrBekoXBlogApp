# Port sözleşme özeti (A10 teslimi)

Sources: `app/agent_core/ports/*.py` define the structural protocols;
`app/agent_core/models/*.py` define validated business models (Pydantic v2,
`extra=forbid`). Production adapters implement these protocols.

## Portlar

| Port | Sorumluluk | Ana metotlar | Production implementation |
| --- | --- | --- | --- |
| `ModelProvider` | tek tamamlama çağrısı; kullanım döner | `complete` / `stream_complete` | `OpenAiModelProvider` |
| `EmbeddingProvider` | metin→vektör kümesi | `embed(texts, cancel)` | `OpenAiEmbeddingProvider` (`text-embedding-3-small`, 1536 dimensions) |
| `BudgetStore` | atomik rezervasyon/commit/release + kullanım görünümü | `reserve/commit/release/usage` | `PolicyBudgetStore` (üretim; bellek-içi) |
| `CheckpointStore` | run bazında opak payload saklama | `save/load/load_latest/list` | `FileCheckpointStore` (persistent filesystem) |
| `ContentRepository` | makale içeriği getirme (K7 yalnız-referans bağlam) | `get_article(article_id)` | `HttpContentRepository` |
| `ProfileRepository` | onaylı profil özeti | `get_profile()` | `CanonicalProfileRepository` / canonical summary |
| `ProfileKnowledgeRepository` | versioned profile content and provenance | `active_snapshot()` / `load(snapshot)` | `CanonicalProfileRepository` |
| `ProjectRepository` | onaylı proje kayıtları | `list_projects()` | `StaticProjectRepository` |
| `WebSearchProvider` | kontrollü web araması | `search(query, max_results, cancel)` | `HttpWebSearchProvider` with a configured endpoint |
| `SourceReader` | URL'den metin çıkarma (A6 araç arkası) | `read(url, ...)` | `HttpSourceReader` (SSRF korumalı) |
| `ProgressSink` | ilerleme olayı yayını; arızası akışı kesmez | `publish(DomainProgress)` | Worker progress sink and persistent event outbox |
| `CancellationToken` | iptal sinyali | `is_cancelled`, `reason`, `raise_if_cancelled` | Worker cancellation and lease fencing |

## Veri tipi köprüleri (D015)

Donuk A1 sözleşme modelleri (`SourceReference`, `EvidenceItem`) genişletilmez;
zengin alanlar iş modellerinde yaşar ve daraltma köprüleriyle geçirilir:

- `WebSourceRecord` (`agent_core/web/models.py`) → `to_source_reference()`
- `ClaimEvidenceRecord` (`agent_core/research/**`) → `record_to_evidence_item()`

## Rota kararı (`RouteDecision`, 8 alan)

`run_id, selected_mode, intent, source_scope, needs_web, needs_clarification,
clarification_question, brief_reason, budget_profile_id, decided_at` — karar
bir kez hesaplanır; kesin durumlarda kurallar (model çağrısız), belirsiz
durumlarda `router_model` JSON önerisi doğrulanıp sıkıştırılarak birleştirilir
(LLM limitleri ASLA okunmaz; bütçe daima sunucu profili).

## Çekirdek akış paketleri (davranış W6 sonunda donuk)

- `qa` — A4 altı-node QA graph'ı; SADECE CONTEXT üretimi, tek sorgu düzenleme,
  atıf seçimi/denetimi, bölüm bağlantı guardrail'i.
- `analysis` — A5 başlık-başına arama + kanıt kapsama + tek üretim çağrısı.
- `research` — A7 plan→gather(Send paralel)→evaluate→coverage→compare→report;
  kanıt kayıtları yapısal olarak doğrulanır (uydurma kaynak ID imkânsız).
- `web` — A6 dört araç; SSRF koruması DNS+redirect-pin'li; loopback yalnız
  `environment="test"`'te.
- `checkpoint` — A8 sürümlü zarf + kararlı yürütme kimliği + resume kapsamı.
- `collab` — A9 durum makinesi; needs_input'ta checkpoint; onay yalnız
  doğrulanmış `ValidatedActionResult` ile.
- `guidance` — A9 profil/projeler/öneri; onaylı kayıttan deterministik, model
  çağrısız; kaynak yoksa dürüst `config_error`/`partial`.

## Hata sözleşmesi

Tek tip `PortError(code, message, port, retryable)`; kodlar
`AgentErrorCode` (`config_error`, `validation_error`, `not_found`,
`stale_snapshot`, `budget_exhausted`, `cancelled`, `provider_error`,
`timeout`) — B1 olay payload'ları bu değerleri kod olarak taşır.

Sürüm kayıtları için `docs/state-schema-versions.md`.
