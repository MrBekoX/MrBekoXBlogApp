# State ve şema sürümleri (A10 teslimi)

| Sürüm sabiti | Değer | Konum | Kapsam |
| --- | --- | --- | --- |
| `CHECKPOINT_SCHEMA_VERSION` | 1 | `agent_core/checkpoint/models.py` | checkpoint ZARFI: şema sürümü + run/execution_id bağlamı. Uyumsuz/ilerideki sürüm anlaşılır `validation_error` ile reddedilir; zarfsız A1 dönemi payload'ları geriye dönük yüklenir. |
| `STATE_SCHEMA_VERSION` | 1 | `agent_core/state/state.py` | checkpoint payload'I (graph state). `save_checkpoint(kind=state)` yalnız bu sürümü yazar; farklı sürüm yazım anında reddedilir. |
| `COLLAB_STATE_SCHEMA_VERSION` | 1 | `agent_core/collab/models.py` | iş birliği hazırlık state'i (`CollaborationState`), PreparedRun içinde checkpoint'te taşınır. |
| Mesaj sözleşmesi | `blog.agent.messaging` v1 | `src/contracts/agent/v1/contract.json` | B1 zarf + 18 payload şeması; `delivery_attempt` uzantısı; MaxPayloadBytes 256 KiB. Bu paket transport tipleri tanımaz (D003). |
| Alembic zinciri | 0001–0003 | `app/migrations/` | agent şeması (D014: Alembic 1.20.x kilitli; `version_table_schema='agent'`). |
| `article_revision` anlamı | D008/L004 | — | backend'in atadığı monoton yayımlanmış içerik anı; `BlogPost.Version` (xmin) DEĞİLDİR. |

## Uyumluluk kuralları

1. **Zarf/state ayrımı:** zarf sürümü payload sürümünden bağımsız artar;
   okuma tarafı bilinmeyen zarf sürümünü reddeder, desteklenen zarfın
   uyumsuz payload'ını da reddeder (iki ayrı denetim).
2. **Kararlı yürütme kimliği:** `execution_id` hazırlıkta bir kez atanır,
   checkpoint zincirine bağlanır; `resume` başka zincirin checkpoint'ini
   `validation_error` ile reddeder.
3. **İş birliği onay sürümü:** `proposal_content_hash` düzenlenebilir özet
   metninin UTF-8 SHA-256 özetidir (B9 tek tanım; backend
   `AgentCollaborationContentHash.Compute` ile aynı değer). Onay farklı
   sürüme işaret ederse reddedilir.
4. **Embedding cache:** source revision, content hash, model identifier, and
   dimension must match before persisted vectors are reused. No shared answer
   cache is implemented by an evaluation harness.
5. **Sürüm arttırma disiplini:** davranış değişen her şema alanı sürümünü
   artırır ve bu tablo güncellenir; eski checkpoint'ler için dönüştürücü
   yazılmaz — anlaşılır reddetme sözleşmedir (plan A8).
