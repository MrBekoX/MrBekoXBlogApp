# A6 Faz Raporu — Web arama ve kaynak değerlendirme araçları

- **Faz:** A6 (search_web, read_source, extract_text, assess_source ayrı adaptörlerde; plan A6 kaynak modeli; ağ ve içerik kontrolleri)
- **Tarih:** 2026-10-12
- **Branch / temel:** `feature/ai-agent-integration` (başlangıç HEAD `72426aa`)
- **Rol:** A6 implementasyon agent'ı
- **Okunan girdiler:** `01-agent-gelistirme-plani.md` "Aşama A6" (satır 325–350, satır satır), `main-prompt.md`, `decisions.md` (D001–D014), `progress.md`, `lessons-learned.md` (L001–L008), `phase-reports/A5-rapor.md`, mevcut kod: `agent_core/ports/{web_search,source_reader,budget,cancellation}.py`, `agent_core/models/{sources,base,__init__}.py`, `agent_core/budget/{guard,policy}.py`, `agent_core/state/events.py`, `agent_core/adapters/{config.py,test_doubles/*}`, `tests/{conftest.py,intake/*,routing/*,messaging_broker/*}`, RAG CONTEXT: `search.cjs verify` → `valid:true` (30 kaynak) + stage A6 prompt ([PY-ASYNCIO#C1], [PY-ASYNCIO#C2], [LG-RAG#C1], [LG-RAG#C2])
- **Yazılan dosyalar:** yalnız izinli kapsam — `app/agent_core/web/**` (9 yeni dosya), `tests/web/**` (8 yeni dosya), bu rapor. Port dosyalarında (`ports/web_search.py`, `ports/source_reader.py`) imza kırıcı değişiklik YAPILMADI — mevcut iki port yeni adaptörlerce olduğu gibi gerçeklendi; genişletme gerekmediği için additive değişiklik de gerekmedi. `models/sources.py` (SourceReference) sahiplik DIŞI olduğundan DEĞİŞTİRİLMEDİ (bkz. §6 S1). Commit/push/reset yapılmadı.

## 1. Ortam ve ön koşul doğrulaması

| Kontrol | Komut / yöntem | Sonuç |
| --- | --- | --- |
| Branch / L006 | `git branch --show-current`, `git status --short` | `feature/ai-agent-integration`; checkout/branch/stash İŞLEMİ YAPILMADI. Çalışma ağacında paralel W4 işi görüldü: `app/messaging/{__init__,job_store,outbox}.py` (M), `migrations/versions/20261012_0002_run_event_sequences.py` (untracked, B5), `tests/events/` (untracked) — DOKUNULMADI |
| RAG aracı (L008 sonrası) | `node docs/ai-agent-plan/source/tools/search.cjs verify` | `valid:true`, 30 kaynak, 60 parça |
| A6 teknik CONTEXT | `search.cjs search --stage A6 --query "Web kaynak okuma araçları ve asyncio timeout iptal" --format prompt` | 4 parça: [PY-ASYNCIO#C1] TaskGroup, [PY-ASYNCIO#C2] CancelledError bastırılmaz, [LG-RAG#C1/C2] bağlam veridir |
| Python / pytest | `python --version`, `python -m pytest --version` | 3.13.9 / 8.3.3 |
| L002 | `ls D:/MrBekoXBlogApp/nul` | dosya yok; cmd yönlendirmesi kullanılmadı |
| L005 | `tests/web/` `__init__.py`'li paket, conftest.py AÇILMADI | yardımcılar `web_helpers.py` adlı BENZERSİZ modülde; testler paket içi göreli içe aktarım kullanır (`tests/intake` örneği) |
| Sır taraması | `grep -rnE "(api[_-]?key\|secret\|password\|token)\s*=\s*['\"][A-Za-z0-9+/]{8,}" app/agent_core/web tests/web` (anahtar adı alanları hariç) | eşleşme yok; arama anahtarı yalnız `api_key_env` (ortam değişkeni ADI) ile gösterilir, değer çağrı anında `os.environ`'dan okunur |
| L002/L007 artık kontrolü | `git status --short -uall` (web dizinleri) | yalnız izinli 17 .py dosyası; `__pycache__` ignore'lu (`.gitignore:1`), pyc yok |

## 2. Oluşturulan yapı

```
app/agent_core/web/          # A6 araç katmanı (agent'ın dış araştırma araçları; backend haberleşmesi DEĞİL)
├── __init__.py              # dışa açılım
├── models.py                # WebSourceRecord (plan A6 kaynak modeli), ExtractedText, FetchedContent,
│                            # SourceEvidence, SourceAssessment, ExtractionStatus/SourceType/EvidenceKind/DuplicateKind
├── settings.py              # WebToolSettings: süre/yönlendirme/boyut/içerik türü sınırları; sır taşımaz
├── ssrf.py                  # UrlGuard: URL doğrulama + DNS çözümleme + özel/loopback/link-local/metadata engeli
├── fetch.py                 # HttpFetcher: bağımlılıksız asyncio HTTP/1.1 istemcisi (stdlib asyncio streams)
├── extract.py               # TextExtractor (extract_text): HTML→metin, metadata, durum raporlama
├── assess.py                # SourceAssessor (assess_source): tür, öncelik, kopya, bağımsızlık
├── search.py                # HttpWebSearchProvider (search_web): JSON uç nokta; anahtar yalnız env'den
└── tools.py                 # SearchWebTool / ReadSourceTool (bütçeli), ExtractTextTool / AssessSourceTool (yerel),
                             # HttpSourceReader (DONMUŞ SourceReader portu), build_web_tools, record_to_evidence

tests/web/                   # A6 test sahipliği (__init__.py'li paket; L005: conftest yok)
├── web_helpers.py           # MockWebServer (asyncio), CapacityBudgetStore, ScriptedSearchProvider, kalıplar
├── test_web_ssrf.py         # 24 test (şema, literal IP, DNS, rebinding, redirect, pin, test-bayrağı sınırı)
├── test_web_fetch.py        # 21 test (kodlama, redirect, durum eşlemesi, sınırlar, iptal, IPv6 Host)
├── test_web_extract.py      # 16 test (metadata, tarih uydurmama, boş/engel/CAPTCHA, kaynak-içi talimat)
├── test_web_assess.py       # 15 test (tür, öncelik, kopya, yayıncı grubu, snippet bayrağı)
├── test_web_tools_budget.py # 24 test (bütçe olayları, retry, port uyumu, JSON sağlayıcı, uçtan uca güncellik)
├── test_web_real_sources.py # 3 test (GERÇEK ağ: rabbitmq.com + docs.python.org + gerçek DNS)
└── __init__.py
```

## 3. Plan gereksinimlerinin karşılanması (plan satır 335–350)

| Plan gereksinimi | Uygulama | Kanıt (test) |
| --- | --- | --- |
| 4 sorumluluk AYRI adaptörlerde | `search.py`, `fetch.py`+`tools.ReadSourceTool`, `extract.py`, `assess.py` | her modülün kendi test dosyası |
| Kaynak modeli: URL, final URL, başlık, yayıncı, varsa yayın tarihi, erişim tarihi, içerik hash'i, çıkarma durumu, kaynak türü, kanıtlar | `WebSourceRecord` alan kümesi birebir; kanıtlar `SourceEvidence` (full_page + page_metadata) | `test_read_success_produces_record_with_plan_fields` |
| Bulunmayan tarih UYDURULMAZ | `published_at: UtcDatetime \| None`; meta yoksa/bozuksa `None` + assess notu "uydurulmadı" | `test_missing_date_is_not_fabricated`, `test_invalid_date_string_is_ignored_not_fabricated` |
| Snippet tam sayfa sayılmaz | `WebSourceRecord.full_page_read`; snippet'ten gelen sonuç `False` + not; `preferred=False` | `test_snippet_only_source_is_flagged_not_preferred`, uçtan uca test |
| Benzer/kopya ayrıştırma, bağımsız çeşitlilik | `content_hash` eşitliği = exact; kelime 5-gram Jaccard ≥ 0.8 = near; eTLD+1 yayıncı grubu sayımı | `test_exact_duplicate…`, `test_near_duplicate…`, `test_distinct_publisher_groups_counted` |
| Resmî belge/araştırma/proje önceliği | `priority_rank` 0/1 + `preferred`; tür kural sınıflaması | `test_priority_rank_and_preferred`, gerçek sayfalarda `official_docs rank=0` |
| Yalnız HTTP/HTTPS | şema izin listesi | `test_parse_rejects_non_http_schemes` (file/ftp/javascript/data/gopher) |
| DNS + yönlendirme dahil özel/loopback/link-local/metadata ENGELİ | `UrlGuard.resolve` tüm çözümlenen adresleri denetler; bağlantı doğrulanmış IP'ye PİNLENİR (TOCTOU kapalı); her redirect adımı parse+resolve'dan yeniden geçer | `test_parse_blocks_literal_private_and_metadata_addresses` (12 adres), `test_resolve_blocks_forbidden_dns_answers` (6 vektör: metadata, private, CGNAT, IPv4-eşlenmiş, NAT64, link-local), `test_redirect_to_metadata_ip_blocked_at_second_hop`, `test_redirect_rebinding_via_dns_blocked` |
| Süre/yönlendirme/boyut/içerik türü sınırları | connect/header/body-idle/resolver/total timeout; max_redirects; Content-Length+chunked+decompress üst sınırı; medya türü izin listesi | `test_slow_response_times_out`, `test_redirect_loop_hits_limit`, `test_size_limit_exceeded_by_content_length`, `test_unsupported_content_type_rejected` |
| Erişim engeli/CAPTCHA/çıkarılamayan raporlama | HTTP 401/403 → `provider_error` "erişim engellendi" (retry yok); HTTP 200 sayfalarda `extraction_status` ∈ {blocked, captcha_suspected, empty, unsupported_content_type, decode_error} | `test_status_mapping[403/401/429]`, `test_captcha_page_is_reported`, `test_access_denied_page_is_reported_blocked`, `test_empty_body_reports_empty_status` |
| Kaynak talimatları veri olarak işle | Çıkarıcı metne koşullu dallanmaz; talimat metni olduğu gibi `text`'e taşınır; HTML yorumu metne sızmaz | `test_in_page_instructions_are_data_not_commands`, `test_instructions_in_html_comment_do_not_leak_into_text` ([LG-RAG#C2] ilkesi) |
| Okuma aracına sır TAŞINMAZ | `HttpFetcher`/`TextExtractor` anahtar parametresi yok; anahtar yalnız `HttpWebSearchProvider`'da `api_key_env` üzerinden, yalnız operatör uç noktasına başlık olarak | `test_search_provider_sends_api_key_from_env_without_leaking`, `test_search_provider_missing_api_key_is_config_error` (değer mesaja girmez) |
| Timeout/oran sınırı/kesinti SINIRLI retry | retry kararları `BudgetGuard.guarded`'ta (politika `max_attempts_per_action`), araçlarda üstel geri çekilme (sınırı `retry_backoff_cap_s`), 429/5xx/timeout `retryable=True` | `test_search_retryable_failure_then_success_records_both_attempts`, `test_search_retry_exhaustion_respects_policy` |
| Her dış araç denemesi bütçede | `SearchWebTool`→`WEB_SEARCH_CALL`, `ReadSourceTool`→`SOURCE_PAGE_READ`; retry denemeleri ayrı `event_id` (`action_id#attempt`); `budget_exhausted` çağrı ÖNCESİ, olay yok; extract/assess yerel → olay yok | §4 bütçe testleri |
| Port sözleşmeleri (DONMUŞ) | `HttpWebSearchProvider` = `WebSearchProvider`; `HttpSourceReader` = `SourceReader` (runtime Protocol `isinstance` kanıtlı) | `test_http_source_reader_satisfies_port_protocol` |

### Kabul senaryoları (plan A6 kabul ölçütü) → test

| Senaryo | Test |
| --- | --- |
| kısa güncel soru | `test_short_freshness_question_end_to_end` (arama→okuma→değerlendirme, resmî belge önceliği, tarih uydurulmaz, 2 bütçe olayı) |
| sayfa çıkarma hatası | `test_empty_body_reports_empty_status`, `test_only_scripts_reports_empty_status`, `test_unsupported_content_type_is_reported` |
| engelli adres | SSRF dosyasının 24 testi; ayrıca engel/CAPTCHA: `test_access_denied_page_is_reported_blocked` |
| yönlendirme | `test_fetch_follows_redirect_chain`, `test_redirect_loop_hits_limit`, `test_redirect_to_metadata_ip_blocked_at_second_hop` |
| boş kaynak | `test_read_empty_page_reports_empty_status_with_success_event`, `test_http_source_reader_maps_empty_to_not_found` (port katmanı) |
| kaynak-içi talimat | `test_in_page_instructions_are_data_not_commands` |
| bütçe yansıması | `test_search_success_records_single_budget_event` … `test_read_http_block_records_failed_budget_event` |

## 4. Gerçek çalıştırılan kontroller ve sonuçlar

| # | Komut (tam) | Sonuç |
| --- | --- | --- |
| 1 | **GATE:** `python -m pytest src/services/ai-agent-service/tests/web -q` (repo kökünden) | **127 passed** in 5.7s (mock 124 + gerçek ağ 3) |
| 2 | `python -m pytest src/services/ai-agent-service/tests -q` (tam suite regresyon) | 1 failed, **523 passed**, 1 skipped in ~104s. **Başarısız test benim değil:** `tests/intake/test_migrations_smoke.py::test_agent_schema_is_at_alembic_head` — aynı checkout'ta B5'in sürmekte olan W4 işi (`20261012_0002_run_event_sequences.py` untracked + `tests/events/` + `app/messaging` düzenlemeleri) ara durumundadır; `app/agent_core/web` veya `tests/web` bu yola hiç dokunmaz (bkz. §6 R1). skipped: `test_messaging_contracts_fixtures.py:58` (bilinen, şema kontrolü uygulanmayan bozuk gövde durumu) |
| 3 | `python -m compileall -q app/agent_core/web tests/web` | hata yok |
| 4 | Gerçek sayfa okuması (test kanıtı, canlı çıktı): `https://www.rabbitmq.com/docs/confirms` | `title='Consumer Acknowledgements and Publisher Confirms \| RabbitMQ'`, `status=ok`, `text_chars=29078`, `hash=9ee72819ca30f000…`, `published_at=None` (sayfada yok → uydurulmadı), `assess=official_docs rank=0 preferred group=rabbitmq.com` |
| 5 | Gerçek sayfa okuması: `https://docs.python.org/3.13/library/asyncio-task.html` | `title='Coroutines and tasks — Python 3.13.16 documentation'`, `status=ok`, `text_chars=43450`, `hash=9e43f8505489c2b6…`, `assess=official_docs rank=0 group=python.org` |
| 6 | Gerçek DNS denetimi: `guard.resolve` (rabbitmq.com) | dönen tüm adresler public (private/loopback/link-local yok) |

SSRF test kanıtı (özet — tam liste `tests/web/test_web_ssrf.py`): literal hedeflerden 12 engellenen vektör (127.0.0.1, ::1, ::ffff:127.0.0.1, 0.0.0.0, 10/8, 172.16, 192.168, **169.254.169.254**, 100.64/10, 198.18/15, fe80::, fd00::); DNS yanıtlarından 6 vektör (metadata, private, CGNAT, `::ffff:10.0.0.7`, NAT64 `64:ff9b::a00:1`, link-local); redirect hedefi metadata → 2. adımda engel; DNS rebinding senaryosu → adım başına yeniden çözümleme engeli; çözümlenen IP'ye pin + Host başlığının korunması kanıtlandı.

## 5. Tasarım kararları (bu fazın uygulama kararları)

1. **Bağımlılıksız asyncio HTTP/1.1 istemcisi:** pyproject sahipliğim dışında ve ortamda httpx/aiohttp kurulu olsa da bildirilmemiş bağımlılık eklemek istemedim; stdlib `asyncio.open_connection` + elle HTTP/1.1 (gzip/deflate, chunked, Content-Length) yazıldı. Bu, DNS'i kendi `getaddrinfo`'muzla çözüp doğrulanan IP'ye pinlemeyi ve faz bazlı timeout'ları mümkün kılar (SSRF stratejisinin ön koşulu).
2. **Pin + adım-başı yeniden çözümleme:** "yeniden çözümlü redirect koruması" her yönlendirme adımını `parse → resolve → engel listesi`'nden yeniden geçirir; bağlantı DOĞRULANMIŞ IP'ye pinlenir, böylece çözümleme-bağlantı arası DNS değişimi (TOCTOU/rebinding) engellenir. `test_resolved_ip_pinned_and_host_header_preserved`.
3. **`allow_loopback` granüler test bayrağı:** İlk taslakta `allow_private_addresses` vardı; bu bayrak metadata hedefini de açacağı için redirect-to-metadata testi anlamsızlaşırdı. Bayrak `allow_loopback` olarak daraltıldı: yalnız 127.0.0.0/8 + ::1 ve yalnız `environment="test"`'te (`config_error` yoksa) — private/link-local/metadata testte bile engelli. (test double üretimde yasak kuralıyla aynı desen).
4. **Bütçe olayı semantiği (A2 ile hizalı):** geçersiz sorgu/URL çağrı ÖNCESİ reddedilir → olay yok; şema reddi `ReadSourceTool`'da `fetcher.parse_url` ile rezervasyondan önce yapılır; DNS engeli/HTTP hatası DENEEMEDİR → `failed` olayı; extract_text/assess_source yereldir → olay yok (plan kuralı "dış araç denemesi" içindir).
5. **Port katmanı ile araç katmanı ayrımı:** DONMUŞ `SourceReader.read` boş metin döndüremediğinden (`text: min_length=1`) boş/çıkarılamayan içerik portta `not_found` olarak raporlanır; planın "boş kaynağı raporla" gereği araç katmanında `extraction_status=empty` kaydıyla karşılanır. İki katman aynı motoru paylaşır.
6. **IPv4-eşlenmiş/NAT64 sarmal açılımı:** `::ffff:10.0.0.7` ve `64:ff9b::a00:1` gibi sarmallar IPv4'e açılıp yeniden denetlenir (`test_resolve_blocks_forbidden_dns_answers[mapped/nat64]`).
7. **IDNA + kontrol karakteri temizliği:** anahtar adı IDNA'ya kodlanır; `urlsplit`'in WHATWG uyumu \t\r\n atması ayrıca test edildi; yol/ek başlıklarda kalan kontrol karakterleri reddedilir (başlık enjeksiyonu kapalı).
8. **`TimeoutError` ≠ bağlantı arızası:** `TimeoutError` Python 3.11+'da `OSError` alt sınıfıdır; `_single_request`'de önce yakalanıp yeniden yükseltilir ki faz zaman aşımı `timeout` koduyla raporlansın, "bağlanılamadı"ya dönüşmesin (ilk koşuda yakalanan hata; düzeltildi).
9. **IPv6 Host başlığı:** diff review'da bulundu — IPv6 hedefte `Host: ::1:9000` geçersizdir; `ParsedTarget.host_header` köşeli parantezli gösterim taşır (`test_ipv6_target_host_header_is_bracketed`).

## 6. Bulgular, riskler ve sınırlar

| Kimlik | Severity | Bulgu / sınıır | Kanıt | Öneri / durum |
| --- | --- | --- | --- | --- |
| R1 | info | Tam suite'te 1 failure: `tests/intake/test_migrations_smoke.py` — B5'in aynı checkout'taki sürmekte olan W4 işi (untracked migration `20261012_0002`, `tests/events/`, `app/messaging` düzenlemeleri). A6 kapsamındaki 127 test tamamen yeşil; intake başarısızlığı A6 diff'inden bağımsızdır (dosya kümeleri ayrık) | `git status --short` çıktısı §1'de | B5 sahibinin tamamlaması beklenir; orchestrator'a kayıt |
| S1 | info (sahiplik) | Plan A6 kaynak modeli alanları DONMUŞ `models/sources.SourceReference`'a sığmıyor (final_url/publisher/published_at/content_hash/extraction_status/source_type/kanıtlar yok). `models/` A6 sahipliği DIŞINDA olduğundan zengin kayıt `web.WebSourceRecord`'a kondu; `to_source_reference()` daraltılmış dönüşüm ve `record_to_evidence()` (DONMUŞ `EvidenceItem`) köprüleri verildi | `tools.record_to_evidence`, `assess._source_id` DONMUŞ `source_id` biçimini üretir | Orchestrator kararı: isterse `SourceReference`'a A6 alanları sonradan eklenebilir (additive); A7 `WebSourceRecord`'ı doğrudan da tüketebilir |
| S2 | low | `assess` kural tabanlıdır: `www.python.org/dev/peps/...` gibi resmî-ama-kural-dışı adresler `unknown` sınıflanır (muhafazakâr orta öncelik 2). Yanlış-pozitif resmî sınıflama yerine bilinmeyen tercihi bilinçlidir | `test_classify_source_type` parametre kümesi | A7 gerekirse anahtar adı listesini genişletebilir |
| S3 | low | eTLD+1 için küçük sabit çok-parçalı son ek kümesi kullanıldı (kapsamlı PublicSuffix bağımlılıksız çalışma gereği dışarıda) | `assess._MULTI_PART_SUFFIXES` | Nadir TLD'lerde grup birleşmesi olabilir; A7'de gerekirse liste büyütülür |
| S4 | low | `robots.txt`/site politikası işlenmez; plan A6 gerektirmez, hız/oran sınırı araç çağrısı düzeyindedir | — | Orchestrator'a ürün kararı olarak bildirilir |
| S5 | info | Gerçek arama sağlayıcısı YOK (anahtar/yapılandırma verilmedi): `search_web` için genel JSON sözleşmeli adaptör yazıldı ve mock uç noktayla doğrulandı; kodda anahtar yoktur. Sağlayıcı kararı operatöre aittir | `test_search_provider_parses_json_results` vb. | Sağlayıcı seçilince `HttpWebSearchProvider(base_url, …, api_key_env=…)` yeterli |
| N1 | info | Port dosyalarında değişiklik gerekmedi: iki mevcut port (`WebSearchProvider`, `SourceReader`) yeni somut adaptörlerce İMZALAR DEĞİŞMEDEN gerçeklendi; additive genişletme ihtiyacı doğmadı | `ports/web_search.py:32`, `ports/source_reader.py:34` imzaları aynen korundu | — |

## 7. RAG kaynak kullanımı

Teknik iddialar aşağıdaki CONTEXT parçalarıyla uyumludur (yalnız bu parçalar): [PY-ASYNCIO#C2] — iptal istisnası bastırılmaz; fetcher/araçlar `CancelledError`'ı `finally` ile temizleyip yükseltir (`test_precancelled_token_fails_before_any_request`). [PY-ASYNCIO#C1] — eşzamanlı alt görev düzeni A7'nin kapsamıdır; A6 araçları tek çağrı sözleşmesi sunar. [LG-RAG#C2] — getirilen bağlam veridir, içindeki talimatlar izlenmez; bu ilke `extract_text`'in yapısal kuralıdır (kod akışı sayfa metnine koşullu dallanmaz). Yerel notlarda bulunmayan HTTP/1.1 çerçeve, zlib wbits ve `TimeoutError ⊂ OSError` davranışı model hafızasından değil, bu depoda ÇALIŞTIRILAN testlerle doğrulandı (§4.1/§4.3).

## 8. Teslim özeti

- **Gate:** `python -m pytest src/services/ai-agent-service/tests/web -q` → **127 passed** (gerçek ağ dahil).
- **Regresyon:** tam suite 523 passed; tek failure B5'in sürmekte olan intake işine aittir (R1), A6 dosyalarıyla ilişkisiz.
- **Dosya sahipliği:** yalnız `app/agent_core/web/**`, `tests/web/**`, bu rapor yazıldı; messaging/.NET/contracts/modellere dokunulmadı; git işlemi yapılmadı.
- **A7'ye not:** araçlar `build_web_tools(guard, settings, search_provider=…)` ile tek noktadan kurulur; her çağrı `events_sink` ile `UsageEvent` akışı verir; `WebSourceRecord.to_source_reference()`/`record_to_evidence()` DONMUŞ A1 sözleşmelerine daraltır.
