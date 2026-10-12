# PostgreSQL 18 transaction isolation

Kaynak kimliği: PG-ISOLATION
Kaynak türü: official
Yazar veya yayıncı: PostgreSQL documentation team / PostgreSQL Global Development Group
Bağlantı: https://www.postgresql.org/docs/18/transaction-iso.html
Kontrol tarihi: 2026-10-11
Sürüm kapsamı: PostgreSQL 18

Bu dosya kaynağın tam kopyası değildir. Aşağıdaki parçalar bağlantılı kaynak okunarak Türkçe hazırlanmış kısa referans notlarıdır. API imzası ve sürüme bağlı ayrıntı burada yoksa asıl belge bölümünü ayrıca doğrula.

## C1 Read committed

PostgreSQL varsayılan izolasyon seviyesi Read Committed'dır. Bir SELECT, sorgu başladığında commit edilmiş veriyi görür. Aynı transaction içindeki sonraki SELECT, eşzamanlı commit nedeniyle farklı sonuç görebilir.

## C2 Concurrent updates

Read Committed düzeyinde UPDATE hedef satırdaki eşzamanlı işlemi bekleyebilir ve güncel satır üzerinde koşulu tekrar değerlendirir. Daha güçlü izolasyon seviyeleri farklı görünürlük ve anomali sınırları sağlar.

## Kullanım sınırı

Kaynak referansı uygulama planının kapsamını değiştirmez. Akademik ve mühendislik sonuçları yeni model veya veri kümesine doğrudan performans garantisi vermez.
