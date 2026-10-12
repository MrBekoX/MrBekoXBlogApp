# A10 değerlendirme koşusu — özet

- Üretim zamanı (UTC): 2026-10-12T13:28:06+00:00
- Sağlayıcı: **test_executor**

> Bu koşu GERÇEK LLM/embedding/web-arama sağlayıcısı olmadan, tamamı is_test_double işaretli test sağlayıcılarıyla yapılmıştır (provider=test_executor). Metrikler; bu sağlayıcılar altında boru hattının yönlendirme/retrieval/atıf denetimi/bütçe-iptal davranışını ölçer. GERÇEK model sadakati, gerçek gecikme ve gerçek arama kalitesi BU RAPORDAN ÖLÇÜLEMEZ ve başarı olarak yazılmamıştır.

## Toplamlar

| Küme büyüklüğü | Koşulan | Beklenti denetimi | Geçen denetim | Geçiş oranı |
| --- | --- | --- | --- | --- |
| 61 | 61 | 232 | 231 | 0.9957 |

## Kapsam doluluğu (plan A10 kapsam listesi)

| Kapsam | Örnek sayısı |
| --- | --- |
| mod_secimi | 23 |
| web_ihtiyaci | 9 |
| retrieval | 12 |
| takip_sorulari | 3 |
| kaynak_destegi | 5 |
| secilen_metin | 3 |
| makale_disi | 2 |
| profil | 9 |
| is_birligi | 5 |
| iki_dil | 10 |
| iptal | 2 |
| butce | 4 |
| checkpoint | 8 |
| onbellek | 5 |

## 1) Görev ve mod kararlarının doğruluğu

| Metrik | Toplam | Doğru | Doğruluk | Sapmalar |
| --- | --- | --- | --- | --- |
| mode_accuracy | 27 | 27 | 1.0 | - |
| intent_accuracy | 22 | 21 | 0.9545 | r08(content_suggestion≠article_qa) |
| web_need_accuracy | 17 | 17 | 1.0 | - |
| clarification_accuracy | 2 | 2 | 1.0 | - |
| source_scope_accuracy | 6 | 6 | 1.0 | - |

## 2) İlgili bölümün bulunması

| Yol | Toplam | İsabet | İsabet oranı |
| --- | --- | --- | --- |
| Doğrudan retrieval sonda | 12 | 12 | 1.0 |
| Atıf hedefi beklenen bölüm | 12 | 12 | 1.0 |

## 3) İddia–kanıt desteği ve hatalı kaynak oranı

| Denetlenen koşu | Toplam atıf | Destekli atıf | Destek oranı | Hatalı kaynak oranı |
| --- | --- | --- | --- | --- |
| 19 | 68 | 65 | 0.9559 | 0.0441 |

## 4) Gecikme (test sağlayıcı — orkestrasyon yükü)

| Mod ailesi | Koşu | p50 (s) | p95 (s) | Ortalama (s) |
| --- | --- | --- | --- | --- |
| fast | 20 | 0.0203 | 0.0253 | 0.0163 |
| analysis | 6 | 0.0319 | 0.0352 | 0.0312 |
| deep_research | 4 | 0.0459 | 0.0545 | 0.0369 |

> Test sağlayıcıyla ölçülen değerler ORKESTRASYON süresidir (model/embedding çağrısı yapay ve anlıktır); gerçek sağlayıcı gecikmesi bu koşudan ölçülemez.

## 5) Araştırma başına araç ve model kullanımı

| Koşu | Etkin koşu | Ort. model çağrısı | Ort. arama | Ort. araç | Bütçe içi koşu |
| --- | --- | --- | --- | --- | --- |
| 4 | 4 | 1.0 | 2.0 | 0.0 | 2 |

## 6) Checkpoint'ten devam başarısı

| Senaryo | Başarılı | Başarı oranı | Başarısız |
| --- | --- | --- | --- |
| 10 | 10 | 1.0 | - |

