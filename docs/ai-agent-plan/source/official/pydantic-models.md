# Pydantic models

Kaynak kimliği: PYDANTIC-MODELS
Kaynak türü: official
Yazar veya yayıncı: Pydantic documentation team / Pydantic
Bağlantı: https://pydantic.dev/docs/validation/latest/concepts/models/
Kontrol tarihi: 2026-10-11
Sürüm kapsamı: Latest belgeleri; kurulu Pydantic major sürümü kontrol edilmeli

Bu dosya kaynağın tam kopyası değildir. Aşağıdaki parçalar bağlantılı kaynak okunarak Türkçe hazırlanmış kısa referans notlarıdır. API imzası ve sürüme bağlı ayrıntı burada yoksa asıl belge bölümünü ayrıca doğrula.

## C1 Models

Pydantic modelleri BaseModel üzerinden tanımlanır ve type annotation'larla alanlarını belirtir. Veri doğrulama ve serileştirme model sınırlarında yürütülür. Hatalı girdiler yapılandırılmış doğrulama hatalarıyla raporlanabilir.

## C2 Data conversion

Varsayılan doğrulama bazı değerleri hedef tipe dönüştürebilir. Strict mode dönüşüm davranışını sınırlamak için kullanılır. Alanların zorunluluğu ve ek alan politikası açık biçimde yapılandırılmalıdır.

## Kullanım sınırı

Kaynak referansı uygulama planının kapsamını değiştirmez. Akademik ve mühendislik sonuçları yeni model veya veri kümesine doğrudan performans garantisi vermez.
