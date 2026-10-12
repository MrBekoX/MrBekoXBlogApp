# LangGraph persistence

Kaynak kimliği: LG-PERSISTENCE
Kaynak türü: official
Yazar veya yayıncı: LangChain documentation team / LangChain
Bağlantı: https://docs.langchain.com/oss/python/langgraph/persistence
Kontrol tarihi: 2026-10-11
Sürüm kapsamı: Python OSS; checkpointer paket sürümü ayrıca kontrol edilmeli

Bu dosya kaynağın tam kopyası değildir. Aşağıdaki parçalar bağlantılı kaynak okunarak Türkçe hazırlanmış kısa referans notlarıdır. API imzası ve sürüme bağlı ayrıntı burada yoksa asıl belge bölümünü ayrıca doğrula.

## C1 Checkpointer and store

Checkpointer bir thread içindeki graph state snapshot'larını saklar. Store uygulamanın thread'ler arasında kullandığı verileri tutar. Thread kimliği graph konfigürasyonunda geçirilir; iki saklama sorumluluğu birbirinden ayrıdır.

## C2 Persistent checkpointer

Bellek içindeki saver, süreç yeniden başlayınca checkpoint'lerini kaybeder. Belgeler kalıcı kullanım için PostgreSQL, geliştirme için SQLite seçeneklerini gösterir. Üretimde uygun kalıcı checkpointer yapılandırılmalıdır.

## Kullanım sınırı

Kaynak referansı uygulama planının kapsamını değiştirmez. Akademik ve mühendislik sonuçları yeni model veya veri kümesine doğrudan performans garantisi vermez.
