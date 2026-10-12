# Rollout ve rollback rehberi — agent haberleşme hattı

Plan bağlantıları: satır 564 "Şema migration ve eski/yeni servis sürümünün
birlikte çalışmasını test et"; senaryo 12.

## 1. Dağıtım birimi ve sırası

Dört dağıtım birimi vardır: `backend` (.NET), `agent-worker` (python),
`frontend` (Next.js — hat için etkisiz), `broker` (topoloji; image sürümü).
Sıfır-kesinti rollout sırası (expand-contract):

```text
1. schema migration (additive; eski kod çalışmaya devam eder)
   → schema-migration.md: Önce Alembic, sonra EF
2. backend yeni sürüm (tek declarer; AgentTopologyInitializer idempotent)
3. agent-worker yeni sürüm
4. (gerekliyse) contract migration — yalnız additive; v2 sözleşme B1 kilidi
   gereği ayrı karar sürecinden geçer
```

## 2. Eski/yeni sürüm birlikte çalışması (senaryo 12)

Garantinin kaynağı: donmuş B1 sözleşmesi — 18 mesaj türü, tek schema_version=1,
38 ortak fixture iki dilde birebir doğrulanır:

- `.NET`: `Api.Tests/AgentContractFixtureTests.cs` +
  `AgentMessagingBrokerContractMirrorTests.cs`
- python: `tests/test_messaging_contracts_fixtures.py` +
  `test_messaging_contracts_rules.py`

Rollout penceresinde eski backend + yeni worker (ve tersi) aynı zarfları
üretir/tüketir; `delivery_attempt` transport tekrar sayacı, idempotency
inbox/outbox tarafındadır — sürüm karışımı çoğaltma üretmez (senaryo 12'nin
kanıt testleri B4 intake idempotency + B5 projection tekilleştirmesidir).

Kısa pencere kuralı: eski sürümlü bileşen en fazla BİR contract major sürümü
ile çalışır; v2 sözleşme çıkarsa eski bileşen v1'i konuşmaya devam ederken
v2 bileşenler çift-yayın (v1+v2) dönemi yaşar — bu fazda v2 YOKTUR.

## 3. Rollout adımları

```bash
# 0) Ön koşullar
docker compose ps                    # mevcut hattın sağlıklı olduğu
pg_dump (yedekleme-geri-yukleme.md §2)

# 1) Migration'lar (schema-migration.md §3)
alembic upgrade head && dotnet ef database update

# 2) Backend
docker compose up -d --no-deps --build backend
curl -f http://127.0.0.1:8080/health/live   # 200
curl -f http://127.0.0.1:8080/health/ready  # 200

# 3) Agent worker (servis birimi; bu depoda compose tanımı yoksa mevcut
#    dağıtım aracının worker unit'i — canlı dağıtım B11 kapsamı DIŞIDIR)
#    worker başlangıç doğrulaması: alembic current == head, broker vhost erişimi

# 4) Duman doğrulaması (gerçek bileşenlerle)
#    - gerçek kabul: POST /api/v1/agent/messages → 202 + run_id
#    - /health/agent: backlog 0'a döner; backend.agent.events.q tüketilir
#    - GET /api/v1/agent/runs/{runId} → terminal durum
```

## 4. Rollback

Tetikleyici: `/health/agent` Unhealthy kalıcı + DLQ/relay hataları + projection
quarantine artışı (admin gözlem sayfası) + run sonuçlarının gelmemesi.

```bash
# 1) Uygulama sürümlerini geri al (migration GERİ ALINMAZ — additive olduğu
#    için eski kod yeni şemayla çalışır)
docker compose up -d --no-deps backend@önceki-image
#    worker birimi aynı şekilde önceki image'e döner

# 2) Health kapısı
curl -f .../health/ready && curl -f .../health/agent

# 3) Uçuşta kalan işler: DB outbox'ta Pending kayıtlar eski relay tarafından
#    boşaltılır (lease dolunca AYNI message_id ile) — ek işlem gerekmez.

# 4) Yalnız migration geri alınması GEREKİYORSA (nadir; veri siler):
#    önce pg_dump, sonra schema-migration.md §5 (alembic downgrade / ef update <onceki>)
```

## 5. Rollout sonrası izleme

- `/health/agent` JSON: `pending_count`, `oldest_pending_age_minutes`
- Admin gözlem sayfası (B10): queue/job backlog, en eski iş yaşı, outbox
  yayın gecikmesi, confirm hatası, duplicate/inbox sayıları, retry/DLQ
- `docker exec blogapp-rabbitmq rabbitmqctl list_queues name messages`
