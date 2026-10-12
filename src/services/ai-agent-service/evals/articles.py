"""Değerlendirme kümesinin GERÇEK içerik fixture'ları (A10).

Bu makaleler BlogPost yayımlı makale biçiminde (başlık + ``##`` bölümleri +
kod blokları + somut sayısal bilgiler) yazılmıştır ve geliştirme
fixture'larından (``tests/conftest.py``'deki tek paragraflık "Merhaba Dünya"
makalesi, tests/qa'nın dört bölümlük kısa makalesi) BİLİNÇLI AYRIDIR:
değerlendirme örnekleri gerçek sitedeki makale uzunluğuna ve yoğunluğuna
yakın bağlamda ölçüm yapar.

Her bölüm kendi terim kümesini taşır: ilgili bölümün bulunması (retrieval)
ölçümünde yanlış-pozitif örtüşme istemiyoruz. Makaleler off-article
(makale dışı) soruların anlamlı terimlerini TAŞIMAMALIDIR; bu, yetersiz-bilgi
yolunun ölçülebilmesi için bir özelliktir.

Onaylı rehberlik kayıtları (profil/projeler/katalog) A9 akışlarının
girdisidir; hepsi yayımlanabilir, uydurulmamış örnek kayıtlardır.

Web sayfaları ``LocalPageServer`` (evals.providers) ile 127.0.0.1 üzerinde
GERÇEK HTTP ile sunulur; araştırma akışı A6 SSRF/izin katmanından geçerek
okur (ortam: test; loopback yalnız ``environment="test"``'te açıktır).
"""

from __future__ import annotations

from datetime import datetime, timezone

from agent_core.models import ArticleSnapshot, compute_content_hash

NOW = datetime(2026, 10, 12, 9, 0, 0, tzinfo=timezone.utc)

#: Katalog URL'lerinin üretildiği doğrulanmış şablon (tests/qa helpers ile aynı şema).
URL_TEMPLATE = "https://mrbekox.dev/blog/{slug}"


def _snapshot(article_id: str, slug: str, title: str, content: str, *, revision: int, language: str, tags: list[str]) -> ArticleSnapshot:
    return ArticleSnapshot(
        article_id=article_id,
        slug=slug,
        title=title,
        content=content,
        content_hash=compute_content_hash(content),
        article_revision=revision,
        language=language,
        tags=tags,
        published_at=NOW,
        fetched_at=NOW,
    )


# --- Makale 1 (tr): asyncio kuyruk yönetimi ---------------------------------

ASYNCIO_ARTICLE_ID = "post-asyncio-queue"
ASYNCIO_SLUG = "asyncio-kuyruk-yonetimi"
ASYNCIO_TITLE = "Asyncio Kuyruk Yönetimi ve Sınırlandırma"

#: Bölüm başlıkları; ilgili-bölüm ölçümünün beklentileri bu adlarla etiketlenir.
ASYNCIO_SECTION_INTRO = "Giriş"
ASYNCIO_SECTION_BOUND = "Kuyruk sınırı belirleme"
ASYNCIO_SECTION_ERRORS = "Hata yönetimi"
ASYNCIO_SECTION_BACKPRESSURE = "Geri basınç stratejileri"
ASYNCIO_SECTION_PITFALLS = "Sık yapılan hatalar"

