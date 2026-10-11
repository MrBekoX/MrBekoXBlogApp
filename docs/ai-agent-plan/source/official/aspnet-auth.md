# ASP.NET Core role based authorization

Kaynak kimliği: ASPNET-AUTH
Kaynak türü: official
Yazar veya yayıncı: Microsoft documentation contributors / Microsoft Learn
Bağlantı: https://learn.microsoft.com/en-us/aspnet/core/security/authorization/roles?view=aspnetcore-10.0
Kontrol tarihi: 2026-10-11
Sürüm kapsamı: ASP.NET Core 10.0 görünümü

Bu dosya kaynağın tam kopyası değildir. Aşağıdaki parçalar bağlantılı kaynak okunarak Türkçe hazırlanmış kısa referans notlarıdır. API imzası ve sürüme bağlı ayrıntı burada yoksa asıl belge bölümünü ayrıca doğrula.

## C1 Roles and policies

ASP.NET Core rol gereksinimlerini authorization attribute veya policy ile ifade eder. Gereken roller sunucunun doğruladığı kullanıcı kimliği üzerinde değerlendirilir. Yönetim işlemleri uygun authorization politikasıyla korunmalıdır.

## C2 Role combinations

Virgülle ayrılmış rol listesi alternatif roller ifade eder. Birden fazla authorization gereksinimi birlikte uygulandığında tüm koşulların sağlanması gerekebilir. Rol eşleştirme davranışı ve büyük küçük harf farkı dikkate alınmalıdır.

## Kullanım sınırı

Kaynak referansı uygulama planının kapsamını değiştirmez. Akademik ve mühendislik sonuçları yeni model veya veri kümesine doğrudan performans garantisi vermez.
