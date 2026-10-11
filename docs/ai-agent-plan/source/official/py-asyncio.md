# Python 3.13 coroutines and tasks

Kaynak kimliği: PY-ASYNCIO
Kaynak türü: official
Yazar veya yayıncı: Python documentation contributors / Python Software Foundation
Bağlantı: https://docs.python.org/3.13/library/asyncio-task.html
Kontrol tarihi: 2026-10-11
Sürüm kapsamı: Python 3.13

Bu dosya kaynağın tam kopyası değildir. Aşağıdaki parçalar bağlantılı kaynak okunarak Türkçe hazırlanmış kısa referans notlarıdır. API imzası ve sürüme bağlı ayrıntı burada yoksa asıl belge bölümünü ayrıca doğrula.

## C1 Task groups

Asyncio TaskGroup ilişkili görevleri bir kapsam içinde yönetir. Görevlerin tamamlanması kapsam çıkışında beklenir; hata ve iptal davranışları birlikte ele alınır. Yapılandırılmış eşzamanlılık için görev yaşam döngüsü önemlidir.

## C2 Cancellation

Task.cancel iptal isteği oluşturur; görevin kesin olarak iptal edildiği garantisini vermez. Coroutine CancelledError alabilir ve cleanup yapabilir. Belgeler iptal istisnasının tamamen bastırılmasını teşvik etmez.

## Kullanım sınırı

Kaynak referansı uygulama planının kapsamını değiştirmez. Akademik ve mühendislik sonuçları yeni model veya veri kümesine doğrudan performans garantisi vermez.