ASYNCIO_CONTENT = """Üretim sistemlerinde asyncio kuyrukları iş yükünü dengelemek için kullanılır; ancak sınırsız kuyruk bellek şişmesinin en yaygın nedenidir.

## Giriş

Asenkron Python servislerinde üretici ve tüketici hızları nadiren eşleşir. Kuyruk, iki taraf arasına gerilim tamponu koyar; tampon büyüklüğü ise sistem kararlılığını doğrudan etkiler. Bu rehber, kuyruk sınırı, hata yönetimi ve geri basınç konularını somut değerlerle ele alır.

## Kuyruk sınırı belirleme

`asyncio.Queue(maxsize=...)` ile üst sınır atanır. Küçük servislerde önerilen üst sınır aralığı 100 ile 1000 arasıdır; sınır seçiminde tüketimin ortalama işleme süresi ve gelen istek tepe hızı ölçülür. Karar verirken bekleme süresi metriği olan `queue_wait_seconds` izlenir; bu değer sürekli artıyorsa sınır küçüktür ya da tüketici yetişmiyordur.

```python
kuyruk = asyncio.Queue(maxsize=800)
```

## Hata yönetimi

Kuyruk dolduğunda `put` çağrısı bekler; `put_now` kullanıldıysa `QueueFull` istisnası fırlar. Yaygın desen, işi reddedip tekrar deneme politikasını üstel geri çekilme ile çalıştırmaktır. İstisnayı sessizce yutmak yerine kaydedin; aksi halde kayıp iş görünmez olur.

```python
try:
    kuyruk.put_now(is_)
except QueueFull:
    logla("kuyruk dolu, iş reddedildi")
```

## Geri basınç stratejileri

Sınır dolduğunda üç seçenek vardır: üretici tarafını yavaşlatmak, gelen işi reddetmek ya da tüketici kapasitesini artırmak. Üreticiyi yavaşlatmak en güvenli yoldur; iş reddi yalnız istemcinin yeniden deneyebildiği uçlarda uygulanır. Kapasite artırımı ise tüketici sayısını büyüterek kuyruk boşalma hızını yükseltir.

## Sık yapılan hatalar

Sınırsız kuyruk kurmak, istisna yutmak ve birden çok görevin tek kuyruğu kilitlemesi en sık görülen üç hatadır. Ayrıca tüketici döngüsünde `sleep` unutulursa döngü işlemciyi tüketrir; ölçüm eklemeden yapılan sınır seçimi ise tahmine dayanır.
"""

ASYNCIO_SNAPSHOT = _snapshot(
    ASYNCIO_ARTICLE_ID,
    ASYNCIO_SLUG,
    ASYNCIO_TITLE,
    ASYNCIO_CONTENT,
    revision=4,
    language="tr",
    tags=["python", "asyncio"],
)

# --- Makale 2 (tr): PostgreSQL indeksleme -----------------------------------

PG_ARTICLE_ID = "post-pg-indeksleme"
PG_SLUG = "postgresql-indeksleme-rehberi"
PG_TITLE = "PostgreSQL İndeksleme Rehberi"

PG_SECTION_INTRO = "Giriş"
PG_SECTION_BTREE = "B-tree indeksleri"
PG_SECTION_GIN = "GIN ve tam metin arama"
PG_SECTION_PARTIAL = "Kısmi indeksler"
PG_SECTION_MAINTENANCE = "Bakım ve maliyet"

PG_CONTENT = """Doğru indeks seçimi okuma hızını katlarıyla artırırken yanlış indeks yazma performansını sessizce bozar.

## Giriş

PostgreSQL'de indeks; sorgu planlayıcının tabloyu baştan sona okumak yerine dar bir yapıya inmesini sağlar. Bu rehber B-tree, GIN ve kısmi indekslerin ne zaman seçileceğini ve bakım maliyetini ele alır.

## B-tree indeksleri

Eşitlik ve aralık sorgularının varsayılan seçeneğidir. `CREATE INDEX idx_siparis_tarih ON siparisler (tarih)` biçiminde kurulur; `BETWEEN`, `<`, `>` ve sıralama içeren sorgularda kullanılır. Birleşik kolon sırası en seçici kolondan başlamalıdır; çünkü sol önekin kullanılmadığı sorgu birleşik indeksi hiç kullanamaz.

## GIN ve tam metin arama

JSONB kolonlarında ve tam metin aramada GIN yapısı gerekir. `to_tsvector('turkish', icerik)` üzerine kurulmuş GIN indeksi, metin arama sorgularını tablo taramasına indirmeden yanıtlar. GIN yazma maliyeti B-tree'den yüksektir; sık güncellenen kolonda dikkatli seçilmelidir.

## Kısmi indeksler

`WHERE` koşulu taşıyan indekstir: `CREATE INDEX idx_aktif ON gorevler (son_tarih) WHERE tamamlandi = false`. Yalnız aktif kayıtlar indekslenir; arşiv tablolarında boyut on kat küçülebilir. Sorgunun koşuluyla birebir uyuşması planlayıcı tarafından istenir.

## Bakım ve maliyet

Her indeks yazma işlemini yavaşlatır; kullanılmayan indeksler `pg_stat_user_indexes` üzerinden tespit edilip düşürülür. İstatistikler `ANALYZE` ile tazelenir; şişen indeks `REINDEX` ya da `VACUUM FULL` ile yeniden kurulur. Bakım penceresi olmadan bu komutlar kilitleme yapar.
"""

