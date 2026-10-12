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

## L005 — pytest alt-dizin conftest.py kök conftest'i gölgeler

- **Faz/yer:** A2 (2026-10-11), W2.
- **Belirti:** `tests/state/conftest.py` açılınca pytest prepend modunda `conftest` modül adını ele geçirdi; kök `tests/conftest.py`'yi import eden A1 testleri `AttributeError: module 'conftest' has no attribute 'make_context'` ile 61 test kırıldı.
- **Kök neden:** `tests/` alt dizinleri `__init__.py`'li paket değil; pytest rootdir-relative modül adı çakışıyor.
- **Düzeltme:** A2 conftest'i silip yardımcıları `tests/state/effects.py`'e taşıdı; B2'nin `tests/messaging_broker/` dizini `__init__.py`'li paket olduğu için kendi conftest'i güvenli kaldı.
- **Tekrarını yakalayan kontrol:** Tam suite koşusu (yalnız faz alt dizini değil); bütünleştirme fazındaki tam pytest kapısı.
- **Gelecekteki önlem:** Faz test dizinlerinde conftest.py ancak dizin `__init__.py`'li paketse açılır; aksi halde yardımcılar ayrı adlandırılmış modüle konur. Dispatch promptlarına eklendi.

## L006 — Paylaşılan working tree'de paralel checkout/commit çakışması

- **Faz/yer:** W2 (2026-10-11), A2 yazma penceresi.
- **Belirti:** A2'nin iki Edit çağrısı "File does not exist" ile reddedildi; untracked dosyaları geçici görünmez oldu. Reflog: `feature/ai-agent-integration → main` checkout, `d72a607` commit, geri dönüş.
- **Kök neden:** Aynı checkout'ta başka bir süreç (kullanıcının paralel çalışması — task kapsamı dışı `d72a607` main commit'i ve `6ed4cc7` web fix'i) branch değiştirdi; muhtemel `stash -u`/pop döngüsü untracked dosyaları geçici taşıdı.
- **Düzeltme:** Dosyalar zedelenmeden geri geldi; A2 edit'leri yeniden uyguladı. Hiçbir veri kaybı olmadı (reflog + A2-rapor.md §6 kanıtlı). Orchestrator commit'leri geri almadı/üzerine yazmadı.
- **Tekrarını yakalayan kontrol:** Her faz öncesi/sonrası `git branch --show-current` + `git status` + reflog kontrolü; commit'lerin beklenen ancestry'de olduğu doğrulanır.
- **Gelecekteki önlem:** Kullanıcı aynı checkout'ta çalışıyorsa branch/checkout işlemleri faz yazma pencereleriyle çakıştırılmaz; faz raporlarındaki ortam olayları orchestrator kaydına alınır; izole checkout gerekiyorsa kullanıcıyla konuşulur.

## L007 — Force-add geniş ağaç + stale index.lock: run kazası ve build-artifact kirliliği

- **Faz/yer:** W3 teslim adımı (2026-10-11/12).
- **Belirti:** Workflow sweep adımı `git add -f src` çalıştırınca ~5 dk askıda kalıp timeout ile run öldü; `.git/index.lock` artık kaldı. Önceki `git add -f` çağrıları ayrıca index'e 78 `.pyc` ve B3 commit'ine 492 `bin/obj` derleme çıktısı sokmuştu.
- **Kök neden:** (1) `-f` bayrağı `**/bin/`, `**/obj/`, `__pycache__/` gitignore kurallarını bypass etti; (2) sweep `src` kökünü — `src/frontend/blogapp-web/node_modules` dahil — force-add etti; (3) timeout edilen git süreci kilidi bıraktı; (4) commit yardımcısında try/catch ve timeout yoktu, faz sonuç raporlaması commit'lerden SONRADAYDI (salvage kaybı).
- **Düzeltme:** Stale lock silindi; .pyc ve bin/obj dosyaları `git rm --cached` ile index'ten çıkarıldı; kök `.gitignore`'a `!src/services/ai-agent-service/tests/` istisnası eklendi (tests için force-add ihtiyacını kaldırdı); git yardımcısına 120 sn timeout + try/catch eklendi; faz sonuç raporlaması commit'lerden önceye alındı; sweep dar altkümeyle force olmadan çalışır.
- **Tekrarını yakalayan kontrol:** `git ls-files | grep -E "(^|/)(bin|obj)/|\.pyc$"` boş dönmeli; her faz sonrası orchestrator `git status`/`git log` doğrulaması.
- **Gelecekteki önlem:** `-f` yalnız dar, bilinen yollar için (docs/ai-agent-plan); geniş ağaçlarda asla. Git takılırsa öncelikle index.lock kontrolü. `git rm --cached` düzeltmeleri raporda gösterilir.

## L008 — core.autocrlf, üretilmiş YAML aynalarını bozup RAG aracını kırıyor

- **Faz/yer:** W3, A5 (2026-10-11/12).
- **Belirti:** `search.cjs verify` ve `search` komutları kalıcı olarak `manifest JSON ve YAML aynaları farklı` hatası verdi; RAG CONTEXT üretimi kapandı (A5 geçici çözümle library.cjs search() fonksiyonunu doğrudan, arşive yazmadan çağırdı).
- **Kök neden:** Kaynak arşivi git'e ilk kez eklendiğinde `core.autocrlf=true`, `manifest.yaml` ve `stage-map.yaml` aynalarını CRLF'e çevirdi; araç ürettiği LF beklenen içerikle byte karşılaştırması yapıyor.
- **Düzeltme:** `node docs/ai-agent-plan/source/tools/rebuild-metadata.cjs` ile aynalar LF olarak yeniden üretildi (`verify` → valid:true); `.gitattributes`'a `docs/ai-agent-plan/source/** text eol=lf` kuralı eklendi.
- **Tekrarını yakalayan kontrol:** Faz başlarında çalıştırılan `search.cjs verify`; valid:false dönerse orchestrator rebuild-metadata çalıştırır.
- **Gelecekteki önlem:** Üretilmiş makine dosyaları (yaml aynaları) versiyonlanırken .gitattributes eol kuralı eşlik eder; kaynak arşivi değişikliğinden sonra rebuild + verify zorunlu.

## L009 — Paylaşılan broker vhost'unda eşzamanlı test koşumu çakışması

- **Faz/yer:** W4 sonrası orchestrator doğrulaması (2026-10-12).
- **Belirti:** dotnet test arka plan doğrulaması 21 başarısız gösterdi; aynı komut seri koşuda 106/106 geçti.
- **Kök neden:** Gerçek-broker testleri (B2/B3/B4/B5 .NET testleri + python messaging testleri) aynı dev vhost'unu ve kuyruk adlarını paylaşıyor; eşzamanlı suite koşumları birbirinin kuyruklarını tüketip purge ediyor. O gün üç koşum (dotnet, python tam suite, fix agent'ın pytest'i) üst üste bindi.
- **Düzeltme:** Doğrulama koşuları seri yapıldı; yeniden koşumda 106/106 yeşil.
- **Tekrarını yakalayan kontrol:** Şüpheli başarısızlıkta ilk kontrol: başka bir test koşumu/agent aynı broker'ı kullanıyor mu; seri yeniden koşum.
- **Gelecekteki önlem:** (1) Orchestrator doğrulama koşumları asla paralel başlatılmaz. (2) W5'ten itibaren her fazın broker entegrasyon testleri KENDİ test vhost'unu ve scratch DB'sini kullanır (dispatch kuralı; B4 scratch-DB deseni broker'a genelleştirildi). (3) Workflow bütünleştirme fazındaki tam suite'ler zaten seridir.
