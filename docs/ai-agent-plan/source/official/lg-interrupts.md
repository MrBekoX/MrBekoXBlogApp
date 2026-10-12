# LangGraph interrupts

Kaynak kimliği: LG-INTERRUPTS
Kaynak türü: official
Yazar veya yayıncı: LangChain documentation team / LangChain
Bağlantı: https://docs.langchain.com/oss/python/langgraph/interrupts
Kontrol tarihi: 2026-10-11
Sürüm kapsamı: Python OSS; resume ve stream formatı sürüme göre kontrol edilmeli

Bu dosya kaynağın tam kopyası değildir. Aşağıdaki parçalar bağlantılı kaynak okunarak Türkçe hazırlanmış kısa referans notlarıdır. API imzası ve sürüme bağlı ayrıntı burada yoksa asıl belge bölümünü ayrıca doğrula.

## C1 Pause and resume

Interrupt yürütmeyi dış girdi beklemek için duraklatır. Kalıcı checkpointer, kararlı thread_id ve JSON olarak serileştirilebilir interrupt girdisi gerekir. Command üzerinden resume girdisi gönderilerek aynı yürütme sürdürülebilir.

## C2 Reexecution

Devam ettirilen node baştan yeniden çalışır; interrupt öncesindeki işlemler tekrarlanabilir. Yan etkiler bu yeniden yürütme davranışı dikkate alınarak tasarlanmalıdır. Resume çağrısında yeni thread kimliği farklı bir state başlatır.

## Kullanım sınırı

Kaynak referansı uygulama planının kapsamını değiştirmez. Akademik ve mühendislik sonuçları yeni model veya veri kümesine doğrudan performans garantisi vermez.
