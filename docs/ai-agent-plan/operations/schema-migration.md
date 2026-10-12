# Schema migration runbook — EF Core + Alembic

İki şema, iki sahip, sıfır FK (D011): backend şeması EF Core ile
Infrastructure assembly'den yönetilir (tek konsolide migration politikası);
`agent` şeması yalnız Python'a aittir ve Alembic ile yönetilir.

## 1. Migration zinciri (B11 itibarıyla)

| Sahip | Araç | Zincir | Konum |
| --- | --- | --- | --- |
| Backend | EF Core 10 (Npgsql) | tek konsolide set + B3/B5/B8/B9 additive migration'ları | `src/backend/Infrastructure/Infrastructure/Persistence/Migrations` |
| Agent | Alembic 1.20.0 (D014 kilidi) | 0001 (inbox/jobs/outbox) → 0002 (run_event_sequences) → 0003 (job_leases + cancel_intents) | `src/services/ai-agent-service/migrations` |

Alembic ortamı: `AGENT_DB_URL` (parola yalnız env'den; yoksa fail-fast) +
`AGENT_DB_SCHEMA=agent`; `version_table_schema='agent'`.

## 2. Sıralama kuralı

1. **Önce Alembic** (agent şeması additive ve bağımsızdır), **sonra EF** —
   tersi de güvenlidir çünkü şemalar arası FK yoktur; ancak rollout
   prosedüründe tek sıra tutarlılığı sağlar.
2. Migration içeren servis sürümü, migration'ı uygulayan sürümle AYNI anda
   release edilmez: migration önce uygulanır (additive olduğu için eski kod
   çalışmaya devam eder), sonra yeni servis başlatılır (expand-contract).

## 3. Uygulama komutları

```bash
# Agent şeması (agent DB'si — dev'de blogdb_dev; scratch test DB'lerinde ayrı)
cd src/services/ai-agent-service
export AGENT_DB_URL="postgresql+asyncpg://USER:PASS@127.0.0.1:5432/blogdb_dev"
export AGENT_DB_SCHEMA=agent
alembic upgrade head
alembic current          # doğrulama: 0003 (head)
alembic history -v       # zincir denetimi

# Backend şeması (uygulama başlangıcında otomatik veya elle)
# - container'da: Database__RunMigrationsOnStartup=true (compose prod yolu)
# - geliştirmede elle:
cd src/backend/Presentation/API
dotnet ef database update --project ../../Infrastructure/Infrastructure
```

## 4. Doğrulama

```bash
# Alembic head ile şema aynı mı (python suite):
cd src/services/ai-agent-service
python -m pytest tests/intake/test_migrations_smoke.py -q

# EF migration'ları uygulandı mı:
psql ... -c "\d outbox_messages" | head   # B3 tablosu var mı
```

## 5. Geri alma

- **Alembic:** `alembic downgrade -1` (tek adım) veya `alembic downgrade 0001`.
  DİKKAT: downgrade veri SILER (ör. 0003 → jobs lease kolonları). Üretimde
  downgrade yalnız `yedekleme-geri-yukleme.md` backup'ı alındıktan sonra.
- **EF:** `dotnet ef database update <OncekiMigration>`. Additive migration'ların
  geri alınması kolon/tablo düşürür — aynı şekilde backup sonrası.

## 6. Eski/yeni sürüm birlikte çalışması

İki servis sürümünün aynı sözleşmelerle çalışması (plan senaryosu 12) B1
sözleşme ayna testleriyle sabittir: 38 ortak fixture iki dilde birebir
doğrulanır (`.NET: AgentContractFixtureTests` + `AgentMessagingBrokerContractMirrorTests`;
python: `test_messaging_contracts_fixtures.py` + `test_messaging_contracts_rules.py`).
Rollout sırası `surum-gecisi-rollback.md`'dedir.
