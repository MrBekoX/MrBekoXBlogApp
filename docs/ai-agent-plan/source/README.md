# Geliştirme kaynak arşivi ve RAG prompt kullanımı

Bu arşiv kodu geliştiren agent'ın teknik sorularını kaynaklara dayandırmak içindir. 30 birincil kaynak içerir: 22 resmî belge, 4 akademik çalışma ve 4 mühendislik yazısı. Her kaynağın iki kısa referans parçası vardır; toplam 60 parça aranabilir.

Burada RAG, verilen teknik soru için seçilen kaynak parçalarını CONTEXT'e yerleştirip yalnız bu bağlama dayalı cevap istemek anlamındadır. Araç LLM çağırmaz, embedding üretmez ve vektör veritabanı kurmaz. Ziyaretçi agent'ın makale RAG özelliği ayrı ürün geliştirme kapsamıdır.

## Dosyalar

- manifest.json kaynak metadata'sının kanonik kaydıdır; manifest.yaml aynı içeriğin okunabilir üretilmiş aynasıdır.
- stage-map.json 23 aşamanın kaynak eşlemesini ve başlangıç sorularını tutar; stage-map.yaml üretilmiş aynasıdır.
- official, academic ve engineering klasörleri kaynak kartlarını ve C1/C2 notlarını içerir.
- snapshots tam web sayfası kopyası değil, yerel notun hash'i ve doğrulama metadata'sıdır.
- prompts/rag-grounded.md kullanıcının SADECE CONTEXT yaklaşımını uygulayan şablondur.
- prompts/implementation-workflow.md bu şablonun kodlama aşaması içinde nasıl kullanılacağını açıklar.
- tools/search.cjs bağımlılıksız yerel arama ve prompt hazırlama aracıdır.

## Çalıştırma

Komutları docs/ai-agent-plan klasöründen çalıştır. Node.js 18 veya üstü gerekir; npm kurulumu ve API anahtarı gerekmez. Arama BM25 puanlaması, metadata eşleşmesi ve Türkçe/İngilizce anahtar kelime grupları kullanır.

```powershell
node source/tools/search.cjs verify
node source/tools/search.cjs list --stage A5
node source/tools/search.cjs search --stage A5 --query "Soru karmaşıklığına göre mod seçimi" --format prompt
node source/tools/search.cjs search --stage B4 --query "Consumer ACK ile publisher confirm arasındaki fark nedir?" --format json --output source/context-b4.json
node source/tools/search.cjs search --stage A3 --type official --query "pgvector hibrit arama" --format context
```

JSON çıktısı query, CONTEXT, seçilen parçalar, URL'ler ve kimlikleri içerir. Prompt çıktısı {retrieved_chunks} ve {user_question} yer tutucularını doldurur. Sonucu kullandığın LLM'ye veya kodlama agent'ına ver.

## Bağlam yeterliliği

matched durumu ilgili terimlerle eşleşme bulunduğunu gösterir; sorunun cevaplanabildiğini göstermez. Modelin yeterlilik değerlendirmesi promptta ayrıca istenir. Yeterli bilgi yoksa tam yanıt: Bu konuda elimde yeterli bilgi yok.

Kısa notlar tam API referansı değildir. Eksik literal imza veya sürüm davranışı için ilgili resmî belgeyi okuyup doğrulanmış metni yeni CONTEXT'e ekle. Linki görmüş olmak sayfanın bütün içeriğini bağlama eklemek anlamına gelmez.

## Kaynak işaretleri

