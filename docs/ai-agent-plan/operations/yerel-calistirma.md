# Yerel çalıştırma rehberi — AI agent haberleşme hattı

Bu rehber B11 fazının "yerel çalıştırma" teslimidir. Tüm komutlar Git Bash'te,
repo kökünden (`D:\MrBekoXBlogApp`) verilir; cmd'ye özgü yönlendirme/aygıt
adları kullanılmaz (L002).

## 1. Ön koşullar

| Bileşen | Sürüm (B11 kilidi) | Not |
| --- | --- | --- |
| Docker + Compose | v2 | broker + postgres + redis + backend + frontend |
| .NET SDK | 10.0.x | `dotnet --version` |
| Python | 3.13 | `python --version` |
| Node | 24 | yalnız frontend için |

Gerçek LLM/embedding sağlayıcısı yerelde YOKTUR; tüm testler `is_test_double`
işaretli test sağlayıcıyla koşar ve sonuçlar gerçek model davranışı olarak
raporlanmaz.

## 2. Altyapıyı kaldır

```bash
cp docker/.env.example docker/.env   # ilk kez; POSTGRES_USER/PASSWORD ayarla
docker compose -f docker/docker-compose.yml up -d
docker compose -f docker/docker-compose.yml ps   # hepsi healthy olana dek bekle
docker exec blogapp-rabbitmq rabbitmqctl -q ping  # Ping succeeded beklenir
```

`docker/.env` sır taşır; repoya commit edilmez (sır kuralı). Python test
conftest'leri bu dosyayı çalışma anında okur.

## 3. Sağlık uç noktaları (B11 ayrımı)

Backend'i yerelde kaldır:

```bash
cd src/backend/Presentation/API
dotnet run --urls "http://127.0.0.1:5199"
```

| Uç nokta | Soru | Davranış |
| --- | --- | --- |
| `GET /health/live` | Süreç yanıtlıyor mu? | Bağımlılık denetlemez; her zaman 200 (container liveness'ı budur) |
| `GET /health/ready` | Trafiğe hazır mı? | db + redis (tag `ready`); broker'i İÇERMEZ |
| `GET /health/agent` | Agent hattı sağlıklı mı? | broker bağlantısı + outbox backlog; JSON gövde backlog sayılarını taşır |
| `GET /health` | Tümü | Eski davranış korunur (tüm kontroller) |

Doğrulanmış davranış (B11 koşum kaydı): broker `rabbitmqctl stop_app` ile
durduğunda `/health/live` → 200, `/health/ready` → 200, `/health/agent` → 503
(Unhealthy). Yani broker kesintisi container'ı restart ETMEZ, kabul yolu DB
outbox'ıyla çalışmayı sürdürür; `/health/agent` operatörü görür.

Backlog eşikleri `AgentHealth` section'ından (appsettings) değiştirilir:
`OutboxWarnPendingCount` (vars. 50), `OutboxUnhealthyPendingCount` (500),
`OutboxWarnOldestMinutes` (5), `OutboxUnhealthyOldestMinutes` (30).

## 4. Test suite'leri

SIRA ÖNEMLİDİR (L009): gerçek broker kullanan iki suite'i PARALEL koşturma;
blogapp_dev vhost'u paylaşılır.

```bash
# Python — hızlı katman (broker'sız; ~10 sn)
cd src/services/ai-agent-service
python -m pytest tests -q \
  --ignore=tests/messaging_broker --ignore=tests/intake --ignore=tests/worker \
  --ignore=tests/control --ignore=tests/events --ignore=tests/content_sync \
  --ignore=tests/integration --ignore=tests/collab --ignore=tests/e2e

# Python — TAM suite (broker + postgres; B11 e2e dahil)
python -m pytest tests -q

# Yalnız B11 e2e (kendi vhost'u blogapp_w7_b11 + scratch DB blogdb_agent_b11_e2e)
python -m pytest tests/e2e -q

# .NET — hızlı katman (broker'sız; ~1 sn)
cd ../..../backend   # repo köküne dön
dotnet test src/backend/Presentation/Api.Tests/BlogApp.Presentation.Api.Tests.csproj -c Release --nologo -v q \
  --filter "FullyQualifiedName~BlogApp.Presentation.Api.Tests.SeoDocumentsTests|FullyQualifiedName~BlogApp.Presentation.Api.Tests.Agent.AgentResumeEnvelopeComposerTests|FullyQualifiedName~BlogApp.Presentation.Api.Tests.Messaging.Broker.AgentMessagingBrokerContractMirrorTests|FullyQualifiedName~BlogApp.Presentation.Api.Tests.Messaging.Content.AgentContentEventServiceTests|FullyQualifiedName~BlogApp.Presentation.Api.Tests.Messaging.Projection.AgentRunProjectionRuleTests"

# .NET — TAM suite (broker + postgres; B11 E2E dahil)
dotnet test src/backend/Presentation/Api.Tests/BlogApp.Presentation.Api.Tests.csproj --nologo -v q
```

Notlar:
- .NET suite'i postgres bağlantısını `BLOGAPP_TEST_PG_CONNECTION` env'iyle
  override etmezse `appsettings.Development.json`'dan okur; test DB'leri koşum
  başına benzersiz yaratılıp sonunda düşürülür (blogdb_b3tests_*, blogdb_b5tests_*,
  blogdb_b11e2e_*).
- Python e2e broker vhost'u `blogapp_w7_b11`; .NET E2E vhost'u
  `blogapp_w7_b11net` — birbirinden ve diğer fazların vhost'larından bağımsızdır.
- İzole bozuk durumda: `docker compose restart rabbitmq` sonrası suite'i
  yeniden koş; vhost'lar idempotent provizyon edilir.

## 5. Sık görülen durumlar

| Belirti | Neden | Çözüm |
| --- | --- | --- |
| dotnet test "broker 2 dakikada ayakta gelmedi" | broker kapalı/uykusuz | `docker compose -f docker/docker-compose.yml up -d rabbitmq`; `rabbitmqctl -q ping` |
| python "docker/.env bulunamadı" | env dosyası yok | §2 ilk adım |
| İki koşumda kuyruk tükenmesi/başarısızlık | L009: paralel suite | SERİ koştur; şüphede seri yeniden koşum |
| `/health/agent` Unhealthy ama broker ayakta | topoloji declare edilmedi | backend'i bir kez başlat (AgentTopologyInitializer declare eder) veya `topoloji-ve-surum-kilidi.md` §3 |
| bin/obj kilit hatası (MSB3027) | çalışan test/API süreci | süreci sonlandır, yeniden derle (B9 F2 dersi) |
