# Topoloji, sürüm kilidi, erişim politikaları ve saklama kararı

Plan kaynakları: plan satır 557-563; [RMQ-DOTNET#C1] bağlantı yaşam döngüsü,
[RMQ-DOTNET#C2] consumer bellek kuralları, [DOCKER-COMPOSE#C2] compose.

## 1. Sürüm kilidi (plan satır 557: "Broker image ve istemci sürümlerini uyumlu kilitle")

| Bileşen | Kilitli sürüm | Konum |
| --- | --- | --- |
| Broker imgesi | `rabbitmq:4.2.9-management` | `docker/docker-compose.yml` (B11'de yüzen `4.2-management` etiketinden sabitlenmiştir) |
| .NET istemci | `RabbitMQ.Client 7.2.2` | `src/backend/BuildingBlocks/BuildingBlocks/BuildingBlocks.csproj` |
| Python istemci | `aio-pika >=9.5,<10` (kurulu 9.5.8) | `src/services/ai-agent-service/pyproject.toml` |
| Postgres | `postgres:18.0-alpine` | `docker/docker-compose.yml` |

Doğrulama (B11 koşum kaydı): `docker pull rabbitmq:4.2.9-management` sonrası
imge Id'si, çalışan `blogapp-rabbitmq` container'ının imgesiyle birebir aynıdır
(sha256:9e9fd21d…). Pin, çalışan ortam için işlemsiz yeniden etiketlemedir;
veri/volume etkisi yoktur.

Yükseltme kuralı: broker major/minor sürümü, İKİ istemcinin de belgelenmiş
uyumluluk aralığına girmeden yükseltilemez; yükseltme `surum-gecisi-rollback.md`
prosedürüyle yapılır.

## 2. Kalıcı volume'lar (plan satır 558)

- `rabbitmq_data` → `/var/lib/rabbitmq` (topoloji + kuyruk mesajları durable)
- `postgres_data` → `/var/lib/postgresql/data`
- `redis_data`, `backend_uploads`, `backend_keys`

Tümü adlandırılmış compose volume'udur; `docker compose down` volume'ı
DÜŞÜRMEZ, `down -v` DÜŞÜRÜR (backup/restore rehberine bak).

## 3. Servis kullanıcıları, vhost ve erişim politikaları (plan satır 559)

Ortam ayrımı vhost iledir (dev: `blogapp_dev`; her test fazının kendi vhost'u
vardır — L009). Üretimde en az iki vhost önerilir: `blogapp_prod` ve
`blogapp_staging`.

Roller (D013 izin modeli; B2'den beri değişmez):

| Kullanıcı | configure | write | read | Amaç |
| --- | --- | --- | --- | --- |
| `backend_svc` | `.*` (tek declarer) | `blog.(agent.commands\|content.events)` | `backend.agent.events.q(.dlq)?\|agent.(execute\|control\|content).q` | Komut/içerik yayını + kendi olay kuyruğunu tüketimi + topoloji declare |
| `agent_svc` | (yok) | `blog.agent.events` | `agent.(execute\|control\|content).q(.dlq)?` | Olay yayını + komut/içerik/ kontrol tüketimi |
| `agent_restricted` | — | — | — | Negatif test kimliği; üretimde YOK |

Sabit kurallar:
- Declarer ayrı bir operasyonel kimliktir; uygulama mesajı yayınlamaz
  (RabbitMQ 4.2'de DLX'li kuyruk yaratımı declarer'dan ek izin ister — D013).
- `backend_svc` events exchange'ine yazamaz (yetkisiz yayın engeli — B2 kabul
  ölçütü, test: `test_backend_service_cannot_publish_to_events_exchange`).
- Parolalar koda/repoya girmez: `.env` + gizli yönetimi; bu depodaki dev
  düz metin kimlikler yalnız 127.0.0.1'e bound broker içindir.

Topoloji declare'i: backend dağıtımında `AgentTopologyInitializer` açılışta
`InitializeAsync` çağrılır (K3: tek declarer). Exchange/kuyruk adları donmuş
B1 sözleşmesinden gelir: `blog.agent.commands`, `blog.agent.events`,
`blog.content.events`, kuyruklar `agent.execute.q`, `agent.control.q`,
`agent.content.q`, `backend.agent.events.q` (+ `.dlq` ve retry kademeleri
`blog.agent.retry.{10,30,120}s`).

## 4. Management UI ağ sınırı (plan satır 560)

- Compose'da AMQP 5672 ve management 15672 yalnız `127.0.0.1`'e bound'dur;
  broker'a dış ağdan erişim yoktur.
- Üretimde: management portu YA hiç yayınlanmalı (yönetim SSH tüneli/VPN
  üstünden) YA da yalnız yönetim ağında ayrı bir port yayınlanmalıdır.
  `RABBITMQ_DEFAULT_USER/PASS` üretimde mutlaka `.env` ile değiştirilir.

## 5. Production TLS yolu (plan satır 559: "production TLS ve erişim politikalarını belgeleyip uygula")

**Durum: belgelendi — istemci kodu değişikliği B11 dosya sahipliği dışındadır
(uygulanmadı, aşağıdaki adımlar uygulanabilir karar olarak yazılmıştır).**

AMQP TLS için istemci taraflı tek eksik: `RabbitMqSettings`'e `ssl: bool` +
`ssl_version` alanı eklenip `RabbitMqConnectionManager`'da
`ConnectionFactory.Ssl = new SslOption(serverName, enabled: true)` ayarlanması
(RabbitMQ.Client 7.x API'si). Python tarafında `BrokerSettings`'e `ssl=True`
ve `aio_pika.connect_robust(..., ssl=True)` karşılığı eklenir. Adımlar:

1. `RabbitMqSettings` + `BrokerSettings`'e TLS alanları ekle (additive).
2. Broker tarafında 5671 listener + sertifikayı mount et; `management` UI'ı
   ters proxy arkasında HTTPS'e al.
3. Compose env: `RABBITMQ_SSL=true` vb.; port 5671'e geç.
4. `dotnet build` + python tam suite'i TLS'li scratch broker ile bir kez koş.

Rollback: env `RABBITMQ_SSL=false` → istemciler düz 5672'ye döner (kod
additive olduğu için davranış değişmez).

## 6. Outbox/inbox saklama ve replay penceresi kararı (plan satır 563)

**Karar (B11):** yayımlanmış outbox kayıtları ve uygulanmış inbox kayıtları
**30 gün** saklanır; replay penceresi bu süreyle sınırlıdır. Gerekçe:
- replay/DLQ incelemesi pratikte olay tarihinden haftalar sonra yapılır;
- 30 gün, deadline'lı işlerin (≤15 dk) ve içerik senkron watermark'ının
  (dakikalar) kat kat üzerindedir;
- tablolar katılımsız büyümeye karşı bağlanır.

Uygulama: B11 kapsamında otomatik silme job'ı YAZILMADI (Infrastructure dosya
sahiplliği dışı). Operatör, bakım penceresinde aşağıdaki SQL'i koşar
(idempotent; `published_at`/`applied_at` dolu kayıtlara dokunulmaz):

```sql
-- outbox: yayımlanmış ve 30 günden eski
DELETE FROM outbox_messages
WHERE "PublishedAt" IS NOT NULL AND "PublishedAt" < now() - interval '30 days';

-- agent.outbox_events (python sahibi; Alembic şeması)
DELETE FROM agent.outbox_events
WHERE published_at IS NOT NULL AND published_at < now() - interval '30 days';

-- agent.inbox_messages (uygulanmış/decided kayıtlar)
DELETE FROM agent.inbox_messages
WHERE status IN ('applied', 'stale', 'quarantined')
  AND created_at < now() - interval '30 days';

-- agent_event_inbox (.NET projection inbox)
DELETE FROM agent_event_inbox
WHERE status IN ('applied', 'stale', 'quarantined')
  AND "CreatedAt" < now() - interval '30 days';
```

Replay penceresi ilkesi: bir mesaj 30 günden eskiyse replay EDİLMEZ (iş
deadline'ı çok geride kalır; tekrar çalıştırma anlamsızdır) — DLQ inceleme
rehberindeki "süresi geçmiş iş" kararıyla aynıdır.

## 7. Kabul sınırları ve bekleyen iş gösterimi (plan satır 561-562)

- Kabul kapısı: `AgentAcceptance.MaxActiveRunsTotal` (B7 backpressure) —
  sistem düzeyi backlog sınırı; `MaxActiveRunsPerOwner` sahibi başına.
- Broker kapalıyken: kabul DB outbox'ına yazar, run `Accepted` görünür
  (bekliyor), iş kaybolmaz; `/health/agent` backlog sayısı + en eski bekleme
  yaşını raporlar. Toparlanma relay'in kendi döngüsündedir — operatör eylemi
  gerekmez.
