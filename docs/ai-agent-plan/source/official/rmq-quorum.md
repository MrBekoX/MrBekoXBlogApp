# RabbitMQ quorum queues

Kaynak kimliği: RMQ-QUORUM
Kaynak türü: official
Yazar veya yayıncı: RabbitMQ documentation team / RabbitMQ
Bağlantı: https://www.rabbitmq.com/docs/quorum-queues
Kontrol tarihi: 2026-10-11
Sürüm kapsamı: Quorum seçenekleri hedef broker sürümünde kontrol edilmeli

Bu dosya kaynağın tam kopyası değildir. Aşağıdaki parçalar bağlantılı kaynak okunarak Türkçe hazırlanmış kısa referans notlarıdır. API imzası ve sürüme bağlı ayrıntı burada yoksa asıl belge bölümünü ayrıca doğrula.

## C1 Quorum

Quorum queue replikasyonunda çoğunluk, kuyruğun durumu üzerinde anlaşır. Güvenilirlik değerlendirmesi replica sayısı ve erişilebilir çoğunluğa bağlıdır. Tek düğüm, düğüm kaybına karşı yüksek erişilebilirlik sağlamaz.

## C2 Data safety

Publisher confirm alınmış mesajın korunması, quorum üyelerinin çoğunluğunun kalıcı biçimde kaybedilmemesi koşuluna bağlıdır. Belgeler veri güvenliği ile erişilebilirlik arasındaki bu tercihleri açıklayarak cluster tasarımını yönlendirir.

## Kullanım sınırı

Kaynak referansı uygulama planının kapsamını değiştirmez. Akademik ve mühendislik sonuçları yeni model veya veri kümesine doğrudan performans garantisi vermez.