PG_SNAPSHOT = _snapshot(
    PG_ARTICLE_ID,
    PG_SLUG,
    PG_TITLE,
    PG_CONTENT,
    revision=2,
    language="tr",
    tags=["postgresql", "veritabani"],
)

# --- Makale 3 (en): event-driven microservices -------------------------------

EVENTS_ARTICLE_ID = "post-event-driven"
EVENTS_SLUG = "event-driven-microservices"
EVENTS_TITLE = "Designing Event-Driven Microservices"

EVENTS_SECTION_WHY = "Why events"
EVENTS_SECTION_OUTBOX = "The outbox pattern"
EVENTS_SECTION_IDEM = "Idempotency"
EVENTS_SECTION_ORDER = "Ordering"
EVENTS_SECTION_OBS = "Observability"

EVENTS_CONTENT = """Event-driven systems decouple services in time, but they introduce duplicated deliveries and ordering traps that must be designed for.

## Why events

Services that call each other synchronously fail together. Publishing domain events instead lets consumers react at their own pace and keeps the producer unaware of subscriber count. The trade-off is eventual consistency: readers see slightly stale data until consumers catch up.

## The outbox pattern

Writing to the database and publishing to a broker are two systems; committing one without the other loses or ghosts messages. The outbox pattern writes the event into an outbox table inside the same database transaction as the state change, and a relay process publishes committed rows afterwards. Delivery becomes at-least-once, which the next section handles.

## Idempotency

At-least-once delivery means consumers must tolerate duplicates. Every message carries a deduplication key, and the consumer records processed keys in its own store; a replay is acknowledged but skipped. Exactly-once processing is an illusion across network boundaries; idempotent handlers are the honest goal.

## Ordering

Global ordering is expensive and rarely needed. Producers partition events by an entity key such as order id, and brokers keep per-partition order. Cross-entity ordering is therefore not guaranteed, and consumers must not assume it; state machines should tolerate interleaved events for different entities.

## Observability

Every event carries a correlation id that flows through all consumers, so one business action can be traced end to end. Consumer lag is the health metric of the system: rising lag means consumers fall behind, and alerts should page on sustained growth rather than absolute size.
"""

EVENTS_SNAPSHOT = _snapshot(
    EVENTS_ARTICLE_ID,
    EVENTS_SLUG,
    EVENTS_TITLE,
    EVENTS_CONTENT,
    revision=6,
    language="en",
    tags=["architecture", "messaging"],
)

#: Makale erişimi: dataset yalnız bu sözlük üzerinden makaleye bakar.
EVAL_ARTICLES: dict[str, ArticleSnapshot] = {
    ASYNCIO_ARTICLE_ID: ASYNCIO_SNAPSHOT,
    PG_ARTICLE_ID: PG_SNAPSHOT,
    EVENTS_ARTICLE_ID: EVENTS_SNAPSHOT,
}

# --- Onaylı rehberlik kayıtları (A9) ----------------------------------------

PROFILE_NAME = "sample"
PROFILE_SUMMARY = {
    "name": PROFILE_NAME,
    "job_title": "Backend ve yapay zekâ entegrasyon geliştiricisi",
    "description": (
        "MrBekoX blogunun yazarı; .NET, Python ve RabbitMQ üzerine "
        "üretim deneyimli backend geliştiricisi."
    ),
    "links": {"site": "https://mrbekox.dev", "github": "https://example.invalid/author"},
    "skills": ["dotnet", "python", "rabbitmq", "postgresql"],
}

