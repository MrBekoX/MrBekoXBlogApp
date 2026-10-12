# pgvector project documentation

Kaynak kimliği: PGVECTOR
Kaynak türü: official
Yazar veya yayıncı: pgvector maintainers / pgvector project
Bağlantı: https://github.com/pgvector/pgvector
Kontrol tarihi: 2026-10-11
Sürüm kapsamı: Proje README sürümü; extension sürümü kurulumda kilitlenmeli

Bu dosya kaynağın tam kopyası değildir. Aşağıdaki parçalar bağlantılı kaynak okunarak Türkçe hazırlanmış kısa referans notlarıdır. API imzası ve sürüme bağlı ayrıntı burada yoksa asıl belge bölümünü ayrıca doğrula.

## C1 Vector search

Pgvector PostgreSQL içinde vektör saklama ve tam veya yaklaşık en yakın komşu araması sağlar. L2, inner product ve cosine gibi mesafeleri destekler. Yaklaşık arama için HNSW ve IVFFlat seçenekleri vardır.

## C2 Hybrid search

Proje belgeleri PostgreSQL full text search ile vektör aramasının birlikte kullanılabileceğini gösterir. Sonuçları birleştirmek için reciprocal rank fusion veya cross encoder seçenekleri anılır; filtre ve indeks davranışı ayrıca değerlendirilmelidir.

## Kullanım sınırı

Kaynak referansı uygulama planının kapsamını değiştirmez. Akademik ve mühendislik sonuçları yeni model veya veri kümesine doğrudan performans garantisi vermez.
