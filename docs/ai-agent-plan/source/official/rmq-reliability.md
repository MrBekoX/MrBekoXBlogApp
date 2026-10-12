# RabbitMQ reliability guide

Kaynak kimliği: RMQ-RELIABILITY
Kaynak türü: official
Yazar veya yayıncı: RabbitMQ documentation team / RabbitMQ
Bağlantı: https://www.rabbitmq.com/docs/reliability
Kontrol tarihi: 2026-10-11
Sürüm kapsamı: Belgeler broker sürümüyle eşleştirilmeli

Bu dosya kaynağın tam kopyası değildir. Aşağıdaki parçalar bağlantılı kaynak okunarak Türkçe hazırlanmış kısa referans notlarıdır. API imzası ve sürüme bağlı ayrıntı burada yoksa asıl belge bölümünü ayrıca doğrula.

## C1 Redelivery

Bağlantı hatası sırasında confirm bilgisi kaybolabilir ve üretici aynı mesajı tekrar yayınlayabilir. Consumer tekrar teslim görmeye hazır olmalıdır. Deduplication veya idempotent işleme uygulama sorumluluğudur.

## C2 Durability and routing

Önemli mesajlar için durable kuyruk ve persistent mesaj kullanılır. Publisher confirms ve consumer acknowledgements farklı teslim sorumluluklarını tamamlar. Mandatory yayınla yönlendirilemeyen mesajların fark edilmesi sağlanabilir.

## Kullanım sınırı

Kaynak referansı uygulama planının kapsamını değiştirmez. Akademik ve mühendislik sonuçları yeni model veya veri kümesine doğrudan performans garantisi vermez.
