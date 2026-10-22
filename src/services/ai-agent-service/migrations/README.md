# Agent migration dizini (B4)

Alembic 1.20.0 (resmî belge ile doğrulandı: SQLAlchemy 2.0+ gerekir) ile
`agent` schema'sını yönetir (D011: agent tablolarının tek sahibi Python'dur;
backend EF Core şemasına dokunmaz; schema'lar arası FK kurulmaz).

## Komutlar (repo kökünden)

```bash
# ortam değişkenleri (parola koda gömülmez)
export AGENT_DB_HOST=127.0.0.1
export AGENT_DB_PORT=5432
export AGENT_DB_USER=blogapp_user
export AGENT_DB_PASSWORD=...   # docker/.env içindeki POSTGRES_PASSWORD
export AGENT_DB_NAME=blogdb_dev
export AGENT_DB_SCHEMA=agent

# uygula / geri al / durum
alembic -c src/services/ai-agent-service/migrations/alembic.ini upgrade head
alembic -c src/services/ai-agent-service/migrations/alembic.ini downgrade base
alembic -c src/services/ai-agent-service/migrations/alembic.ini current
```

`AGENT_DB_URL` verilirse (`postgresql+asyncpg://...`) tüm değişkenler yerine
onun kullanılır. Sürüm tablosu hedef schema içindedir:
`agent.alembic_version_agent`.

## Tablolar

- `agent.inbox_messages` — consumer kapsamlı mesaj idempotency kaydı;
  PK `(consumer_name, message_id)`. Satır yalnız iş kabulü ile AYNI
  transaction'da doğar; ayrı "görüldü" işareti yoktur (plan B4).
- `agent.jobs` — kalıcı iş kabulü; `run_id` UNIQUE (idempotent kabul),
  `payload_hash` SHA-256 (aynı run_id farklı payload → çatışma).
- `agent.outbox_events` — accepted olayının outbox kaydı; `claimed_until`
  lease + `FOR UPDATE SKIP LOCKED` ile relay erişimi; `published_at` confirm
  sonrası yazılır.

## Zincir

`0001` → `0002` → `0003` → `0005` (`0004` bilinçli olarak kullanılmadı; kimlik
Who am I karar kaydı K4 adıyla hizalı). Yeni migration `down_revision = "0005"`.

### 0005 — run wire sürümü (Who am I, K4)

- `agent.jobs.wire_version smallint NOT NULL DEFAULT 1` (`ck_jobs_wire_version`:
  1|2). Kabulde execute zarfının `schema_version`'ı yazılır; run boyunca değişmez.
  Mevcut satırlar 1 (v1) okunur.
- `trg_jobs_wire_claim_guard` (jobs BEFORE UPDATE): satır sürümü oturumun
  `agent.worker_wire_max` ayarından (yoksa 1) büyükse güncelleme atlanır.
  Yeni worker havuzu (`messaging.db.connect_pool`) bağlantı başlangıcında
  `agent.worker_wire_max=2` bildirir; ayarı bilmeyen eski worker v2 işini
  claim edemez, kapatamaz, lease'ini yenileyemez.
- `trg_outbox_wire_version_guard` (outbox_events BEFORE INSERT): run'ın jobs
  satırı varsa zarf `schema_version` ≠ `wire_version` → `check_violation`.
- Downgrade aktif v2 işi varken reddedilir: önce
  `cd app && python -m messaging.wire_drain --check` (veya `--cancel`).
