# Yedekleme ve geri yükleme rehberi

Plan bağlantısı: "backup/restore ... rehberi teslim edilir" (satır 581).
Kalıcı durum iki yerdedir: postgres (run/outbox/inbox/projection kayıtları —
GERÇEK kayıt kaynağı) ve broker volume'ları (geçici kuyruk içeriği; broker
kayıt kaynağı DEĞİLDİR — her kalıcı karar DB transaction'ındadır).

## 1. Neyin yedeklendiği

| Varlık | Araç | Sıklık (öneri) |
| --- | --- | --- |
| Postgres (tüm DB'ler: blogdb_dev + agent şemaları) | `pg_dump` / `pg_dumpall` | günlük + rollout öncesi |
| Broker topoloji tanımı | `rabbitmqctl export_definitions` | topoloji değişiminde |
| Broker kuyruk İÇERİĞİ | YEDEKLENMEZ (tasarım: kayıt kaynağı DB outbox/inbox) | — |
| Uploads/keys volume'ları | mevcut yedekleme politikası (agent kapsamı dışı) | — |

Broker kuyruk içeriği yedeklenmez çünkü hatanın tasarım sözleşmesi
"kalıcı karar DB'de"dir (B3 kabul ölçütü: DB commit sonrası broker kapansa iş
kaybolmaz). Broker volume kaybı = uçuştaki mesajların tekrar teslimi; DB
outbox'ından yeniden yayın üretilir.

## 2. Backup komutları

```bash
# Postgres — her DB ayrı dosya (compose servis kullanıcı kimliğiyle)
docker exec blogapp-postgres pg_dump -U "$POSTGRES_USER" -d blogdb_dev -Fc \
  > backups/blogdb_dev_$(date +%Y%m%d_%H%M).dump

# Broker topoloji tanımı (kuyruk/exchange/izin tanımları)
docker exec blogapp-rabbitmq rabbitmqctl export_definitions /tmp/defs.json
docker cp blogapp-rabbitmq:/tmp/defs.json backups/broker_defs_$(date +%Y%m%d).json
```

## 3. Restore komutları

```bash
# Postgres
docker exec -i blogapp-postgres pg_restore -U "$POSTGRES_USER" \
  -d blogdb_dev --clean --if-exists < backups/blogdb_dev_YYYYMMDD_HHMM.dump

# Broker tanımları (topoloji; uygulama declare'i zaten idempotent — K3)
docker cp backups/broker_defs_YYYYMMDD.json blogapp-rabbitmq:/tmp/defs.json
docker exec blogapp-rabbitmq rabbitmqctl import_definitions /tmp/defs.json
```

## 4. Restore sonrası doğrulama (sırayla)

1. `docker compose ps` → tüm servisler healthy.
2. `/health/ready` → 200; `/health/agent` → Healthy (broker bağlantısı + backlog).
3. Alembic head doğrulaması: `alembic current` → 0003 (agent şeması).
4. Agent hattı duman testi: B11 python e2e tam suite (`pytest tests/e2e -q`,
   L009 izole vhost/scratch DB ile) veya tek gerçek kabul: backend kabul →
   `outbox_messages` kaydı `Published` → terminal olay `backend.agent.events.q`'da.
5. Kalan outbox backlog'u: `SELECT count(*) FROM outbox_messages WHERE "Status" = 'Pending';`
   → relay'in kendi döngüsünde boşaldığını gözlemle (bekliyor kayıp DEĞİLDİR).

## 5. Kısmi kurtarma senaryoları

| Kayıp | Etki | Kurtarma |
| --- | --- | --- |
| Broker volume | uçuş mesajlar | DB outbox yeniden yayınlar (relay); inbox tekilleştirme çoğaltmayı engeller |
| Postgres (agent şeması) | run/job/projection kayıtları | son `pg_dump` restore; uçuşta kabul edilen işler kaybolmuş olabilir — kullanıcıya tekrar soru gönderimi önerilir |
| Tek kuyruk zehirlenmesi | DLQ birikimi | `dlq-inceleme-ve-replay.md` prosedürü |
