# Transactional outbox pattern

Kaynak kimliği: ENG-OUTBOX
Kaynak türü: engineering
Yazar veya yayıncı: Chris Richardson / Microservices.io
Bağlantı: https://microservices.io/patterns/data/transactional-outbox.html
Kontrol tarihi: 2026-10-11
Sürüm kapsamı: Mimari desen; belirli RabbitMQ veya ORM API'si değildir

Bu dosya kaynağın tam kopyası değildir. Aşağıdaki parçalar bağlantılı kaynak okunarak Türkçe hazırlanmış kısa referans notlarıdır. API imzası ve sürüme bağlı ayrıntı burada yoksa asıl belge bölümünü ayrıca doğrula.

## C1 Transactional outbox

İş verisi değişikliği ile gönderilecek mesaj aynı veritabanı transaction'ında saklanır. Ayrı relay, kayıtlı mesajları broker'a yayınlar. Böylece veritabanı güncellemesiyle mesaj gönderimi arasındaki çift yazma problemi ele alınır.

## C2 Relay duplicates

Relay yayın yaptıktan sonra gönderildi kaydını yazamadan çökerse mesaj tekrar yayınlanabilir. Desen consumer'ın idempotent olmasını gerektirir; işleme kimliklerinin takibi tekrarların aynı iş etkisini üretmesini önlemeye yardımcı olur.

## Kullanım sınırı

Kaynak referansı uygulama planının kapsamını değiştirmez. Akademik ve mühendislik sonuçları yeni model veya veri kümesine doğrudan performans garantisi vermez.
