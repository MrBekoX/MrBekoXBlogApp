# JSON Schema object reference

Kaynak kimliği: JSON-SCHEMA
Kaynak türü: official
Yazar veya yayıncı: JSON Schema documentation contributors / JSON Schema
Bağlantı: https://json-schema.org/understanding-json-schema/reference/object
Kontrol tarihi: 2026-10-11
Sürüm kapsamı: Draft 2020-12 ve belge örneklerindeki draft farkları doğrulanmalı

Bu dosya kaynağın tam kopyası değildir. Aşağıdaki parçalar bağlantılı kaynak okunarak Türkçe hazırlanmış kısa referans notlarıdır. API imzası ve sürüme bağlı ayrıntı burada yoksa asıl belge bölümünü ayrıca doğrula.

## C1 Object properties

Properties alan tanımlarını, required zorunlu alanları belirler. Bir alanın properties içinde yer alması tek başına zorunlu olduğu anlamına gelmez. Ek alan kabulü additionalProperties üzerinden düzenlenebilir.

## C2 Schema composition

AdditionalProperties yalnız kendi subschema'sında tanımlanan alanları tanır; allOf ile kapalı şema genişletilirken beklenmeyen reddetmeler oluşabilir. UnevaluatedProperties farklı subschema sonuçlarını dikkate almak için açıklanır.

## Kullanım sınırı

Kaynak referansı uygulama planının kapsamını değiştirmez. Akademik ve mühendislik sonuçları yeni model veya veri kümesine doğrudan performans garantisi vermez.
