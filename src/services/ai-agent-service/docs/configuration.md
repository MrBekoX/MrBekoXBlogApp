# Yapılandırma rehberi (A10 teslimi)

Bu paket yapılandırmayı kod içinde taşımaz: tüm sınırlar çağıranın verdiği
modellerle gelir. Aşağıdaki tablo adaptörün (B6 worker) doldurması
beklenen yapılandırma yüzeyidir.

## 1. Model/embedding sağlayıcısı

- `ModelProvider` / `EmbeddingProvider` portlarını gerçekleştiren adaptör
  sınıfları operatör yapılandırmasıyla kurulur (anahtarlar ENV'ten; sırlar
  prompta, loga, commit'e girmez).
- Test sağlayıcılar (`is_test_double=True`) `environment != "test"`'te
  ÜRETİMDE ETKİNLEŞTİRİLEMEZ (D009 sözleşmesi). Gerçek sağlayıcı
  bağlanana kadar hiçbir kalite sonucu gerçek sayılmaz.
- Router: `prepare_and_route(router_model=...)` verilmezse belirsiz
  durumlar deterministik kurala düşer (geçiş davranışı); verilirse çıktı
  doğrulanır, limit üretimi engellenir.

## 2. Bütçe profilleri (`BudgetProfile` — sunucu sahipliğinde)

| Alan | Anlam | Not |
| --- | --- | --- |
| `max_model_calls` | üretim çağrısı üst sınırı | PositiveInt |
| `max_total_tokens` | token üst sınırı | rezervasyon + commit ile |
| `max_tool_calls` | WEB araç üst sınırı | yerel retrieval bu sınıra bağlı değildir (qa_policy ayrı rezerve eder) |
| `max_web_search_calls` | arama üst sınırı | BudgetPolicy eşlemede `max(profile, 1)` TABANINA sabitlenir — "0 arama" politika düzeyinde ifade edilemez (A10 gözlemi F3) |
| `max_duration_seconds` | süre sınırı | Deadline monotonic saatle |

Akış politikaları: `qa_policy_for`, `research_policy_for`,
`analysis` profili profilden türetilir; politika sınırları profili aşamaz.

## 3. Akış yapılandırmaları

- `QaFlowConfig(top_k=4, max_retrieval_attempts=2, min_citation_overlap=3,
  max_history_query_tokens=6)`
- `AnalysisConfig` (A5 başlık/bütçe sınırları; `MAX_ANSWER_HEADINGS=4`)
- `ResearchFlowConfig(max_claims=6, max_candidates_per_query=3,
  min_claim_overlap=2, max_evidence_per_finding=6)`

## 4. Web araçları (`WebToolSettings`)

- `environment`: `development|test|production`. **`allow_loopback=True`
  yalnız `environment="test"`'te kabul edilir** (UrlGuard); üretimde
  metadata/özel adresler DNS+redirect-pin ile engellidir.
- Port izinleri `allowed_ports`; boyut/tür/timeout sınırları ayar alanlarıdır
  (`connect_timeout_s`, `total_timeout_s`, ...).
- Arama sağlayıcısı verilmezse `search_web` kurulmaz ve araştırma akışı
  anlaşılır `config_error` verir (sessiz devre dışı bırakma yoktur).

## 5. Checkpoint

- `FileCheckpointStore(base_dir)` (D016): atomik tmp+replace+fsync;
  tek-süreç/tek-host varsayımı. Çok-host/kalıcı DB store ihtiyacı B11'de
  değerlendirilir.
- Zarf `CHECKPOINT_SCHEMA_VERSION=1`; uyumsuz zarf anlaşılır
  `validation_error` ile reddedilir.

## 6. Önbellek anahtar kuralı (plan A10 madde 5)

Üretimde cevap-seviyesi önbellek kurulacaksa `evals/cache_policy.py`
referans sözleşmeyi uygular ve koşucu ölçer:

- Anahtar = SHA-256(`ANSWER_CACHE_KEY_VERSION` + **içerik hash'i** +
  **dil** + **soru kapsamı** (general/article/selected) + **yapılandırma
  parmak izi** (embedding model id, qa/analysis/research config JSON'u,
  bütçe profili adı, CHECKPOINT/STATE şema sürümleri, prompt sözleşme
  sürümü)).
- **Konuşmaya bağlı cevaplar ortak önbelleğe girmez:**
  `conversation_history` veya `selected_text` taşıyan istekler
  `is_shared_cache_eligible()=False`.
- Mevcut üretim içi önbellek: `InMemoryContentIndex.search` sorgu önbelleği
  anahtarı `(katlanmış sorgu, filtreler[dil dâhil], top_k, embedding
  model_id)` (`content/index.py:354`, `content/retrieval.py:51`); içerik
  hash'i indekslemenin idempotent `content_hash` anahtarlamasıyla makale
  bazında ayrışır ve makale kaldırılınca çözülemeyen giriş yeniden hesap
  tetikler.

## 7. Değerlendirme koşucusu

- Giriş: `python -m evals.run --suite all --report out/evals` (hizmet kökünden).
- `evals/providers.py` tamamen test sağlayıcısıdır (`provider="test_executor"`);
  `evals/dataset.py` örnekleri bağımsız etiketlidir (router kural importu yok).
- Gerçek sağlayıcı devreye alındığında: `GroundedTestModel` yerine gerçek
  `ModelProvider` bağlanır, koşu yenilenir ve raporun `provider` alanı
  gerçek sağlayıcıyı taşır — o zamana kadar tüm metrikler test-sağlayıcı
  işaretli kalır.
