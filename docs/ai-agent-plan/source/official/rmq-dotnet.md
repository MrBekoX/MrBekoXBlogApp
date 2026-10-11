# RabbitMQ .NET client API guide

Kaynak kimliği: RMQ-DOTNET
Kaynak türü: official
Yazar veya yayıncı: RabbitMQ documentation team / RabbitMQ
Bağlantı: https://www.rabbitmq.com/client-libraries/dotnet-api-guide
Kontrol tarihi: 2026-10-11
Sürüm kapsamı: İncelenen rehber client 7.x API'lerini açıklar; paket major sürümü doğrulanmalı

Bu dosya kaynağın tam kopyası değildir. Aşağıdaki parçalar bağlantılı kaynak okunarak Türkçe hazırlanmış kısa referans notlarıdır. API imzası ve sürüme bağlı ayrıntı burada yoksa asıl belge bölümünü ayrıca doğrula.

## C1 Connection lifetime

RabbitMQ .NET bağlantıları ve channel'ları uzun ömürlü kullanılır. Her mesaj için yeni bağlantı açılması önerilmez. Channel paylaşımı ve publisher eşzamanlılığı istemcinin güvenlik kurallarına göre yönetilmelidir.

## C2 Consumer memory

Client 7.x rehberinde payload ReadOnlyMemory olarak sunulur. Consumer callback'i bittikten sonra kullanılacak veri callback sırasında kopyalanmalı veya ayrıştırılmalıdır. Eski major sürüm örnekleri aynı API kabul edilmemelidir.

## Kullanım sınırı

Kaynak referansı uygulama planının kapsamını değiştirmez. Akademik ve mühendislik sonuçları yeni model veya veri kümesine doğrudan performans garantisi vermez.