PROJECT_RECORDS = [
    {
        "name": "mrbekox-blog",
        "description": "Next.js arayüz, .NET backend ve Python agent çekirdeğiyle çalışan kişisel blog platformu.",
        "technologies": ["nextjs", "dotnet", "python"],
        "links": {"site": "https://mrbekox.dev"},
    },
    {
        "name": "queue-lab",
        "description": "asyncio ve RabbitMQ kuyruk desenlerini ölçen küçük deney atölyesi.",
        "technologies": ["python", "rabbitmq"],
        "links": {},
    },
]

ARTICLE_CATALOG = [
    {
        "article_id": ASYNCIO_ARTICLE_ID,
        "title": ASYNCIO_TITLE,
        "url": URL_TEMPLATE.format(slug=ASYNCIO_SLUG),
        "topics": ["python", "asyncio", "kuyruk"],
        "summary": "Kuyruk sınırı, hata yönetimi ve geri basınç için somut değerler.",
    },
    {
        "article_id": PG_ARTICLE_ID,
        "title": PG_TITLE,
        "url": URL_TEMPLATE.format(slug=PG_SLUG),
        "topics": ["postgresql", "indeks", "performans"],
        "summary": "B-tree, GIN ve kısmi indeks seçimi ile bakım maliyeti.",
    },
    {
        "article_id": EVENTS_ARTICLE_ID,
        "title": EVENTS_TITLE,
        "url": URL_TEMPLATE.format(slug=EVENTS_SLUG),
        "topics": ["mimari", "olaylar", "mikroservis"],
        "summary": "Outbox, idempotency, sıralama ve gözlemlenebilirlik.",
    },
]

# --- Araştırma sayfaları (yerel HTTP sunucu gövdeleri) -----------------------

#: asyncio kuyruğu araştırma senaryosunun birincil kaynağı; makaledeki 100–1000
#: aralığını destekler ve ek ölçüm önerir.
QUEUE_GUIDE_PATH = "/queue-guidelines"
QUEUE_GUIDE_HTML = (
    "<html><head><title>Queue sizing guidelines</title></head><body>"
    "<h1>Queue sizing guidelines</h1>"
    "<p>For small asyncio services the recommended upper bound for a queue is "
    "1000 items; start at 100 and measure the wait time before growing.</p>"
    "<p>Track queue wait seconds and consumer lag; alert on sustained growth.</p>"
    "</body></html>"
)

#: İkinci kaynak: kuyruk dolunca reddetme/tekrar deneme önerisi (hata yönetimi
#: iddiasını dış kanıtla destekler).
BACKPRESSURE_PATH = "/backpressure-handbook"
BACKPRESSURE_HTML = (
    "<html><head><title>Backpressure handbook</title></head><body>"
    "<h1>Backpressure handbook</h1>"
    "<p>When a bounded queue is full, reject the task and retry with "
    "exponential backoff; slowing down the producer is safer than dropping "
    "work silently.</p>"
    "</body></html>"
)

#: EN araştırma senaryosunun kaynağı: outbox + idempotency önerisi.
OUTBOX_GUIDE_PATH = "/outbox-pattern-guide"
OUTBOX_GUIDE_HTML = (
    "<html><head><title>Outbox pattern guide</title></head><body>"
    "<h1>Outbox pattern guide</h1>"
    "<p>Write the event to an outbox table in the same transaction as the "
    "state change, then relay committed rows to the broker.</p>"
    "<p>Consumers must deduplicate by message key because delivery is "
    "at-least-once.</p>"
    "</body></html>"
)

#: Araştırma senaryolarının sorgu→URL eşlemesi; ScriptedSearchProvider bunu kullanır.
SEARCH_INDEX: dict[str, list[str]] = {
    "kuyruk": [QUEUE_GUIDE_PATH, BACKPRESSURE_PATH],
    "queue": [QUEUE_GUIDE_PATH, BACKPRESSURE_PATH],
    "outbox": [OUTBOX_GUIDE_PATH],
    "idempoten": [OUTBOX_GUIDE_PATH],
}

LOCAL_PAGES: dict[str, str] = {
    QUEUE_GUIDE_PATH: QUEUE_GUIDE_HTML,
    BACKPRESSURE_PATH: BACKPRESSURE_HTML,
    OUTBOX_GUIDE_PATH: OUTBOX_GUIDE_HTML,
}
