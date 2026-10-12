# Build a custom RAG agent with LangGraph

Kaynak kimliği: LG-RAG
Kaynak türü: official
Yazar veya yayıncı: LangChain documentation team / LangChain
Bağlantı: https://docs.langchain.com/oss/python/langgraph/agentic-rag
Kontrol tarihi: 2026-10-11
Sürüm kapsamı: Python OSS öğretici; örnek API ve model adları kurulu sürümle doğrulanmalı

Bu dosya kaynağın tam kopyası değildir. Aşağıdaki parçalar bağlantılı kaynak okunarak Türkçe hazırlanmış kısa referans notlarıdır. API imzası ve sürüme bağlı ayrıntı burada yoksa asıl belge bölümünü ayrıca doğrula.

## C1 Grade and rewrite

Retrieval sonrasında getirilen belgelerin soruyla ilgisi değerlendirilir. İlgili belgeler cevap üretimine gönderilir; ilgisiz sonuçlarda soru yeniden düzenlenip retrieval tekrar denenebilir. Bu geçişler koşullu graph kenarlarıyla uygulanır.

## C2 Generate grounded answer

Cevap üretiminde özgün soru ve getirilen bağlam birlikte kullanılır. Öğreticide bağlamın veri olarak ele alınması, içindeki talimatların izlenmemesi ve cevap bilinmiyorsa bunun belirtilmesi istenir.

## Kullanım sınırı

Kaynak referansı uygulama planının kapsamını değiştirmez. Akademik ve mühendislik sonuçları yeni model veya veri kümesine doğrudan performans garantisi vermez.