Kaynak biçimi [RMQ-CONFIRMS#C1] gibi parça kimliğidir. JSON arama sonucu ve model cevabı birlikte biçimsel olarak kontrol edilebilir:

```powershell
node source/tools/search.cjs check-citations --context-json source/context-b4.json --answer-file answer.txt
```

Kontrol, kullanılan kimliklerin CONTEXT'te bulunmasını ve paragraflardaki kaynak işaretlerini denetler. Bir iddianın metin tarafından anlamsal olarak desteklendiğini garanti etmez. Bu görev RAG promptu ve gerektiğinde insan/kod incelemesiyle tamamlanır.

## Güncelleme ve sürümler

Kaynakların bağlantıları ve kısa notları 11 Ekim 2026 tarihinde birincil sayfalardan kontrol edildi. Rolling dokümanlar paketlerin kurulu sürümüyle eşleştirilmelidir; akademik deneyler güncel modeller için otomatik garanti değildir.

Bir not değişirse hash denetimi aramayı durdurur. Önce kaynak içeriğini gözden geçir, sonra node source/tools/rebuild-metadata.cjs komutuyla hash ve YAML aynalarını güncelle. Bu komut internete çıkmaz ve last_verified_on tarihini otomatik yenilemez.

Yeni kaynak eklerken manifest.json kaydını, not dosyasını ve aşama eşlemesini birlikte düzenle. Kaynak onay tarihi gerçek kontrol tarihini temsil etmelidir.

## Kalite kontrolleri

```powershell
node --test source/tools/search.test.cjs
node source/tools/search.cjs verify
```

Testler retrieval, aşama filtresi, boş sonuç, prompt yer tutucuları, kaynak kimlikleri ve hash bütünlüğünü kapsar. LLM çağrısı yapılmadığından model cevap kalitesi burada ölçülmez.

## Kaynak kataloğu

| Kimlik | Tür | Başlık ve bağlantı | İlgili aşamalar |
| --- | --- | --- | --- |
| LG-WORKFLOWS | official | [LangGraph workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents) | A0, A1, A2, A5, A7 |
| LG-PERSISTENCE | official | [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence) | A2, A8, B6 |
| LG-STREAMING | official | [LangGraph streaming](https://docs.langchain.com/oss/python/langgraph/streaming) | A2, A7, B5, B10 |
| LG-RAG | official | [Build a custom RAG agent with LangGraph](https://docs.langchain.com/oss/python/langgraph/agentic-rag) | A3, A4, A5, A6, A7, A10 |
| LG-INTERRUPTS | official | [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) | A8, A9, B9 |
| PY-ASYNCIO | official | [Python 3.13 coroutines and tasks](https://docs.python.org/3.13/library/asyncio-task.html) | A0, A1, A2, A6, A8, A10, B6, B7 |
| PYDANTIC-MODELS | official | [Pydantic models](https://pydantic.dev/docs/validation/latest/concepts/models/) | A1, B1 |
| FASTAPI-LIFESPAN | official | [FastAPI lifespan events](https://fastapi.tiangolo.com/advanced/events/) | B0, B11 |
| PG-ISOLATION | official | [PostgreSQL 18 transaction isolation](https://www.postgresql.org/docs/18/transaction-iso.html) | B0, B3, B4, B6, B8 |
| PGVECTOR | official | [pgvector project documentation](https://github.com/pgvector/pgvector) | A3, B8 |
| REDIS-EVICTION | official | [Redis key eviction](https://redis.io/docs/latest/develop/reference/eviction/) | B10, B11 |
| RMQ-RELIABILITY | official | [RabbitMQ reliability guide](https://www.rabbitmq.com/docs/reliability) | B0, B1, B2, B3, B5, B6, B7 |
| RMQ-CONFIRMS | official | [RabbitMQ consumer acknowledgements and publisher confirms](https://www.rabbitmq.com/docs/confirms) | B2, B3, B4, B5 |
| RMQ-QUORUM | official | [RabbitMQ quorum queues](https://www.rabbitmq.com/docs/quorum-queues) | B2, B7, B11 |
| RMQ-DLX | official | [RabbitMQ dead letter exchanges](https://www.rabbitmq.com/docs/dlx) | B2, B7 |
| RMQ-DOTNET | official | [RabbitMQ .NET client API guide](https://www.rabbitmq.com/client-libraries/dotnet-api-guide) | B0, B2, B11 |
| AIO-PIKA | official | [aio-pika quick start](https://docs.aio-pika.com/quick-start.html) | B0, B2, B4, B11 |
| ASPNET-AUTH | official | [ASP.NET Core role based authorization](https://learn.microsoft.com/en-us/aspnet/core/security/authorization/roles?view=aspnetcore-10.0) | B9, B10 |
| SIGNALR-HUBS | official | [ASP.NET Core SignalR hubs](https://learn.microsoft.com/en-us/aspnet/core/signalr/hubs?view=aspnetcore-10.0) | B5, B10 |
| DOCKER-COMPOSE | official | [Docker Compose features and uses](https://docs.docker.com/compose/intro/features-uses/) | A0, B11 |
| JSON-SCHEMA | official | [JSON Schema object reference](https://json-schema.org/understanding-json-schema/reference/object) | A1, B1, B9 |
| NEXTJS-APP | official | [Next.js App Router documentation](https://nextjs.org/docs/app) | B10 |
| AC-RAG | academic | [Retrieval Augmented Generation for Knowledge Intensive NLP Tasks](https://arxiv.org/abs/2005.11401) | A3, A4, A7 |
| AC-REACT | academic | [ReAct Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629) | A7 |
| AC-LOST-MIDDLE | academic | [Lost in the Middle How Language Models Use Long Contexts](https://aclanthology.org/2024.tacl-1.9/) | A4, A7, A10 |
| AC-SELF-RAG | academic | [Self RAG Learning to Retrieve Generate and Critique through Self Reflection](https://arxiv.org/abs/2310.11511) | A4, A7, A10 |
| ENG-AGENTS | engineering | [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) | A0, A5, A7, A9 |
| ENG-CONTEXTUAL | engineering | [Introducing Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval) | A3, A4, A7, A10 |
| ENG-CONTEXT | engineering | [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | A0, A4, A6, A7, A10 |
| ENG-OUTBOX | engineering | [Transactional outbox pattern](https://microservices.io/patterns/data/transactional-outbox.html) | B0, B3, B4, B5, B8, B9 |
