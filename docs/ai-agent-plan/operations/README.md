# B11 Operasyon Rehberleri — AI agent haberleşme hattı

Bu dizin B11 fazının operasyon teslimleridir (plan satır 581: "Yerel çalıştırma,
topology, schema migration, DLQ inceleme, backup/restore ve rollout/rollback
rehberi teslim edilir").

| Rehber | Kapsam |
| --- | --- |
| [yerel-calistirma.md](yerel-calistirma.md) | Compose ortamı, health endpoint'leri, test suite'leri, E2E koşumları |
| [topoloji-ve-surum-kilidi.md](topoloji-ve-surum-kilidi.md) | Broker topology, sürüm kilidi, servis kullanıcıları/vhost/izinler, TLS yolu, saklama/replay penceresi kararı |
| [schema-migration.md](schema-migration.md) | EF Core (backend şeması) + Alembic (agent şeması) migration runbook'u |
| [dlq-inceleme-ve-replay.md](dlq-inceleme-ve-replay.md) | DLQ'ya düşme nedenleri, inceleme komutları, replay prosedürü, süresi geçmiş işler |
| [yedekleme-geri-yukleme.md](yedekleme-geri-yukleme.md) | Postgres backup/restore, broker volume, runbook |
| [surum-gecisi-rollback.md](surum-gecisi-rollback.md) | Sıfır-kesinti rollout, eski/yeni sürüm birlikte çalışması, rollback adımları |
| [pgvector-karari.md](pgvector-karari.md) | B11 pgvector kararı: uygulanmadı — gerekçe, uygulama adımları, rollback |

Sürüm kilidi (B11, doğrulanmış): `rabbitmq:4.2.9-management` + `RabbitMQ.Client
7.2.2` + `aio-pika 9.5.8` + `postgres:18.0-alpine`. Değişiklikler yalnız
`topoloji-ve-surum-kilidi.md` prosedürüyle yapılır.
