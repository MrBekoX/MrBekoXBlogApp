# Redis key eviction

Kaynak kimliği: REDIS-EVICTION
Kaynak türü: official
Yazar veya yayıncı: Redis documentation team / Redis
Bağlantı: https://redis.io/docs/latest/develop/reference/eviction/
Kontrol tarihi: 2026-10-11
Sürüm kapsamı: Rolling belgeler; kurulu Redis sürümü ve memory policy doğrulanmalı

Bu dosya kaynağın tam kopyası değildir. Aşağıdaki parçalar bağlantılı kaynak okunarak Türkçe hazırlanmış kısa referans notlarıdır. API imzası ve sürüme bağlı ayrıntı burada yoksa asıl belge bölümünü ayrıca doğrula.

## C1 Memory policy

Redis maxmemory ayarı veri için bellek sınırını belirler. Sınır aşılınca seçilen eviction politikası uygulanır. Maxmemory-policy hangi anahtarların çıkarılacağını veya yazma hatası davranışını düzenler.

## C2 Cache measurement

Belgeler hit/miss ve eviction ölçümlerinin politikayı değerlendirmede kullanılmasını önerir. Replication veya persistence buffer'ları maxmemory karşılaştırmasına dahil olmayabilir; kurulumda bu kaynaklar için alan bırakılmalıdır.

## Kullanım sınırı

Kaynak referansı uygulama planının kapsamını değiştirmez. Akademik ve mühendislik sonuçları yeni model veya veri kümesine doğrudan performans garantisi vermez.