## 7) Bütçe ve iptal davranışı

| Örnek | Beklenen davranış | Doğruluk |
| --- | --- | --- |
| 4 | 4 | 1.0 |

## Önbellek anahtar sözleşmesi (madde 5)

| Senaryo | Denetim | Geçen |
| --- | --- | --- |
| 5 | 9 | 9 |

## Örnek başına sonuçlar

| ID | Suite | Kapsam | Sonuç | Başarısız denetim |
| --- | --- | --- | --- | --- |
| r01 | routing | mod_secimi/retrieval | ✓ | - |
| r02 | routing | mod_secimi | ✓ | - |
| r03 | routing | mod_secimi | ✓ | - |
| r04 | routing | mod_secimi | ✓ | - |
| r05 | routing | mod_secimi/web_ihtiyaci | ✓ | - |
| r06 | routing | mod_secimi/web_ihtiyaci | ✓ | - |
| r07 | routing | mod_secimi/web_ihtiyaci | ✓ | - |
| r08 | routing | mod_secimi/iki_dil | ✗ | intent |
| r09 | routing | mod_secimi/iki_dil | ✓ | - |
| r10 | routing | mod_secimi | ✓ | - |
| r11 | routing | mod_secimi/secilen_metin | ✓ | - |
| r12 | routing | mod_secimi/profil | ✓ | - |
| r13 | routing | mod_secimi/is_birligi | ✓ | - |
| r14 | routing | mod_secimi/profil | ✓ | - |
| r15 | routing | mod_secimi/profil | ✓ | - |
| r16 | routing | mod_secimi | ✓ | - |
| r17 | routing | mod_secimi/web_ihtiyaci/iki_dil | ✓ | - |
| r18 | routing | mod_secimi/profil | ✓ | - |
| q01 | qa | retrieval/kaynak_destegi | ✓ | - |
| q02 | qa | retrieval/kaynak_destegi | ✓ | - |
| q03 | qa | retrieval | ✓ | - |
| q04 | qa | retrieval | ✓ | - |
| q05 | qa | retrieval | ✓ | - |
| q06 | qa | retrieval/iki_dil | ✓ | - |
| q07 | qa | retrieval/iki_dil | ✓ | - |
| q08 | qa | takip_sorulari/retrieval | ✓ | - |
| q09 | qa | takip_sorulari/iki_dil | ✓ | - |
| q10 | qa | makale_disi | ✓ | - |
| q11 | qa | makale_disi/iki_dil | ✓ | - |
| q12 | qa | mod_secimi/kaynak_destegi | ✓ | - |
| q13 | qa | secilen_metin | ✓ | - |
| q14 | qa | secilen_metin/kaynak_destegi | ✓ | - |
| q15 | qa | mod_secimi/kaynak_destegi | ✓ | - |
| q16 | qa | retrieval | ✓ | - |
| q17 | qa | retrieval/iki_dil | ✓ | - |
| q18 | qa | retrieval | ✓ | - |
| g01 | guidance | profil/mod_secimi | ✓ | - |
| g02 | guidance | profil | ✓ | - |
| g03 | guidance | profil/mod_secimi | ✓ | - |
| g04 | guidance | profil/mod_secimi | ✓ | - |
| g05 | guidance | profil | ✓ | - |
| g06 | guidance | is_birligi/checkpoint | ✓ | - |
| g07 | guidance | is_birligi/checkpoint | ✓ | - |
| g08 | guidance | is_birligi | ✓ | - |
| g09 | guidance | is_birligi/checkpoint | ✓ | - |
| s01 | research | web_ihtiyaci/butce | ✓ | - |
| s02 | research | web_ihtiyaci/iki_dil | ✓ | - |
| s03 | research | web_ihtiyaci | ✓ | - |
| s04 | research | web_ihtiyaci/butce | ✓ | - |
| l01 | lifecycle | iptal/checkpoint | ✓ | - |
| l02 | lifecycle | checkpoint/butce | ✓ | - |
| l03 | lifecycle | butce | ✓ | - |
| l04 | lifecycle | iptal/web_ihtiyaci | ✓ | - |
| l05 | lifecycle | checkpoint | ✓ | - |
| l06 | lifecycle | checkpoint | ✓ | - |
| l07 | lifecycle | checkpoint | ✓ | - |
| c01 | cache | onbellek | ✓ | - |
| c02 | cache | onbellek | ✓ | - |
| c03 | cache | onbellek/iki_dil | ✓ | - |
| c04 | cache | onbellek | ✓ | - |
| c05 | cache | onbellek/takip_sorulari | ✓ | - |

