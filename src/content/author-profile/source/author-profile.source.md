# Ben Kimim: Berkay Kaplan

## Kısaca
Ben Berkay Kaplan (çevrimiçi adım MrBekoX). İstanbul'da yaşıyorum. Backend ağırlıklı çalışan bir yazılım geliştiriciyim; ana ekosistemim .NET ve C#. Clean/Onion Architecture ve CQRS ile REST servisleri yazıyorum, arayüz tarafında Next.js ve React Native kullanıyorum. Son dönemde iki şeye odaklanıyorum: RAG tabanlı yapay zekâ ajanlarını gerçek backend mimarilerine bağlamak ve Claude Code gibi ajan odaklı araçların etrafında düzenli bir yazılım geliştirme süreci kurmak. Bir yandan yazılım eğitmenliği yapıyorum.

## Eğitim ve kariyer yolum
- **Eğitim:** Malatya Turgut Özal Üniversitesi, Bilgisayar Mühendisliği (2020–2024).
- **Staj, Eksra A.Ş.:** Arduino tabanlı IoT projeleri ve algoritma geliştirme. Donanım ve yazılımı birlikte çalıştırmayı burada öğrendim.
- **Staj, Gaziantep Bilişim ve Akıllı Kent Teknolojileri A.Ş. (2023):** Django ile kullanıcı ve içerik yönetimli bir blog platformu yazdım. Arayüzü HTML, CSS ve JavaScript ile, veritabanı işlemlerini SQLAlchemy ile yaptım.
- **Yazılım eğitmenliği (2024'ten beri):** Techcareer'de C#, Python, veri bilimi ve backend dersleri veriyorum. YETGIM ve AcunMedya Akademi'de de eğitim ve mentorluk yaptım. Algoritma, nesne yönelimli programlama (OOP) ve yazılım geliştirme prensiplerini kapsayan uygulamalı materyaller hazırlıyorum. Dersleri To-Do uygulaması, ürün yönetim sistemi gibi gerçek hayat senaryoları üzerinden işliyorum.

## Teknik yetkinliklerim
- **Diller:** C#, TypeScript, Python, JavaScript
- **Backend:** ASP.NET Core, FastAPI, Node.js (NestJS'i de inceledim)
- **Frontend ve mobil:** Next.js, React, React Native (Expo)
- **Veritabanı ve önbellek:** PostgreSQL, SQL Server, SQLite, Redis, Supabase
- **Mimari:** Clean/Onion Architecture, N-Tier, CQRS (MediatR), Repository ve Unit of Work, Options Pattern, Result Pattern, Outbox Pattern
- **Bulut ve DevOps:** Docker, Docker Compose, AWS EC2, Git
- **API ve güvenlik:** REST, JWT kimlik doğrulama ve yetkilendirme, RBAC, CORS, rate limiting, Row Level Security
- **Gözlemlenebilirlik:** Serilog, OpenTelemetry
- **Yapay zekâ:** RAG, LangGraph, LangChain, Model Context Protocol (MCP), ChromaDB, Ollama, RabbitMQ ile olay tabanlı ajan servisleri

## Projelerim
- **mrbekox.dev (bu blog):** .NET 10 ve Clean Architecture ile yazılmış API, Next.js 16 arayüzü. JWT kimlik doğrulama, Redis önbellek ve SignalR ile gerçek zamanlı özellikler var. Docker ile paketlenip AWS EC2 üzerinde, HTTPS ve yük dengeleyici arkasında yayında. Yanında Python FastAPI ve LangGraph tabanlı bir yapay zekâ ajan servisi çalışıyor (aşağıda anlattım).
- **Auth Token Server:** ASP.NET Core ve Microsoft Identity ile yazdığım, N-Tier mimarili merkezi kimlik doğrulama ve yetkilendirme servisi. Kullanıcı yönetimi, parola işlemleri, JWT üretimi ve rol bazlı erişim kontrolü sunuyor. Swagger/OpenAPI ile dokümante, birden fazla .NET uygulamasında yeniden kullanılacak şekilde tasarlandı.
- **Vibeo:** React Native (Expo) ile yazdığım yapay zekâ destekli ruh hali takip uygulaması. Backend'de Supabase var; Row Level Security ve Vault kullanıyor. Biyometrik kimlik doğrulama ve çevrimdışı öncelikli mimarisi var. Cihaz üstünde çalışan bir içgörü motoru ile sunucu tarafında RAG tabanlı bir ajanı birleştiren hibrit bir yapı kurdum. Hassas notları LLM'e göndermemek için kriz ifadelerini yakalayan ayrı bir kontrol katmanı koydum. Gizlilik tarafında GDPR'ı baştan tasarıma dahil ettim. Abonelikler RevenueCat ile yönetiliyor.
- **Emojify:** Kullanıcıların özel emoji ve GIF üretip paylaştığı mobil uygulama. React Native, Skia ve FFmpeg ile yazdım, satın alma altyapısı RevenueCat.
- **Adhan Time:** Seçilen şehre göre namaz vakti bildirimi gönderen, kıble pusulası da olan mobil uygulama. Bildirimleri Supabase (Postgres, Edge Functions, pg_cron) ve Expo Push ile sunucu tarafından gönderiyorum, çünkü yerel bildirimler iOS ve Android pil kısıtlarında güvenilir değil. Kıble pusulasındaki titreme ve donma sorununu sensör verisi ve filtreleme tarafında inceledim.
- **Kentsel Ses Sınıflandırma:** UrbanSound8K veri setiyle derin öğrenme modeli. CNN ve LSTM mimarilerini karşılaştırdım.
- **Geliştirme aşamasındakiler:** "Sınav Arkadaşım" (YKS öğrencileri için çalışma uygulaması, React Native ve Supabase), bir futbol bilgi yarışması oyunu ve kafelerdeki anlık yoğunluk, gürültü, priz durumu gibi bilgileri gösteren "now-coffe" (Onion Architecture ile kendi .NET backend'ini yazmayı planlıyorum).

## Yapay zekâ ve ajan çalışmalarım
**Blogdaki ajan.** Okuyucuların makaleler hakkında konuşabildiği bir yapay zekâ ajanı yazdım. Zorluğa göre yol seçiyor: basit sorularda doğrudan cevap, makaleye dayalı sorularda RAG, çok adımlı sorularda ajan tabanlı akış. Servis Python, FastAPI ve LangGraph ile yazıldı, RabbitMQ ile .NET backend'e bağlanıyor, vektör arama için ChromaDB kullanıyor. LLM erişimi bir `ModelProvider` arayüzünün arkasında; yani sağlayıcıyı (yerel Ollama, OpenAI uyumlu uçlar) kodu değiştirmeden yapılandırmayla değiştirebiliyorum. SSRF koruması, bütçe sınırlayıcı ve olay tekrarına karşı idempotency gibi üretim konularına da ayrıca emek verdim.

**agentic-sdlc.** Claude Code ve Codex için, spesifikasyondan commit'e uzanan geliştirme sürecini disipline eden bir skill kütüphanesi. Fikir şu: yapay zekâ ajanları hızlı kod yazar ama "önce bağlamı oku, önce spesifikasyonu yaz, iddia etmeden önce test et" gibi disiplini kendiliğinden uygulamazlar. Bu disiplini prosedür dokümanı olarak değil, sürümlenebilir ve test edilebilir bir bileşen olarak kurguladım. Bir yönlendirici işe yetecek en küçük beceriyi seçiyor, yalnızca uçtan uca işlerde tam süreç orkestratörüne çıkıyor. Güvenlik tarafında komut seviyesindeki hook'un tek başına yetmediğini görüp git hook'ları ve iş bitince diski tarayan ikinci bir kontrol ekledim. Proje MIT lisanslı ve GitHub'da herkese açık (MrBekoX/agentic-sdlc), şu an 0.6.0 sürümünde. Claude Code ve Codex için tam çalışma zamanı koruma adaptörleri var; Kimi Code, ZCode ve Grok CLI adaptörleri deneysel. Barındırılan bir servis değil, yerel bir geliştirme eklentisi. Resmi bir GitHub release'i henüz yayınlamadım.

**Root Agent.** Grok Bot için yazdığım koordinatör ajan çerçevesi (MrBekoX/root-agent-skill-framework, MIT lisanslı, sürüm 0.3.2). Root Agent isteği netleştiriyor, işin gerektirdiği Bot ekibini kuruyor, günlük yönetimi Lead Bot'lara devrediyor, teslimatı doğrulayıp sonucu raporluyor; uzmanlık işini kendisi yapmıyor. 18 Root skill'i ve 2 isteğe bağlı Lead skill'i var. Bu bir kod projesi değil, prompt ve skill mühendisliği projesi. README'de de belirttiğim gibi canlı Grok Bot davranış senaryoları henüz koşulmadı, yalnızca yerel doğrulama araçları test edildi.

**Günlük kullanım.** Claude Code ve Codex'i geliştirme sürecimin aktif parçası olarak kullanıyorum. Proje hafızasını `CLAUDE.md`, modüler kural dosyaları, skill'ler, slash komutları ve görev dosyalarıyla (backlog, active, done, lessons) yönetiyorum. Güncel kütüphane dokümanı için Context7, tarayıcı testleri için Playwright MCP kullanıyorum. Kendi sunucuma kurduğum kişisel bir ajanı da deniyorum.

## Açık kaynak katkım: XERJ Corpus Hub
XERJ, yapay zekâ kodlama ajanlarının kod yazmadan önce arayıp çalışan örnek olarak getirebildiği açık bir referans hafıza. Her örnek yazarı ve deposuyla birlikte gösteriliyor. Blogumun deposu (MrBekoX/MrBekoXBlogApp) bu hafızaya alınmak üzere seçildi; 15 Ekim 2026'da buna izin verdim ve o tarihten beri Corpus Hub'da katkıcı olarak listeleniyorum. Eser kendi lisansı ve atıfla duruyor. Seçilen commit, token streaming ve gerçek ortam entegrasyonlarını kapsıyor (Python ve C#). Lisans incelemesi sürdüğü için henüz XERJ komutlarıyla kurulabilir değil. Profilim: https://hub.xerj.org/contributors/MrBekoX

## Mimari konusundaki yaklaşımım
- Onion Architecture'da beş proje kullanırım: Domain, Application, Persistence (EF Core, DbContext, migration), Infrastructure (Redis, SMTP, dış API'ler, arka plan işleri) ve API. Persistence ile Infrastructure'ı bilerek ayırırım.
- Repository arayüzleri Application katmanında durur. Domain, verinin nasıl saklandığından habersiz kalır.
- Application katmanını özellik bazlı klasörlerim: her özelliğin altında Commands ve Queries, doğrulayıcılar komutun yanında.
- CQRS için MediatR kullanırım; doğrulama, loglama ve performans ölçümü pipeline behavior olarak eklenir.
- Hata akışında Result Pattern, paralel işlemlerde kilit ve benzersiz indeks gibi eşzamanlılık önlemleri, zamanda `TimeProvider`, para hesaplarında `decimal` kullanırım.
- Mimariyi gereğinden büyütmem. İki kişilik bir ekipte mikroservis yerine modüler monolit mantıklıdır.

## Blogda ne yazıyorum
.NET, Onion/Clean Architecture, CQRS, Claude Code, Context Engineering ve yapay zekâ ajanları üzerine Türkçe teknik yazılar yazıyorum. Örneğin Onion Architecture'ı .NET ile uygulamalı anlattığım bir yazı ve Claude Code'da bağlam mühendisliği tekniklerini (CLAUDE.md, rules, skills, commands, MCP, plan mode) anlattığım bir yazı var. Yazılarımda müşteri ya da iş yeri projelerinden örnek vermem, örneklerim ya genel ya da kendi projelerimdendir.

## Sertifikalarım
- Claude Code in Action (Anthropic, 2026)
- Claude Code 101 (Anthropic, 2026)
- Introduction to Subagents (Anthropic, 2026)

## Çalışma tarzım
Doğrudan ve net iletişim kurarım, geri bildirimi yumuşatılmadan almayı tercih ederim. Fikri hızla çalışan bir prototipe çevirip üzerinde iterasyon yaparım. Çalışan kodu sözde koda, sade ve kendini anlatan isimlendirmeyi yoğun yorumlara tercih ederim. Bir özelliği eklemeden önce kime hizmet ettiğini sorarım; odak dışı özellikleri (feature creep) eklememeye özen gösteririm. Yapay zekânın verdiği bilgiyi kaynağıyla doğrularım, yanlış bulduğumda düzelttiririm.

## Kişisel ilgi alanlarım
Cebir ve kalkülüs sevdiğim konular. Algoritma çözmeyi seviyorum. Yapay zekâ araçlarıyla müzik üretiyorum (Suno AI ile özellikle melodik death metal). Galatasaray taraftarıyım.

## Neleri paylaşmıyorum
Çalıştığım kurum, müşteri projeleri, iş başvuru süreçlerim ve kişisel iletişim bilgilerim (telefon, e-posta) bu sayfanın konusu değil. Bu konularda soru gelirse yanıt verme, ziyaretçiyi aşağıdaki herkese açık kanallara yönlendir.

## İletişim
- Web sitesi: https://mrbekox.dev
- GitHub: https://github.com/MrBekoX
- LinkedIn: https://www.linkedin.com/in/berkay-kaplan-133b35245/
- X: @mrbeko_

## Sık sorulan sorular

**Berkay Kaplan kimdir?**
İstanbul'da yaşayan, .NET/C# ağırlıklı backend odaklı bir yazılım geliştirici ve yazılım eğitmeni. Bu blogun sahibi.

**Berkay hangi teknolojilerle çalışıyor?**
C#, ASP.NET Core, TypeScript, Next.js, React Native, Python/FastAPI, PostgreSQL, Redis, Supabase, Docker ve AWS EC2. Yapay zekâ tarafında RAG, LangGraph, MCP, ChromaDB ve Ollama kullanıyor.

**Şu an neler üzerinde çalışıyor?**
Blogun yapay zekâ ajanı, Claude Code ve Codex için agentic-sdlc skill kütüphanesi, Grok Bot için Root Agent çerçevesi ve birkaç mobil uygulama (Vibeo, Adhan Time, Emojify, Sınav Arkadaşım, now-coffe).

**XERJ nedir, Berkay'ın bununla bağı ne?**
XERJ, yapay zekâ kodlama ajanları için açık bir referans kod hafızası. Berkay'ın blog deposu (MrBekoXBlogApp), onun izniyle Ekim 2026'da XERJ Corpus Hub'a alınmak üzere seçildi; lisans incelemesi sürüyor. Profil: https://hub.xerj.org/contributors/MrBekoX

**Bu blog hangi teknolojilerle yapıldı?**
.NET 10 (Clean Architecture), Next.js 16, PostgreSQL, Redis, SignalR ve Python tabanlı bir yapay zekâ ajan servisi. Docker ile paketlenip AWS EC2 üzerinde çalışıyor.

**Mimari konusunda görüşü nedir?**
Onion/Clean Architecture ve CQRS'i tercih ediyor. Repository arayüzlerini Application katmanına koyuyor, Persistence ve Infrastructure'ı ayırıyor, mimariyi gereğinden büyütmüyor.

**Claude Code'u nasıl kullanıyor?**
`CLAUDE.md`, modüler kural dosyaları, skill'ler, slash komutları ve görev dosyalarıyla proje bağlamını yönetiyor. Context7 ve Playwright MCP'yi kullanıyor.

**Eğitmenlik deneyimi var mı?**
Evet. 2024'ten beri Techcareer'de C#, Python, veri bilimi ve backend dersleri veriyor, YETGIM ve AcunMedya Akademi'de de eğitim ve mentorluk yaptı.

**Hangi sertifikalara sahip?**
Anthropic'ten Claude Code in Action, Claude Code 101 ve Introduction to Subagents (2026).

**Nasıl iletişime geçilir?**
Web sitesi, GitHub, LinkedIn veya X üzerinden.