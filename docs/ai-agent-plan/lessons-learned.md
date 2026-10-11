# Hata dersleri

Her ders kök neden, yapılan düzeltme, tekrarını yakalayan kontrol ve gelecekteki önlemi içerir. Yeni dispatch'lerde ilgili dersler görev bağlamına eklenir.

## L001 — `docs/` .gitignore'da: yeni dokümanlar sessizce commit dışı kaldı

- **Faz/yer:** W0 teslim adımı (workflow commit adımı), 2026-10-11.
- **Belirti:** Workflow log'u `W0 belgeleri: stage edilecek dosya yok`; A0/B0 raporları ve mimari belgeler commit edilmedi.
- **Kök neden:** `.gitignore:23` tüm `docs/` dizinini yok sayıyor. Mevcut plan dosyaları geçmişte force-added olduğu için tracked; ama YENİ dosyalar (phase-reports/, agent-architecture.md, integration-architecture.md) normal `git add` ile alınmaz. Ek olarak `tests/` (satır 27) de yok sayıldığından yeni test projesi oraya konulamaz (W0 Ç1 çözümü: Api.Tests kullanılır).
- **Düzeltme:** Yeni `docs/ai-agent-plan` dosyaları `git add -f` ile eklendi; W0 dokümanları ayrı bir docs commit'iyle teslim edildi.
- **Tekrarını yakalayan kontrol:** Her faz sonunda orchestrator `git log` + `git status` doğrulaması yapar; workflow `stageAndCommit` sonucunu log olarak yazdırır.
- **Gelecekteki önlem:** Dispatch promptlarında "yeni docs dosyaları force-add gerektirir" notu taşınır; commit adımlarının çıktısı log'lanıp doğrulanır (sessiz başarı varsayılmaz).

## L002 — Windows'ta `nul` çöp dosyası

- **Faz/yer:** W0+W1 workflow çalışması sırasında bir alt-agent komutu, 2026-10-11.
- **Belirti:** Repo kökünde 51 baytlık untracked `nul` dosyası (içeriği: `dir: cannot access '/b': No such file or directory`).
- **Kök neden:** Alt-agent Windows cmd sözdizimini (`dir /b > nul`) Git Bash'te çalıştırdı; MSYS ortamında `nul` aygıt adı değil gerçek dosya adıdır ve yönlendirme dosya oluşturur.
- **Düzeltme:** Dosya silindi.
- **Tekrarını yakalayan kontrol:** Faz sonunda `git status --short` kontrolü; beklenmeyen untracked dosya varlığı.
- **Gelecekteki önlem:** Dispatch promptlarında shell'in Git Bash olduğu ve cmd'ye özgü yönlendirme/aygıt adlarının (`nul`) kullanılmaması gerektiği belirtilir.

## L003 — Dispatch özetindeki sayılar plan metninin yerine geçmez

- **Faz/yer:** B1 (2026-10-11). Orchestrator'ın görev prompt'u "17 mesaj türü" yazmıştı; planın tür listesi 18 tür içeriyordu.
- **Kök neden:** Orchestrator plan tablosunu ikinci elden özetlerken ContentSnapshot çiftini tek saymış.
- **Düzeltme:** B1 uzmanı ve bağımsız inceleyici plan metninden sayımı doğrulayıp 18 türü uyguladı; sapma B1-rapor.md §1'de gerekçelendi.
- **Tekrarını yakalayan kontrol:** Bağımsız inceleyicinin "ölçütü plan metninden karşılaştır" talimatı; B1 şema ayna testleri 18 türü sabitler.
- **Gelecekteki önlem:** Tüm dispatch prompt'larına "görevdeki özet sayılar bağlam içindir; çelişki halinde plan dosyası asıl kaynaktır" kuralı eklenir.

## L004 — `BlogPost.Version` içerik revizyonu değildir

- **Faz/yer:** A0/W0 (2026-10-11); B8'i doğrudan etkiler.
- **Belirti/Yük:** Plan `article_revision` varsayar; kodda `BlogPost.Version` bir xmin rowversion concurrency token'dır (`BlogPostConfiguration.cs:32-34`), DTO'ya çıkmaz ve yayın anını tanımlamaz. Bunu revizyon sanmak içerik güncelliği hatalarına (eski snapshot'ın canlı sayılması, kaldırılan içeriğe dayanan geç sonuç) yol açardı — main prompt'un kritik entegrasyon kontrollerinden ikisi.
- **Kök neden:** Plan varsayımı ile mevcut şema anlamının çakışması; MVCC token'ını revizyon sayma yasağı plan B8'de açıktır.
- **Düzeltme:** W0 anlam sözlüğü: `article_revision` backend'in atadığı monoton yayımlanmış içerik anı kimliği; `article_content_hash` UTF-8 SHA-256. B8 kendi revizyon üretimini yazacak (D008).
- **Tekrarını yakalayan kontrol:** A0-rapor.md §5 ve W0-ortak-mimari-kararlari.md §1.4; B8 dispatch'ine bağlam olarak eklenir; B8 kabul ölçütleri (olayların ters gelmesi, kaldırma) bunu test eder.
- **Gelecekteki önlem:** Mevcut alan adları plan kavramlarıyla eşlenirken kod tanımı (configuration/annotation) okunur; isim benzerliği kanıt sayılmaz.
