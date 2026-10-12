# RabbitMQ consumer acknowledgements and publisher confirms

Kaynak kimliği: RMQ-CONFIRMS
Kaynak türü: official
Yazar veya yayıncı: RabbitMQ documentation team / RabbitMQ
Bağlantı: https://www.rabbitmq.com/docs/confirms
Kontrol tarihi: 2026-10-11
Sürüm kapsamı: Protokol davranışı; örnek client API'lerinin major sürümü ayrıca kontrol edilmeli

Bu dosya kaynağın tam kopyası değildir. Aşağıdaki parçalar bağlantılı kaynak okunarak Türkçe hazırlanmış kısa referans notlarıdır. API imzası ve sürüme bağlı ayrıntı burada yoksa asıl belge bölümünü ayrıca doğrula.

## C1 Confirms and ACK

Publisher confirm, üretici ile broker arasındaki kabulü bildirir; consumer'ın işi tamamlamasını izlemez. Consumer ACK ayrı bir mekanizmadır ve broker'a teslimin işlendiğini bildirir. Bu iki sinyal birbirinden bağımsızdır.

## C2 Delivery tags

Delivery tag ilgili channel kapsamında geçerlidir. ACK teslimin geldiği channel üzerinden verilmelidir. Manuel ACK ve sınırlı prefetch, consumer'ın açık teslim sayısını kontrol etmeye yardımcı olur.

## Kullanım sınırı

Kaynak referansı uygulama planının kapsamını değiştirmez. Akademik ve mühendislik sonuçları yeni model veya veri kümesine doğrudan performans garantisi vermez.
