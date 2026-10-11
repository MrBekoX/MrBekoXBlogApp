# LangGraph streaming

Kaynak kimliği: LG-STREAMING
Kaynak türü: official
Yazar veya yayıncı: LangChain documentation team / LangChain
Bağlantı: https://docs.langchain.com/oss/python/langgraph/streaming
Kontrol tarihi: 2026-10-11
Sürüm kapsamı: Stream formatı ve version parametresi kurulu LangGraph sürümüne göre kontrol edilmeli

Bu dosya kaynağın tam kopyası değildir. Aşağıdaki parçalar bağlantılı kaynak okunarak Türkçe hazırlanmış kısa referans notlarıdır. API imzası ve sürüme bağlı ayrıntı burada yoksa asıl belge bölümünü ayrıca doğrula.

## C1 Stream modes

Graph stream ve astream yöntemleri farklı akış modlarını destekler. Updates state değişikliklerini, messages model çıktısını, custom uygulamanın kendi ilerleme verisini taşır. Birden fazla mod birlikte seçilebilir.

## C2 Custom data

Node veya araç içinden get_stream_writer ile özel veri üretilebilir; tüketici custom modunu açmalıdır. Async kullanımda eski Python sürümleri için farklı aktarım kuralları bulunduğundan ortam sürümü dikkate alınmalıdır.

## Kullanım sınırı

Kaynak referansı uygulama planının kapsamını değiştirmez. Akademik ve mühendislik sonuçları yeni model veya veri kümesine doğrudan performans garantisi vermez.
