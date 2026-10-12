# FastAPI lifespan events

Kaynak kimliği: FASTAPI-LIFESPAN
Kaynak türü: official
Yazar veya yayıncı: FastAPI documentation contributors / FastAPI
Bağlantı: https://fastapi.tiangolo.com/advanced/events/
Kontrol tarihi: 2026-10-11
Sürüm kapsamı: Rolling belgeler; yalnız management/health host seçilirse uygulanır

Bu dosya kaynağın tam kopyası değildir. Aşağıdaki parçalar bağlantılı kaynak okunarak Türkçe hazırlanmış kısa referans notlarıdır. API imzası ve sürüme bağlı ayrıntı burada yoksa asıl belge bölümünü ayrıca doğrula.

## C1 Lifespan

FastAPI lifespan fonksiyonunda yield öncesi başlangıç, yield sonrası kapanış işleri yapılır. Model veya bağlantı kaynakları bu kapsamda açılıp temizlenebilir. Async context manager bu yaşam döngüsünü düzenler.

## C2 Alternative events

Belgeler uygulama başlangıç ve kapanış yönetimi için lifespan yaklaşımını önerir. Lifespan tanımlanmışsa alternatif startup ve shutdown handler'ları birlikte çalıştırılmaz; uygulama yaklaşımı tutarlı seçmelidir.

## Kullanım sınırı

Kaynak referansı uygulama planının kapsamını değiştirmez. Akademik ve mühendislik sonuçları yeni model veya veri kümesine doğrudan performans garantisi vermez.
