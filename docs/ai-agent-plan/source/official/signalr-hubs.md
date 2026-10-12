# ASP.NET Core SignalR hubs

Kaynak kimliği: SIGNALR-HUBS
Kaynak türü: official
Yazar veya yayıncı: Microsoft documentation contributors / Microsoft Learn
Bağlantı: https://learn.microsoft.com/en-us/aspnet/core/signalr/hubs?view=aspnetcore-10.0
Kontrol tarihi: 2026-10-11
Sürüm kapsamı: ASP.NET Core 10.0 görünümü

Bu dosya kaynağın tam kopyası değildir. Aşağıdaki parçalar bağlantılı kaynak okunarak Türkçe hazırlanmış kısa referans notlarıdır. API imzası ve sürüme bağlı ayrıntı burada yoksa asıl belge bölümünü ayrıca doğrula.

## C1 Hubs

SignalR hub'ları sunucu ve istemci çağrıları için yüksek seviyeli bir iletişim katmanı sağlar. İstemci hedefleri ve strongly typed hub yaklaşımı desteklenir. Hub örneği üzerinde kalıcı iş state'i tutmaya güvenilmemelidir.

## C2 Hub context

Hub dışındaki servisler IHubContext üzerinden istemcilere mesaj gönderebilir. Hub yaşam döngüsü ve dependency injection kapsamı belgelenmiştir; background servislerde uygun context ve servis ömrü kullanılmalıdır.

## Kullanım sınırı

Kaynak referansı uygulama planının kapsamını değiştirmez. Akademik ve mühendislik sonuçları yeni model veya veri kümesine doğrudan performans garantisi vermez.
