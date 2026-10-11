# RabbitMQ dead letter exchanges

Kaynak kimliği: RMQ-DLX
Kaynak türü: official
Yazar veya yayıncı: RabbitMQ documentation team / RabbitMQ
Bağlantı: https://www.rabbitmq.com/docs/dlx
Kontrol tarihi: 2026-10-11
Sürüm kapsamı: DLX ve at least once ayarları broker sürümünde doğrulanmalı

Bu dosya kaynağın tam kopyası değildir. Aşağıdaki parçalar bağlantılı kaynak okunarak Türkçe hazırlanmış kısa referans notlarıdır. API imzası ve sürüme bağlı ayrıntı burada yoksa asıl belge bölümünü ayrıca doğrula.

## C1 Dead lettering

Dead letter exchange, belirli reddetme, süre dolumu veya kuyruk sınırı durumlarında mesajın başka exchange'e yönlendirilmesini sağlar. Routing key ve policy ayarları yeni hedefi belirler.

## C2 Dead letter reliability

Varsayılan dead letter aktarımı her durumda kayıpsız teslim garantisi vermez. Quorum queue belgeleri, iç publisher confirms kullanan at least once dead lettering seçeneğini açıklar. Gereken ayarlar hedef sürümde doğrulanmalıdır.

## Kullanım sınırı

Kaynak referansı uygulama planının kapsamını değiştirmez. Akademik ve mühendislik sonuçları yeni model veya veri kümesine doğrudan performans garantisi vermez.