## Örnek başına bağımsız etiket gerekçeleri

- **r01 — Tekil olgu sorusu hızlı modda kalır**: Soru tek bir olguyu soruyor ve cevabın makalede hazır bulunması beklenir; çok bölüm ilişkilendirme, karşılaştırma veya dış güncellik istemi yoktur. Doğru davranış: hızlı mod, makale kapsamı, web yok.
- **r02 — Uzun ama tek bölümlü soru araştırmaya çıkmaz**: Soru fiziksel olarak uzun olsa da tek bir bölümün (kuyruk sınırı) içeriğini sorar; birden fazla bölümün ilişkilendirilmesi istenmez. Uzunluk tek başına derin araştırma gerekçesi değildir.
- **r03 — Karşılaştırma sorusu analiz moduna gider**: İki indeks yapısının karşılaştırılması, birden fazla bölümün (B-tree ve GIN bölümleri) birlikte değerlendirilmesini gerektirir; tek bölüm araması bu soruya yanlış cevap verirdi.
- **r04 — Çok bölümlü soru analiz moduna gider**: Üç ayrı bölümün içeriği aynı cevapta ilişkilendirilmelidir; bu, başlık başına arama yapan analiz akışının görevidir.
- **r05 — Açık araştırma isteği derin araştırmaya yönelir**: Kullanıcı açıkça araştırma ve alt sorular istiyor: güncel dış kanıt toplanması gerekir; makale içeriği tek başına bu isteği karşılamaz.
- **r06 — Güncellik sorusu dış kanıt ister**: 'Güncel durum' sorusu makalenin yazıldığı andaki bilgiyi değil bugünün durumunu sorar; dış kanıt olmadan cevap yanıltıcıdır.
- **r07 — Eylem sorusu güncellik sanılıp web'e çıkarılmaz**: 'Güncellerim' burada bir eylem fiilidir; kullanıcı kendi kodunu değiştirmeyi soruyor, dünyanın güncel halini değil. Web araması bu soruya gereksiz maliyet ve gecikme eklerdi.
- **r08 — İngilizce tekil soru hızlı modda kalır**: İki dil kapsamı: aynı davranış Türkçe örnekte olduğu gibi İngilizce soruda da beklenir; dil kararı değiştirmez.
- **r09 — İngilizce karşılaştırma analize gider**: Outbox ile doğrudan yayınlama iki bölümün karşılıklı değerlendirilmesini gerektirir; dil Türkçe karşılığıyla aynı davranışı üretmelidir.
- **r10 — Makaleyi bütün soran özet sorusu hızlı modda kalır**: Ana fikir sorusu bölüm ilişkilendirmesi değil bütün makalenin özetlenmesidir; getirilen herhangi bir bölüm kanıt sayılır.
- **r11 — Seçili metin açıklaması analiz moduna gider**: Kullanıcı makaleden seçtiği satırı soruyor: açıklama seçilen parçanın bağlamıyla yapılmalıdır; bu analiz akışının görevidir.
- **r12 — Yazar tanıtımı profil niyetine gider**: Yazar kimliği sorusu onaylı profil kayıtlarından deterministik yanıtlanır; model üretimine gerek yoktur.
- **r13 — İş birliği isteği iş birliği niyetine gider**: Konuk yazı isteği durum makinesiyle yürütülür; detay toplanmadan öneri üretilemez ve model üretimine gerek yoktur.
- **r14 — Makale önerisi öneri niyetine gider**: Okuma önerisi onaylı makale kataloğundan gerekçeli seçimdir; model çağrısı yerine katalog taraması yeterlidir.
- **r15 — Kişisel bağlam sorusu açıklama ister**: 'Benim projem' kullanıcının ortamına özgü bilgi gerektirir; bu bilgi yoktur ve tahminle doldurulamaz — açık soru sorulmalıdır.
- **r16 — Bağlamsız makale göndermesi belirsiz sayılır ve açıklama ister**: Soru 'bu makaledeki' diyor ama bağlamda makale yok: belirsiz durumda router modeline danışılması ve soru metniyle açıklama istenmesi doğru davranıştır; tahminle cevap üretmek değildir.
- **r17 — İngilizce güncellik sorusu dış kanıt ister**: 'Latest guidance' güncel dış kanıt ister; makalenin anlattığı ilkeyi değil bugünkü uygulama önerilerini soruyor.
- **r18 — Proje rehberi sorusu proje niyetine gider**: Portfolyo sorusu onaylı proje kayıtlarından deterministik yanıtlanır; model üretimi uydurma riski taşır.
- **q01 — Kuyruk sınırı bölümüne yönelik soru**: Cevap kuyruk sınırı bölümündedir; doğru bölümün bulunması ve cevabın o bölüme atıfla desteklenmesi beklenir.
- **q02 — Hata yönetimi bölümüne yönelik soru**: QueueFull yönetimi hata yönetimi bölümündedir; bölümün bulunması ve atıf desteği ölçülür.
- **q03 — Geri basınç bölümüne yönelik soru**: Geri basınç stratejileri ayrı bir bölümdür; ilgili bölümün bulunması beklenir.
- **q04 — GIN bölümüne yönelik soru**: JSONB/tam metin cevabı GIN bölümündedir; yanlış bölüm (B-tree) atıfı hatalı kaynaktır.
- **q05 — Kısmi indeks bölümüne yönelik soru**: Kısmi indeks bölümünün bulunması ve desteklenen cevap beklenir.
- **q06 — İngilizce outbox sorusu**: İki dil kapsamı: İngilizce soruda da bölüm bulma ve atıf desteği aynı çalışmalıdır.
- **q07 — İngilizce idempotency sorusu**: Idempotency bölümü İngilizce soruda bulunup atıflanmalıdır; cevap tekrar teslim toleransını taşımalıdır.
- **q08 — Türkçe takip sorusu önceki turun konusunu taşır**: Takip sorusu tek başına 'istisna yönetimi' der; önceki turun kuyruk bağlamıyla birlikte hata yönetimi bölümüne yönelmesi beklenir. Bu örnek konuşmaya bağlıdır: ortak önbelleğe giremez.
- **q09 — İngilizce takip sorusu**: Outbox turlarından sonra tekrar teslim sorusu idempotency bölümüne yönelmelidir.
- **q10 — Makale dışı Türkçe soru uydurmadan reddeder**: Sorunun makalede karşılığı yoktur: doğru davranış model çağrısı yapmadan, atıfsız ve açık yetersiz-bilgi yanıtıdır; uydurma cevap hata olur.
- **q11 — Makale dışı İngilizce soru uydurmadan reddeder**: İki dil kapsamı: yetersizlik yanıtı İngilizce soruda da uydurmaz ve İngilizce döner. Soru, makaleyle kazara terim örtüşmesi taşımayan biçimde seçildi: yeterlilik kapısı belirteç-örtüşmesine dayalıdır ve tek işlev sözcüğü ('without' gibi) bile İngilizce soruyu üretime sokabiliyor — bu gözlem raporda ayrı kaydedilmiştir.
- **q12 — Genel özet sorusu bütün makaleyi kanıtlar**: Ana fikir sorusunda getirilen herhangi bir bölüm kanıttır; cevap tek model çağrısıyla üretilip makale bölümleriyle atıflanmalıdır.
- **q13 — Makaleden seçilen satır doğrulanmış kaynak olur**: Seçili metin makalede mevcut: doğru davranış seçimi doğrulanmış kaynak olarak kullanmak ve 'bulunamadı' notu üretmemektir.
- **q14 — Makalede olmayan seçim dürüstçe bildirilir**: Seçilen metin makaleden değil: aynen kaynak gibi kullanmak yanlış kanıt üretir; doğru davranış 'makalede bulunamadı' notudur.
- **q15 — Çok bölümlü soru başlıklarla cevaplanır**: Analiz akışı soruyu başlıklara ayırıp başlık başına arar; üç bölümün de cevapta temsil edilmesi ve tek üretim çağrısı beklenir.
- **q16 — Bakım bölümüne yönelik soru**: Bakım komutları Bakım ve maliyet bölümündedir; bölüm bulma + atıf beklenir.
- **q17 — İngilizce 'neden olaylar' sorusu**: Giriş bölümündeki eventually-consistency ödünü bulunmalı ve atıflanmalıdır.
- **q18 — B-tree bölümüne yönelik soru**: Aralık/sıralama cevabı B-tree bölümündedir; gözlemlenebilirlik değil doğru bölüm atıflanır.
- **g01 — Profil sorusu onaylı kayıttan model çağrısız yanıtlanır**: Yazar tanıtımı onaylı profil kaydının deterministik kompozisyonudur; model çağrısı yoktur ve cevap kayıttaki ismi taşır.
- **g02 — Ücret sorusu uydurulmaz, açık soru döner**: Ücret kayıtlı profil verisi değildir; doğru davranış needs_input terminaliyle açık soru sormaktır, sayı uydurmak değil.
- **g03 — Proje sorusu onaylı kayıtlardan listeler**: Proje rehberi onaylı kayıtların listesidir; cevap kayıttaki proje adını taşımalıdır.
- **g04 — Öneri onaylı katalogdan kaynak bağlantılı verilir**: Öneri uydurma URL taşımaz; katalogdaki doğrulanmış bağlantıyla gelir.
- **g05 — Katalogsuz öneri dürüst kısmi sonuç verir**: Katalog bağlı değilken öneri uydurulmaz; kullanılamazlık notuyla kısmi sonuç doğru davranıştır.
- **g06 — İş birliği ilk adımda eksik detayı sorar ve checkpoint'e yazar**: İş birliği hazırlığı eksik alanlarda DURUR; sorular sorulur ve durum checkpoint'e yazılır — model tahminiyle devam etmez.
- **g07 — Eksik alan cevapları checkpoint'ten devamla öneri üretir**: Zorunlu alanlar tamamlandığında makaleye bağlı öneri üretilir ve onay sorusuyla needs_input'ta durulur; state checkpoint'te günceldir.
- **g08 — Doğrulanmamış onay reddedilir**: Onay yalnız backend'in doğrulanmış ValidatedActionResult'ıyla işlenir; sonucuz onay başarı varsayamaz ve reddedilir.
- **g09 — Doğrulanmış sonuçla iş birliği kapanır**: Kayıt başarısı yalnız doğrulanmış backend sonucundan sonra bildirilir; agent kendi başına kayıt atmaz.
- **s01 — Türkçe araştırma dış kanıtlarla kısmi/tam rapor üretir**: Araştırma akışı arama yapmalı, en az bir dış sayfa okuyup kanıt elemeli ve model çağrılı raporu dış kaynak atıflarıyla döndürmelidir; tüm kullanım profil sınırlarında kalmalıdır.
- **s02 — İngilizce araştırma dış kanıtlarla rapor üretir**: İki dil kapsamı: İngilizce araştırma aynı araç disipliniyle çalışmalıdır.
- **s03 — Web bağlı değilken dürüst kullanılamazlık notu**: Karar web gerektirir ama araçlar bağlı değildir: tek model çağrısıyla içerik üretilir ve dış kanıt toplanamadığı AÇIKÇA raporda bildirilir.
- **s04 — Arama bütçesi sıfırken araştırma kısmi terminalde kalır**: Arama bütçesi bitince akış çökmek veya bulgu uydurmak yerine kayıtlı hata notuyla KISMİ rapor üretir. Ölçüm notu: BudgetPolicy arama sınırını profil 0'da bile en az 1'e sabitler (from_budget_profile: max(profile.max_web_search_calls, 1)); 'sıfır arama' politika düzeyinde ifade edilemez, dolayısıyla ölçülen davranış 'kota dolunca zarif kısmi terminal'dir (rapor gözlemi F3).
- **l01 — İptal sonrası checkpoint'ten devam modu korur**: İptal edilmiş çalışma cancelled terminaliyle biter; checkpoint'ten devam rota kararını YENİDEN hesaplamaz, aynı modla tamamlanır.
- **l02 — Deadline dolan devam çalışması timeout ile biter**: Devam ettirilen çalışmaya verilen kalan süre dolduğunda süreç asılı kalmaz; anlaşılır timeout terminali üretilir.
- **l03 — Token bütçesi tükenince anlaşılır bütçe hatası**: Sunucu bütçesi token rezervasyonuna yetmez: akış çökmez, bütçe hatasıyla terminal sonuç döner.
- **l04 — Araştırma iptali cancelled terminaliyle döner**: İptal sinyali araştırma graph'ında da cancelled terminaline eşlenir; kısmi rapor yanıltıcı olurdu.
- **l05 — İçerik ilerlemişse kanıtlar yeniden kullanılmadan sürülür**: Checkpoint sonrası makale revizyonu ilerledi: tam yeniden kullanım yanlış olur; güncel bağlamla sürülmesi ve bunun ilerleme olayında bildirilmesi beklenir.
- **l06 — Geri gitmiş içerikte checkpoint devamı reddedilir**: Checkpoint revizyonundan geri bir bağlama devam etmek bayat kanıt üretir; doğru davranış anlaşılır stale_snapshot reddidir.
- **l07 — Başka yürütme kimliğiyle devam reddedilir**: Checkpoint kararlı yürütme zincirine bağlıdır; farklı kimlikle gelen devam isteği anlaşılır validation_error ile reddedilir.
- **c01 — Aynı içerik+istek aynı anahtarı üretir**: Aynı makale içeriği, dili ve kapsamıyla sorulan aynı soru aynı anahtarı üretmelidir; aksi halde önbellek boşuna ıska yapar.
- **c02 — İçerik hash'i anahtara girer**: Makale revizyonu ilerleyince içerik hash'i değişir ve eski cevap anahtarı geçersiz kalmalıdır; aksi halde bayat cevap paylaşılır.
- **c03 — Dil anahtara girer**: Aynı sorunun Türkçe ve İngilizce cevapları farklıdır; dil anahtarda olmalıdır.
- **c04 — Soru kapsamı anahtara girer**: Genel, makale ve seçim kapsamlı istekler farklı bağlam taşır; kapsam anahtarda yoksa seçim-bağlı cevap genel anahtarla paylaşılır.
- **c05 — Yapılandırma sürümü anahtarı değiştirir; konuşmalı sorular ortak önbelleğe girmez**: Prompt/şema sürümü değişince anahtar değişmelidir; konuşma geçmişi veya seçili metin taşıyan istekler ise ORTAK önbelleğe hiç girmemelidir.
