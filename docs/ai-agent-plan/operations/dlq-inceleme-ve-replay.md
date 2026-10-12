# DLQ inceleme ve replay rehberi

Plan bağlantıları: senaryo 10 (DLQ replay + süresi geçmiş işler), plan satır
"Retry/DLQ kör ve sınırsız tekrar çalıştırma üretmez".

## 1. DLQ topolojisi

Her ana kuyruğun kendi DLQ'su vardır (B1 registry'den türetilen adlar):

| Ana kuyruk | DLQ |
| --- | --- |
| `agent.execute.q` | `agent.execute.q.dlq` |
| `agent.control.q` | `agent.control.q.dlq` |
| `agent.content.q` | `agent.content.q.dlq` |
| `backend.agent.events.q` | `backend.agent.events.q.dlq` |

Yol: handler kalıcı hata (sözleşme ihlali/policy ihlali) → `nack(requeue=false)`
→ `x-dead-letter-exchange` → DLQ. Geçici hata (transport) → retry kademeleri
`blog.agent.retry.{10,30,120}s` → tükendiğinde DLQ. Requeue döngüsü YOKTUR
(B2 consumer base sözleşmesi; test: `test_handler_failure_dead_letters_without_requeue_loop`).

## 2. İnceleme

```bash
# DLQ derinliği (management API)
curl -s -u blogapp:$RABBITMQ_PASS \
  "http://127.0.0.1:15672/api/queues/blogapp_prod/agent.execute.q.dlq" | \
  python -c "import json,sys; d=json.load(sys.stdin); print('messages:', d.get('messages'))"

# Bir mesajın gövdesini GÖRME (peek; requeue=true ile geri koyar)
docker exec blogapp-rabbitmq rabbitmqadmin \
  -u blogapp -p "$RABBITMQ_PASS" -V blogapp_prod \
  get queue=agent.execute.q.dlq requeue=true count=5

# Başarısızlık nedeni: mesaj özelliklerinde x-death header'ı
# (reason=rejected / expired, routing-keys, original-queue, time)
```

Backend tarafı ayrıca `AgentOutboxRelaySettings.MaxAttempts`'ı aşan ve zarfı
çözülemeyen outbox kayıtlarını `LastError` ile işaretler: `outbox_messages`
tablosunda `status != 'Published'` + `last_error` sorgusu birikim teşhisinin
DB ayaklıdır.

## 3. Replay prosedürü (manual, onaylı)

Replay B7 replay servisidir: DLQ'daki mesajı KÖKENAğına (origin queue) AYNI
message_id ile geri yayınlar; intake yeniden DOĞRULAR (sözleşme + inbox
tekilleştirme + run üçlüsü idempotency). Kör replay yoktur — koşullar:

```text
test_valid_job_is_replayed_to_origin_with_same_id     → geçerli iş: replay OK
test_expired_job_is_not_blindly_replayed              → deadline geçmiş: replay RED
test_cancel_intent_blocks_replay_and_finalizes_running → cancel niyeti: replay RED
test_terminal_job_replay_is_discarded                 → terminal iş: atılır
test_payload_mismatch_is_not_replayed                 → payload uyuşmaz: RED
```

Operatör adımı (örnek; doğrulanmış replay servisi python `control` hattının
admin publisher yoludur — doğrudan `rabbitmqadmin publish` KULLANMA, message_id
korunumunu ve doğrulamayı atlar):

1. DLQ mesajını peek et; `x-death.time` ve zarf `deadline_at` alanına bak.
2. Süresi geçmişse (deadline < şimdi) REPLAY ETME — kaydı DLQ'da bırak veya
   §4'teki arşiv akışına al.
3. Uygunsa replay servisiyle kök kuyruğa geri ver; intake zaten doğrular.
4. Sonucu gözlemle: `agent.execute.q` tüketimi + `backend.agent.events.q`'da
   terminal olay.

## 4. Süresi geçmiş işler (plan senaryosu 10'un ikinci yarısı)

- Worker/B7 reaper: deadline'ı geçmiş claim'li işleri `timeout` hatasıyla
  terminalize eder (`test_expired_running_job_fails_with_timeout`).
- Accepted+expired işler reaper'la kapanır
  (`test_accepted_job_with_expired_deadline_is_closed_by_reaper`).
- DLQ'da süresi geçmiş mesaj: replay edilmez; 30 gün saklama penceresi
  (`topoloji-ve-surum-kilidi.md` §6) sonunda management API'den
  `DELETE /queues/{vh}/{q}/contents` ile temizlenir (tüm kuyruk boşaltma —
  seçmeli silinmez; bu yüzden temizlik bakım penceresinde yapılır).

## 5. Toparlanma akış şeması (broker/topoloji sorunu)

```text
/health/agent Unhealthy (broker) → broker'ı kontrol et (docker compose ps)
  ├─ broker ayakta, bağlantı yok → backend/worker log'larında reconnect;
  │   otomatik recovery (NetworkRecoveryInterval=10s) birkaç döngüde döner
  ├─ broker kapalı → rabbitmqctl start_app / compose restart
  │   → relay backlog'u otomatik boşaltır (B11 e2e: toparlanma testi yeşil)
  └─ topoloji bozuk (exchange/kuyruk yok) → backend'i yeniden başlat
      (AgentTopologyInitializer idempotent declare eder; arguman uyuşmazlığında
      PRECONDITION_FAILED → topoloji-ve-surum-kilidi.md §3 adlarıyla karşılaştır)
```
