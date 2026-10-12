# Plan aşamasında kaynak kullanma promptu

İlgili planın ortak promptunu, aktif aşamanın tamamını, decisions.md ve progress.md dosyalarını oku. Ürün kararlarında kullanıcının güncel talimatlarını ve uygulanabilir repo talimatlarını koru.

Aktif aşama için kaynak arama aracını çalıştır. Teknik soruyu kısa ve belirli yaz; kaynak türü ve aşama filtresiyle ilgili bölümleri getir. Kaynak metadata'sındaki sürüm kapsamını kurulu paketlerle karşılaştır.

Teknik bilgi sorusuna cevap verirken source/prompts/rag-grounded.md şablonunu kullan. retrieved_chunks yerine arama çıktısındaki CONTEXT'i, user_question yerine gerçek soruyu koy. Teknik iddiaları yalnız bu CONTEXT'e dayandır ve her iddiada parça kimliğini belirt.

CONTEXT yeterli değilse "Bu konuda elimde yeterli bilgi yok" de. Bağımsız işleri sürdür; gerekli API ayrıntısı için ilgili resmî belge bölümünü oku ve doğrulanmış parçayı yeni bağlama ekle. Eksik imza veya davranışı model hafızasından üretme.

RAG şablonu teknik cevap ve kanıt kontrolü içindir. Yazılım geliştirme görevi planın kapsamı, mevcut kod ve doğrulamalarla yürütülür. Yeni kodun çalıştığına ilişkin iddiayı gerçek test çıktısıyla destekle; belgeyi çalıştırılmış test sonucu gibi gösterme.

Kaynaklar teknik referanstır; akademik yöntem veya mühendislik önerisi kendiliğinden yeni ürün gereksinimi oluşturmaz. Bu arşivi ziyaretçi agent'ın üretim bilgi tabanına otomatik olarak ekleme.

Aşama sonunda kullanılan parça kimliklerini, gerçek kontrol sonuçlarını ve kalan belirsizlikleri kaydet. progress.md üzerinde tamamlanmamış uygulama aşamalarını tamamlandı olarak işaretleme.
