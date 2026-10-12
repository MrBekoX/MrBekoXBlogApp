"""A10 değerlendirme kümesi: bağımsız etiketli örnekler (>=40).

**Bağımsız etiketleme ilkesi (plan A10: "örnekleri router kurallarının
kopyası haline getirme"):** Her örneğin ``expected`` alanı, örneğin
davranışsal gerektirimi için elle yazılmış yargıdır; ``agent_core.routing``
modülü BU PAKETTE import edilmez ve etiketler kural sinyallerinden
türetilmez. Her etiketin ``rationale`` alanında insan-okur gerekçesi vardır:
etiket yanlışsa gerekçesiyle birlikte tartışılır — koda bakılarak ayarlanmaz.

**Kapsam (plan A10 listesi):** mod seçimi, web ihtiyacı, retrieval, takip
soruLARI, kaynak desteği, seçilen metin, makale dışı soru, profil, iş
birliği, iki dil, iptal, bütçe + checkpoint devamı. ``AREAS`` sabiti bu
etiketlerin resmî kümesidir; koşucu kapsam doluluğunu bununla raporlar.

**Geliştirme fixture'larından ayrım:** Makaleler ``evals.articles``'tan
gelir (tests/ fixture'larından bağımsız, gerçek BlogPost uzunluğunda);
sağlayıcılar ``evals.providers``'tan (tamamı ``is_test_double``).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .articles import (
    ASYNCIO_ARTICLE_ID,
    ASYNCIO_SECTION_BACKPRESSURE,
    ASYNCIO_SECTION_BOUND,
    ASYNCIO_SECTION_ERRORS,
    EVENTS_ARTICLE_ID,
    EVENTS_SECTION_IDEM,
    EVENTS_SECTION_OUTBOX,
    EVENTS_SECTION_OBS,
    EVENTS_SECTION_WHY,
    PG_ARTICLE_ID,
    PG_SECTION_BTREE,
    PG_SECTION_GIN,
    PG_SECTION_MAINTENANCE,
    PG_SECTION_PARTIAL,
)

__all__ = [
    "AREAS",
    "CASES",
    "EvalCase",
    "Expectation",
    "case_by_id",
    "cases_for_suite",
    "SUITE_NAMES",
]

#: Plan A10 kapsam etiketleri; her örnek en az birini taşır.
AREAS: tuple[str, ...] = (
    "mod_secimi",
    "web_ihtiyaci",
    "retrieval",
    "takip_sorulari",
    "kaynak_destegi",
    "secilen_metin",
    "makale_disi",
    "profil",
    "is_birligi",
    "iki_dil",
    "iptal",
    "butce",
    "checkpoint",
    "onbellek",
)

SUITE_NAMES: tuple[str, ...] = ("routing", "qa", "guidance", "research", "lifecycle", "cache")

#: Araştırma akışının ihtiyaç duyduğu serbest bütçe profili adı.
RESEARCH_PROFILE = "eval-research"


class Expectation(BaseModel):
    """Bağımsız etiketlenen beklenen davranış; yalnız dolu alanlar ölçülür."""

    # --- rota kararları (prepare_and_route) ---
    mode: str | None = None
    intent: str | None = None
    needs_web: bool | None = None
    needs_clarification: bool | None = None
    source_scope: str | None = None

    # --- terminal sonuç (execute_plan/resume) ---
    status: str | None = None
    status_in: list[str] = Field(default_factory=list)
    error_code: str | None = None
    raises_error_code: str | None = None  # PortError beklentisi (reddedilen devam)
    mode_preserved: bool | None = None  # resume'da kararın checkpoint'ten gelmesi

    # --- cevap/rapor içerik denetimleri ---
    answer_contains: list[str] = Field(default_factory=list)
    answer_excludes: list[str] = Field(default_factory=list)
    report_contains: list[str] = Field(default_factory=list)
    min_unresolved: int | None = None

    # --- retrieval ve kaynak ölçümleri ---
    expected_section: str | None = None
    min_citations: int | None = None
    zero_citations: bool | None = None
    min_web_citations: int | None = None

    # --- kullanım sınırları (araştırma başına araç/model kullanımı) ---
    model_calls_zero: bool | None = None
    min_model_calls: int | None = None
    max_model_calls: int | None = None
    min_tool_calls: int | None = None
    max_tool_calls: int | None = None
    min_web_search_calls: int | None = None
    max_web_search_calls: int | None = None
    #: Araştırma bütçesinde işlenmiş kaynak sayfası okuması (BudgetStore görünümü).
    min_source_reads: int | None = None
    within_budget: bool | None = None

    # --- checkpoint / durum denetimleri ---
    checkpoint_written: bool | None = None
    collab_stage: str | None = None
    progress_contains: str | None = None


class EvalCase(BaseModel):
    """Tek değerlendirme örneği: girdi + bağlam + bağımsız etiketler."""

    case_id: str
    suite: str
    areas: list[str]
    kind: str = "execute"  # route | execute | resume | cache
    title: str
    question: str
    language: str = "tr"
    article_id: str | None = None
    mode_preference: str = "auto"
    selected_text: str | None = None
    conversation_history: list[dict[str, str]] = Field(default_factory=list)
    #: Belirsiz router yolunu denemek için scripted router bağlanır (double).
    use_router_model: bool = False
    router_suggestions: dict[str, str] = Field(default_factory=dict)
    web_wired: bool = False
    budget_profile: str = "eval-default"
    budget_overrides: dict[str, float] = Field(default_factory=dict)
    #: resume senaryo adı (kind="resume"); harness'taki senaryo fonksiyonuna eşlenir.
    scenario: str | None = None
    #: cache senaryo adı (kind="cache").
    expected: Expectation
    rationale: str


def _history(role: str, content: str) -> dict[str, str]:
    return {"role": role, "content": content}


# ===========================================================================
# ROUTING — görev/mod kararlarının doğruluğu + web ihtiyacı + iki dil
# ===========================================================================

_ROUTING_CASES: list[EvalCase] = [
    EvalCase(
        case_id="r01",
        suite="routing",
        areas=["mod_secimi", "retrieval"],
        kind="route",
        title="Tekil olgu sorusu hızlı modda kalır",
        question="Asyncio kuyruğunda önerilen üst sınır aralığı kaçtır?",
        article_id=ASYNCIO_ARTICLE_ID,
        expected=Expectation(mode="fast", intent="article_qa", needs_web=False, source_scope="article"),
        rationale=(
            "Soru tek bir olguyu soruyor ve cevabın makalede hazır bulunması "
            "beklenir; çok bölüm ilişkilendirme, karşılaştırma veya dış güncellik "
            "istemi yoktur. Doğru davranış: hızlı mod, makale kapsamı, web yok."
        ),
    ),
    EvalCase(
        case_id="r02",
        suite="routing",
        areas=["mod_secimi"],
        kind="route",
        title="Uzun ama tek bölümlü soru araştırmaya çıkmaz",
        question=(
            "Asyncio servislerinde kuyruk sınırı belirlenirken izlenen bekleme "
            "süresi metriği sürekli artıyorsa bu durum tüketici kapasitesinin "
            "artırılması gerektiğine mi işaret eder?"
        ),
        article_id=ASYNCIO_ARTICLE_ID,
        expected=Expectation(mode="fast", intent="article_qa", needs_web=False),
        rationale=(
            "Soru fiziksel olarak uzun olsa da tek bir bölümün (kuyruk sınırı) "
            "içeriğini sorar; birden fazla bölümün ilişkilendirilmesi istenmez. "
            "Uzunluk tek başına derin araştırma gerekçesi değildir."
        ),
    ),
    EvalCase(
        case_id="r03",
        suite="routing",
        areas=["mod_secimi"],
        kind="route",
        title="Karşılaştırma sorusu analiz moduna gider",
        question="B-tree mi GIN mi: JSONB sorguları için hangisi uygundur?",
        article_id=PG_ARTICLE_ID,
        expected=Expectation(mode="analysis", intent="compare", needs_web=False),
        rationale=(
            "İki indeks yapısının karşılaştırılması, birden fazla bölümün "
            "(B-tree ve GIN bölümleri) birlikte değerlendirilmesini gerektirir; "
            "tek bölüm araması bu soruya yanlış cevap verirdi."
        ),
    ),
    EvalCase(
        case_id="r04",
        suite="routing",
        areas=["mod_secimi"],
        kind="route",
        title="Çok bölümlü soru analiz moduna gider",
        question=(
            "Kuyruk sınırı nasıl belirlenir? QueueFull istisnası nasıl yönetilir? "
            "Geri basınç nasıl uygulanır?"
        ),
        article_id=ASYNCIO_ARTICLE_ID,
        expected=Expectation(mode="analysis", intent="article_qa", needs_web=False),
        rationale=(
            "Üç ayrı bölümün içeriği aynı cevapta ilişkilendirilmelidir; bu, "
            "başlık başına arama yapan analiz akışının görevidir."
        ),
    ),
    EvalCase(
        case_id="r05",
        suite="routing",
        areas=["mod_secimi", "web_ihtiyaci"],
        kind="route",
        title="Açık araştırma isteği derin araştırmaya yönelir",
        question=(
            "Asyncio kuyruk yönetimi için güncel uygulamaları araştır; sınırlama "
            "ve hata yönetimi alt sorularıyla derinlemesine incele."
        ),
        article_id=ASYNCIO_ARTICLE_ID,
        expected=Expectation(
            mode="deep_research", intent="research", needs_web=True, source_scope="article_and_web"
        ),
        rationale=(
            "Kullanıcı açıkça araştırma ve alt sorular istiyor: güncel dış kanıt "
            "toplanması gerekir; makale içeriği tek başına bu isteği karşılamaz."
        ),
    ),
    EvalCase(
        case_id="r06",
        suite="routing",
        areas=["mod_secimi", "web_ihtiyaci"],
        kind="route",
        title="Güncellik sorusu dış kanıt ister",
        question="PostgreSQL kısmi indekslerinin güncel durumu nedir?",
        article_id=PG_ARTICLE_ID,
        expected=Expectation(mode="deep_research", intent="research", needs_web=True),
        rationale=(
            "'Güncel durum' sorusu makalenin yazıldığı andaki bilgiyi değil "
            "bugünün durumunu sorar; dış kanıt olmadan cevap yanıltıcıdır."
        ),
    ),
    EvalCase(
        case_id="r07",
        suite="routing",
        areas=["mod_secimi", "web_ihtiyaci"],
        kind="route",
        title="Eylem sorusu güncellik sanılıp web'e çıkarılmaz",
        question="Kuyruğumu nasıl güncellerim?",
        article_id=ASYNCIO_ARTICLE_ID,
        expected=Expectation(mode="fast", needs_web=False),
        rationale=(
            "'Güncellerim' burada bir eylem fiilidir; kullanıcı kendi kodunu "
            "değiştirmeyi soruyor, dünyanın güncel halini değil. Web araması "
            "bu soruya gereksiz maliyet ve gecikme eklerdi."
        ),
    ),
    EvalCase(
        case_id="r08",
        suite="routing",
        areas=["mod_secimi", "iki_dil"],
        kind="route",
        title="İngilizce tekil soru hızlı modda kalır",
        question="What upper bound does the article recommend for the queue?",
        language="en",
        article_id=EVENTS_ARTICLE_ID,
        expected=Expectation(mode="fast", intent="article_qa", needs_web=False),
        rationale=(
            "İki dil kapsamı: aynı davranış Türkçe örnekte olduğu gibi "
            "İngilizce soruda da beklenir; dil kararı değiştirmez."
        ),
    ),
    EvalCase(
        case_id="r09",
        suite="routing",
        areas=["mod_secimi", "iki_dil"],
        kind="route",
        title="İngilizce karşılaştırma analize gider",
        question="Outbox pattern versus direct publishing: which approach should I pick?",
        language="en",
        article_id=EVENTS_ARTICLE_ID,
        expected=Expectation(mode="analysis", intent="compare", needs_web=False),
        rationale=(
            "Outbox ile doğrudan yayınlama iki bölümün karşılıklı "
            "değerlendirilmesini gerektirir; dil Türkçe karşılığıyla aynı davranışı üretmelidir."
        ),
    ),
    EvalCase(
        case_id="r10",
        suite="routing",
        areas=["mod_secimi"],
        kind="route",
        title="Makaleyi bütün soran özet sorusu hızlı modda kalır",
        question="Bu makale genel olarak ne anlatıyor?",
        article_id=ASYNCIO_ARTICLE_ID,
        expected=Expectation(mode="fast", intent="summarize", needs_web=False),
        rationale=(
            "Ana fikir sorusu bölüm ilişkilendirmesi değil bütün makalenin "
            "özetlenmesidir; getirilen herhangi bir bölüm kanıt sayılır."
        ),
    ),
    EvalCase(
        case_id="r11",
        suite="routing",
        areas=["mod_secimi", "secilen_metin"],
        kind="route",
        title="Seçili metin açıklaması analiz moduna gider",
        question="Kuyruk sınırı bu satırda nasıl atanır?",
        article_id=ASYNCIO_ARTICLE_ID,
        selected_text="`asyncio.Queue(maxsize=...)` ile üst sınır atanır.",
        expected=Expectation(mode="analysis", intent="explain", needs_web=False),
        rationale=(
            "Kullanıcı makaleden seçtiği satırı soruyor: açıklama seçilen "
            "parçanın bağlamıyla yapılmalıdır; bu analiz akışının görevidir."
        ),
    ),
    EvalCase(
        case_id="r12",
        suite="routing",
        areas=["mod_secimi", "profil"],
        kind="route",
        title="Yazar tanıtımı profil niyetine gider",
        question="Yazar kimdir ve hangi alanlarda çalışıyor?",
        expected=Expectation(mode="fast", intent="profile", source_scope="profile", needs_web=False),
        rationale=(
            "Yazar kimliği sorusu onaylı profil kayıtlarından deterministik "
            "yanıtlanır; model üretimine gerek yoktur."
        ),
    ),
    EvalCase(
        case_id="r13",
        suite="routing",
        areas=["mod_secimi", "is_birligi"],
        kind="route",
        title="İş birliği isteği iş birliği niyetine gider",
        question="Sizinle konuk yazı iş birliği yapmak istiyorum.",
        expected=Expectation(mode="fast", intent="collaboration", needs_web=False),
        rationale=(
            "Konuk yazı isteği durum makinesiyle yürütülür; detay toplanmadan "
            "öneri üretilemez ve model üretimine gerek yoktur."
        ),
    ),
    EvalCase(
        case_id="r14",
        suite="routing",
        areas=["mod_secimi", "profil"],
        kind="route",
        title="Makale önerisi öneri niyetine gider",
        question="Bana kuyruk yönetimi konulu bir makale öner.",
        expected=Expectation(mode="fast", intent="content_suggestion", needs_web=False),
        rationale=(
            "Okuma önerisi onaylı makale kataloğundan gerekçeli seçimdir; "
            "model çağrısı yerine katalog taraması yeterlidir."
        ),
    ),
    EvalCase(
        case_id="r15",
        suite="routing",
        areas=["mod_secimi", "profil"],
        kind="route",
        title="Kişisel bağlam sorusu açıklama ister",
        question="Benim projemde kuyruk sınırı kaç olmalı?",
        article_id=ASYNCIO_ARTICLE_ID,
        expected=Expectation(mode="fast", intent="article_qa", needs_clarification=True),
        rationale=(
            "'Benim projem' kullanıcının ortamına özgü bilgi gerektirir; bu "
            "bilgi yoktur ve tahminle doldurulamaz — açık soru sorulmalıdır."
        ),
    ),
    EvalCase(
        case_id="r16",
        suite="routing",
        areas=["mod_secimi"],
        kind="route",
        title="Bağlamsız makale göndermesi belirsiz sayılır ve açıklama ister",
        question="Bu makaledeki kuyruk yaklaşımı günümüz servislerine uygun mu?",
        use_router_model=True,
        router_suggestions={
            "kuyruk yaklaşımı": (
                '{"intent": "article_qa", "selected_mode": "fast", "needs_web": false, '
                '"needs_clarification": true, "clarification_question": '
                '"Hangi makaleden söz ettiğinizi paylaşabilir misiniz?", '
                '"brief_reason": "makale bağlamı belirsiz"}'
            )
        },
        expected=Expectation(mode="fast", intent="article_qa", needs_clarification=True),
        rationale=(
            "Soru 'bu makaledeki' diyor ama bağlamda makale yok: belirsiz "
            "durumda router modeline danışılması ve soru metniyle açıklama "
            "istenmesi doğru davranıştır; tahminle cevap üretmek değildir."
        ),
    ),
    EvalCase(
        case_id="r17",
        suite="routing",
        areas=["mod_secimi", "web_ihtiyaci", "iki_dil"],
        kind="route",
        title="İngilizce güncellik sorusu dış kanıt ister",
        question="What is the latest guidance on idempotency keys for consumers?",
        language="en",
        article_id=EVENTS_ARTICLE_ID,
        expected=Expectation(mode="deep_research", intent="research", needs_web=True),
        rationale=(
            "'Latest guidance' güncel dış kanıt ister; makalenin anlattığı "
            "ilkeyi değil bugünkü uygulama önerilerini soruyor."
        ),
    ),
    EvalCase(
        case_id="r18",
        suite="routing",
        areas=["mod_secimi", "profil"],
        kind="route",
        title="Proje rehberi sorusu proje niyetine gider",
        question="Hangi projelerde çalıştınız?",
        expected=Expectation(mode="fast", intent="projects", source_scope="projects", needs_web=False),
        rationale=(
            "Portfolyo sorusu onaylı proje kayıtlarından deterministik "
            "yanıtlanır; model üretimi uydurma riski taşır."
        ),
    ),
]

# ===========================================================================
# QA — ilgili bölümün bulunması, kaynak desteği, takip, seçilen metin,
# makale dışı, iki dil, gecikme aileleri
# ===========================================================================

_QA_CASES: list[EvalCase] = [
    EvalCase(
        case_id="q01",
        suite="qa",
        areas=["retrieval", "kaynak_destegi"],
        kind="execute",
        title="Kuyruk sınırı bölümüne yönelik soru",
        question="Asyncio kuyruğunda önerilen üst sınır aralığı kaçtır?",
        article_id=ASYNCIO_ARTICLE_ID,
        expected=Expectation(
            status="completed",
            expected_section=ASYNCIO_SECTION_BOUND,
            min_citations=1,
            answer_contains=["100"],
            max_model_calls=1,
        ),
        rationale=(
            "Cevap kuyruk sınırı bölümündedir; doğru bölümün bulunması ve "
            "cevabın o bölüme atıfla desteklenmesi beklenir."
        ),
    ),
    EvalCase(
        case_id="q02",
        suite="qa",
        areas=["retrieval", "kaynak_destegi"],
        kind="execute",
        title="Hata yönetimi bölümüne yönelik soru",
        question="Kuyruk dolduğunda QueueFull istisnası nasıl yönetilmelidir?",
        article_id=ASYNCIO_ARTICLE_ID,
        expected=Expectation(
            status="completed",
            expected_section=ASYNCIO_SECTION_ERRORS,
            min_citations=1,
            answer_contains=["QueueFull"],
            max_model_calls=1,
        ),
        rationale=(
            "QueueFull yönetimi hata yönetimi bölümündedir; bölümün bulunması "
            "ve atıf desteği ölçülür."
        ),
    ),
    EvalCase(
        case_id="q03",
        suite="qa",
        areas=["retrieval"],
        kind="execute",
        title="Geri basınç bölümüne yönelik soru",
        question="Kuyruk sınırı dolduğunda geri basınç için hangi stratejiler uygundur?",
        article_id=ASYNCIO_ARTICLE_ID,
        expected=Expectation(
            status="completed",
            expected_section=ASYNCIO_SECTION_BACKPRESSURE,
            min_citations=1,
            answer_contains=["üretici"],
            max_model_calls=1,
        ),
        rationale="Geri basınç stratejileri ayrı bir bölümdür; ilgili bölümün bulunması beklenir.",
    ),
    EvalCase(
        case_id="q04",
        suite="qa",
        areas=["retrieval"],
        kind="execute",
        title="GIN bölümüne yönelik soru",
        question="JSONB sorguları için hangi indeks yapısı gereklidir?",
        article_id=PG_ARTICLE_ID,
        expected=Expectation(
            status="completed",
            expected_section=PG_SECTION_GIN,
            min_citations=1,
            answer_contains=["GIN"],
            max_model_calls=1,
        ),
        rationale="JSONB/tam metin cevabı GIN bölümündedir; yanlış bölüm (B-tree) atıfı hatalı kaynaktır.",
    ),
    EvalCase(
        case_id="q05",
        suite="qa",
        areas=["retrieval"],
        kind="execute",
        title="Kısmi indeks bölümüne yönelik soru",
        question="Yalnız aktif kayıtları indekslemek için ne kullanılmalıdır?",
        article_id=PG_ARTICLE_ID,
        expected=Expectation(
            status="completed",
            expected_section=PG_SECTION_PARTIAL,
            min_citations=1,
            answer_contains=["aktif"],
            max_model_calls=1,
        ),
        rationale="Kısmi indeks bölümünün bulunması ve desteklenen cevap beklenir.",
    ),
    EvalCase(
        case_id="q06",
        suite="qa",
        areas=["retrieval", "iki_dil"],
        kind="execute",
        title="İngilizce outbox sorusu",
        question="How does the outbox pattern make delivery reliable?",
        language="en",
        article_id=EVENTS_ARTICLE_ID,
        expected=Expectation(
            status="completed",
            expected_section=EVENTS_SECTION_OUTBOX,
            min_citations=1,
            answer_contains=["outbox"],
            max_model_calls=1,
        ),
        rationale="İki dil kapsamı: İngilizce soruda da bölüm bulma ve atıf desteği aynı çalışmalıdır.",
    ),
    EvalCase(
        case_id="q07",
        suite="qa",
        areas=["retrieval", "iki_dil"],
        kind="execute",
        title="İngilizce idempotency sorusu",
        question="Why must consumers tolerate duplicate deliveries?",
        language="en",
        article_id=EVENTS_ARTICLE_ID,
        expected=Expectation(
            status="completed",
            expected_section=EVENTS_SECTION_IDEM,
            min_citations=1,
            answer_contains=["tolerate duplicates"],
            max_model_calls=1,
        ),
        rationale="Idempotency bölümü İngilizce soruda bulunup atıflanmalıdır; cevap tekrar teslim toleransını taşımalıdır.",
    ),
    EvalCase(
        case_id="q08",
        suite="qa",
        areas=["takip_sorulari", "retrieval"],
        kind="execute",
        title="Türkçe takip sorusu önceki turun konusunu taşır",
        question="Peki istisna yönetimi tarafında ne yapılmalıdır?",
        article_id=ASYNCIO_ARTICLE_ID,
        conversation_history=[
            _history("user", "Asyncio kuyruğunda önerilen üst sınır nedir?"),
            _history("assistant", "Önerilen üst sınır aralığı 100 ile 1000 arasındadır."),
        ],
        expected=Expectation(
            status="completed",
            expected_section=ASYNCIO_SECTION_ERRORS,
            min_citations=1,
            max_model_calls=1,
        ),
        rationale=(
            "Takip sorusu tek başına 'istisna yönetimi' der; önceki turun kuyruk "
            "bağlamıyla birlikte hata yönetimi bölümüne yönelmesi beklenir. "
            "Bu örnek konuşmaya bağlıdır: ortak önbelleğe giremez."
        ),
    ),
    EvalCase(
        case_id="q09",
        suite="qa",
        areas=["takip_sorulari", "iki_dil"],
        kind="execute",
        title="İngilizce takip sorusu",
        question="How should consumers deal with replays of the same message?",
        language="en",
        article_id=EVENTS_ARTICLE_ID,
        conversation_history=[
            _history("user", "How does the outbox pattern make delivery reliable?"),
            _history(
                "assistant",
                "The outbox pattern writes events in the same transaction and relays them afterwards.",
            ),
        ],
        expected=Expectation(
            status="completed",
            expected_section=EVENTS_SECTION_IDEM,
            min_citations=1,
            max_model_calls=1,
        ),
        rationale="Outbox turlarından sonra tekrar teslim sorusu idempotency bölümüne yönelmelidir.",
    ),
    EvalCase(
        case_id="q10",
        suite="qa",
        areas=["makale_disi"],
        kind="execute",
        title="Makale dışı Türkçe soru uydurmadan reddeder",
        question="Fırın kek tarifinde kabartma tozu oranı nasıl ayarlanır?",
        article_id=ASYNCIO_ARTICLE_ID,
        expected=Expectation(
            status="completed",
            zero_citations=True,
            model_calls_zero=True,
            answer_contains=["makalede yer almıyor"],
        ),
        rationale=(
            "Sorunun makalede karşılığı yoktur: doğru davranış model çağrısı "
            "yapmadan, atıfsız ve açık yetersiz-bilgi yanıtıdır; uydurma cevap hata olur."
        ),
    ),
    EvalCase(
        case_id="q11",
        suite="qa",
        areas=["makale_disi", "iki_dil"],
        kind="execute",
        title="Makale dışı İngilizce soru uydurmadan reddeder",
        question="Where can I learn salsa dance in Izmir this weekend?",
        language="en",
        article_id=EVENTS_ARTICLE_ID,
        expected=Expectation(
            status="completed",
            zero_citations=True,
            model_calls_zero=True,
            answer_contains=["not covered by the article"],
        ),
        rationale=(
            "İki dil kapsamı: yetersizlik yanıtı İngilizce soruda da uydurmaz ve "
            "İngilizce döner. Soru, makaleyle kazara terim örtüşmesi taşımayan "
            "biçimde seçildi: yeterlilik kapısı belirteç-örtüşmesine dayalıdır ve "
            "tek işlev sözcüğü ('without' gibi) bile İngilizce soruyu üretime "
            "sokabiliyor — bu gözlem raporda ayrı kaydedilmiştir."
        ),
    ),
    EvalCase(
        case_id="q12",
        suite="qa",
        areas=["mod_secimi", "kaynak_destegi"],
        kind="execute",
        title="Genel özet sorusu bütün makaleyi kanıtlar",
        question="Bu makale genel olarak ne anlatıyor?",
        article_id=ASYNCIO_ARTICLE_ID,
        expected=Expectation(
            status="completed",
            min_citations=1,
            min_model_calls=1,
            max_model_calls=1,
        ),
        rationale=(
            "Ana fikir sorusunda getirilen herhangi bir bölüm kanıttır; cevap "
            "tek model çağrısıyla üretilip makale bölümleriyle atıflanmalıdır."
        ),
    ),
    EvalCase(
        case_id="q13",
        suite="qa",
        areas=["secilen_metin"],
        kind="execute",
        title="Makaleden seçilen satır doğrulanmış kaynak olur",
        question="Kuyruk sınırı bu satırda nasıl atanır?",
        article_id=ASYNCIO_ARTICLE_ID,
        selected_text="`asyncio.Queue(maxsize=...)` ile üst sınır atanır.",
        expected=Expectation(
            status="completed",
            mode="analysis",
            answer_excludes=["makalede bulunamadı"],
        ),
        rationale=(
            "Seçili metin makalede mevcut: doğru davranış seçimi doğrulanmış "
            "kaynak olarak kullanmak ve 'bulunamadı' notu üretmemektir."
        ),
    ),
    EvalCase(
        case_id="q14",
        suite="qa",
        areas=["secilen_metin", "kaynak_destegi"],
        kind="execute",
        title="Makalede olmayan seçim dürüstçe bildirilir",
        question="Kuyruk sınırı uygulamasında bu seçili bölüm ne yapmalıdır?",
        article_id=ASYNCIO_ARTICLE_ID,
        selected_text="Kubernetes HPA yatay ölçekleme kararını metriklerden üretir.",
        expected=Expectation(
            status="completed",
            mode="analysis",
            answer_contains=["makalede bulunamadı"],
        ),
        rationale=(
            "Seçilen metin makaleden değil: aynen kaynak gibi kullanmak yanlış "
            "kanıt üretir; doğru davranış 'makalede bulunamadı' notudur."
        ),
    ),
    EvalCase(
        case_id="q15",
        suite="qa",
        areas=["mod_secimi", "kaynak_destegi"],
        kind="execute",
        title="Çok bölümlü soru başlıklarla cevaplanır",
        question=(
            "Kuyruk sınırı nasıl belirlenir? QueueFull istisnası nasıl yönetilir? "
            "Geri basınç nasıl uygulanır?"
        ),
        article_id=ASYNCIO_ARTICLE_ID,
        expected=Expectation(
            status="completed",
            mode="analysis",
            min_model_calls=1,
            max_model_calls=1,
            answer_contains=["QueueFull", "üretici"],
        ),
        rationale=(
            "Analiz akışı soruyu başlıklara ayırıp başlık başına arar; üç "
            "bölümün de cevapta temsil edilmesi ve tek üretim çağrısı beklenir."
        ),
    ),
    EvalCase(
        case_id="q16",
        suite="qa",
        areas=["retrieval"],
        kind="execute",
        title="Bakım bölümüne yönelik soru",
        question="Kullanılmayan indeksler nasıl tespit edilir ve bakımı yapılır?",
        article_id=PG_ARTICLE_ID,
        expected=Expectation(
            status="completed",
            expected_section=PG_SECTION_MAINTENANCE,
            min_citations=1,
            answer_contains=["pg_stat_user_indexes"],
            max_model_calls=1,
        ),
        rationale="Bakım komutları Bakım ve maliyet bölümündedir; bölüm bulma + atıf beklenir.",
    ),
    EvalCase(
        case_id="q17",
        suite="qa",
        areas=["retrieval", "iki_dil"],
        kind="execute",
        title="İngilizce 'neden olaylar' sorusu",
        question="What trade-off do events introduce between services?",
        language="en",
        article_id=EVENTS_ARTICLE_ID,
        expected=Expectation(
            status="completed",
            expected_section=EVENTS_SECTION_WHY,
            min_citations=1,
            answer_contains=["eventual consistency"],
            max_model_calls=1,
        ),
        rationale="Giriş bölümündeki eventually-consistency ödünü bulunmalı ve atıflanmalıdır.",
    ),
    EvalCase(
        case_id="q18",
        suite="qa",
        areas=["retrieval"],
        kind="execute",
        title="B-tree bölümüne yönelik soru",
        question="Sıralama ve aralık sorguları için hangi indeks türü seçilmelidir?",
        article_id=PG_ARTICLE_ID,
        expected=Expectation(
            status="completed",
            expected_section=PG_SECTION_BTREE,
            min_citations=1,
            answer_contains=["B-tree"],
            max_model_calls=1,
        ),
        rationale="Aralık/sıralama cevabı B-tree bölümündedir; gözlemlenebilirlik değil doğru bölüm atıflanır.",
    ),
]

# ===========================================================================
# GUIDANCE — profil, iş birliği, onaylı kaynaklar
# ===========================================================================

_GUIDANCE_CASES: list[EvalCase] = [
    EvalCase(
        case_id="g01",
        suite="guidance",
        areas=["profil", "mod_secimi"],
        kind="execute",
        title="Profil sorusu onaylı kayıttan model çağrısız yanıtlanır",
        question="Yazar kimdir ve hangi alanlarda çalışıyor?",
        expected=Expectation(
            status="completed",
            intent="profile",
            model_calls_zero=True,
            answer_contains=["berkay"],
            source_scope="profile",
        ),
        rationale=(
            "Yazar tanıtımı onaylı profil kaydının deterministik kompozisyonudur; "
            "model çağrısı yoktur ve cevap kayıttaki ismi taşır."
        ),
    ),
    EvalCase(
        case_id="g02",
        suite="guidance",
        areas=["profil"],
        kind="execute",
        title="Ücret sorusu uydurulmaz, açık soru döner",
        question="Danışmanlık ücretiniz ne kadar?",
        expected=Expectation(
            status="needs_input",
            intent="profile",
            model_calls_zero=True,
            min_unresolved=1,
        ),
        rationale=(
            "Ücret kayıtlı profil verisi değildir; doğru davranış needs_input "
            "terminaliyle açık soru sormaktır, sayı uydurmak değil."
        ),
    ),
    EvalCase(
        case_id="g03",
        suite="guidance",
        areas=["profil", "mod_secimi"],
        kind="execute",
        title="Proje sorusu onaylı kayıtlardan listeler",
        question="Hangi projelerde çalıştınız?",
        expected=Expectation(
            status="completed",
            intent="projects",
            model_calls_zero=True,
            answer_contains=["mrbekox-blog"],
            source_scope="projects",
        ),
        rationale="Proje rehberi onaylı kayıtların listesidir; cevap kayıttaki proje adını taşımalıdır.",
    ),
    EvalCase(
        case_id="g04",
        suite="guidance",
        areas=["profil", "mod_secimi"],
        kind="execute",
        title="Öneri onaylı katalogdan kaynak bağlantılı verilir",
        question="Bana kuyruk yönetimi konulu bir makale öner.",
        expected=Expectation(
            status="completed",
            intent="content_suggestion",
            model_calls_zero=True,
            answer_contains=["https://mrbekox.dev/blog/asyncio-kuyruk-yonetimi"],
        ),
        rationale="Öneri uydurma URL taşımaz; katalogdaki doğrulanmış bağlantıyla gelir.",
    ),
    EvalCase(
        case_id="g05",
        suite="guidance",
        areas=["profil"],
        kind="execute",
        title="Katalogsuz öneri dürüst kısmi sonuç verir",
        question="Bana kuyruk yönetimi konulu bir makale öner.",
        expected=Expectation(
            status="partial",
            intent="content_suggestion",
            model_calls_zero=True,
            answer_contains=["bağlı olmadığı"],
        ),
        rationale=(
            "Katalog bağlı değilken öneri uydurulmaz; kullanılamazlık notuyla "
            "kısmi sonuç doğru davranıştır."
        ),
    ),
    EvalCase(
        case_id="g06",
        suite="guidance",
        areas=["is_birligi", "checkpoint"],
        kind="resume",
        scenario="collab_first",
        title="İş birliği ilk adımda eksik detayı sorar ve checkpoint'e yazar",
        question="Sizinle konuk yazı iş birliği yapmak istiyorum.",
        article_id=ASYNCIO_ARTICLE_ID,
        expected=Expectation(
            status="needs_input",
            intent="collaboration",
            min_unresolved=1,
            checkpoint_written=True,
            collab_stage="details_needed",
        ),
        rationale=(
            "İş birliği hazırlığı eksik alanlarda DURUR; sorular sorulur ve "
            "durum checkpoint'e yazılır — model tahminiyle devam etmez."
        ),
    ),
    EvalCase(
        case_id="g07",
        suite="guidance",
        areas=["is_birligi", "checkpoint"],
        kind="resume",
        scenario="collab_answers",
        title="Eksik alan cevapları checkpoint'ten devamla öneri üretir",
        question="Sizinle konuk yazı iş birliği yapmak istiyorum.",
        article_id=ASYNCIO_ARTICLE_ID,
        expected=Expectation(
            status="needs_input",
            collab_stage="proposal_review",
            checkpoint_written=True,
            min_unresolved=1,
        ),
        rationale=(
            "Zorunlu alanlar tamamlandığında makaleye bağlı öneri üretilir ve "
            "onay sorusuyla needs_input'ta durulur; state checkpoint'te günceldir."
        ),
    ),
    EvalCase(
        case_id="g08",
        suite="guidance",
        areas=["is_birligi"],
        kind="resume",
        scenario="collab_approval_unverified",
        title="Doğrulanmamış onay reddedilir",
        question="Sizinle konuk yazı iş birliği yapmak istiyorum.",
        article_id=ASYNCIO_ARTICLE_ID,
        expected=Expectation(raises_error_code="validation_error"),
        rationale=(
            "Onay yalnız backend'in doğrulanmış ValidatedActionResult'ıyla "
            "işlenir; sonucuz onay başarı varsayamaz ve reddedilir."
        ),
    ),
    EvalCase(
        case_id="g09",
        suite="guidance",
        areas=["is_birligi", "checkpoint"],
        kind="resume",
        scenario="collab_approval",
        title="Doğrulanmış sonuçla iş birliği kapanır",
        question="Sizinle konuk yazı iş birliği yapmak istiyorum.",
        article_id=ASYNCIO_ARTICLE_ID,
        expected=Expectation(
            status="completed",
            collab_stage="resolved",
            answer_contains=["doğrulandı ve kaydedildi"],
        ),
        rationale=(
            "Kayıt başarısı yalnız doğrulanmış backend sonucundan sonra "
            "bildirilir; agent kendi başına kayıt atmaz."
        ),
    ),
]

# ===========================================================================
# RESEARCH — web ihtiyacı, araç/model kullanımı, bütçe
# ===========================================================================

_RESEARCH_CASES: list[EvalCase] = [
    EvalCase(
        case_id="s01",
        suite="research",
        areas=["web_ihtiyaci", "butce"],
        kind="execute",
        title="Türkçe araştırma dış kanıtlarla kısmi/tam rapor üretir",
        question=(
            "Asyncio kuyruk yönetimi için güncel uygulamaları araştır; sınırlama "
            "ve hata yönetimi alt sorularıyla derinlemesine incele."
        ),
        article_id=ASYNCIO_ARTICLE_ID,
        web_wired=True,
        budget_profile=RESEARCH_PROFILE,
        expected=Expectation(
            status_in=["completed", "partial"],
            mode="deep_research",
            min_web_search_calls=1,
            min_source_reads=1,
            min_model_calls=1,
            max_model_calls=2,
            min_web_citations=1,
            within_budget=True,
        ),
        rationale=(
            "Araştırma akışı arama yapmalı, en az bir dış sayfa okuyup kanıt "
            "elemeli ve model çağrılı raporu dış kaynak atıflarıyla döndürmelidir; "
            "tüm kullanım profil sınırlarında kalmalıdır."
        ),
    ),
    EvalCase(
        case_id="s02",
        suite="research",
        areas=["web_ihtiyaci", "iki_dil"],
        kind="execute",
        title="İngilizce araştırma dış kanıtlarla rapor üretir",
        question=(
            "Investigate the current state of the outbox pattern and idempotency; "
            "research it with sub questions."
        ),
        language="en",
        article_id=EVENTS_ARTICLE_ID,
        web_wired=True,
        budget_profile=RESEARCH_PROFILE,
        expected=Expectation(
            status_in=["completed", "partial"],
            mode="deep_research",
            min_web_search_calls=1,
            min_source_reads=1,
            min_model_calls=1,
            min_web_citations=1,
            within_budget=True,
        ),
        rationale="İki dil kapsamı: İngilizce araştırma aynı araç disipliniyle çalışmalıdır.",
    ),
    EvalCase(
        case_id="s03",
        suite="research",
        areas=["web_ihtiyaci"],
        kind="execute",
        title="Web bağlı değilken dürüst kullanılamazlık notu",
        question="Asyncio kuyruk yönetimi için güncel uygulamaları araştır ve derinlemesine incele.",
        article_id=ASYNCIO_ARTICLE_ID,
        web_wired=False,
        budget_profile=RESEARCH_PROFILE,
        expected=Expectation(
            status="completed",
            mode="deep_research",
            needs_web=True,
            max_model_calls=1,
            report_contains=["bağlı olmadığı"],
        ),
        rationale=(
            "Karar web gerektirir ama araçlar bağlı değildir: tek model çağrısıyla "
            "içerik üretilir ve dış kanıt toplanamadığı AÇIKÇA raporda bildirilir."
        ),
    ),
    EvalCase(
        case_id="s04",
        suite="research",
        areas=["web_ihtiyaci", "butce"],
        kind="execute",
        title="Arama bütçesi sıfırken araştırma kısmi terminalde kalır",
        question="Asyncio kuyruk yönetimi için güncel uygulamaları araştır ve derinlemesine incele.",
        article_id=ASYNCIO_ARTICLE_ID,
        web_wired=True,
        budget_profile=RESEARCH_PROFILE,
        budget_overrides={"max_web_search_calls": 0},
        expected=Expectation(
            status="partial",
            mode="deep_research",
        ),
        rationale=(
            "Arama bütçesi bitince akış çökmek veya bulgu uydurmak yerine kayıtlı "
            "hata notuyla KISMİ rapor üretir. Ölçüm notu: BudgetPolicy arama "
            "sınırını profil 0'da bile en az 1'e sabitler "
            "(from_budget_profile: max(profile.max_web_search_calls, 1)); 'sıfır "
            "arama' politika düzeyinde ifade edilemez, dolayısıyla ölçülen "
            "davranış 'kota dolunca zarif kısmi terminal'dir (rapor gözlemi F3)."
        ),
    ),
]

# ===========================================================================
# LIFECYCLE — checkpoint/resume, bütçe, iptal
# ===========================================================================

_LIFECYCLE_CASES: list[EvalCase] = [
    EvalCase(
        case_id="l01",
        suite="lifecycle",
        areas=["iptal", "checkpoint"],
        kind="resume",
        scenario="resume_after_cancel",
        title="İptal sonrası checkpoint'ten devam modu korur",
        question="Asyncio kuyruğunda önerilen üst sınır aralığı kaçtır?",
        article_id=ASYNCIO_ARTICLE_ID,
        expected=Expectation(
            status="completed",
            mode="fast",
            mode_preserved=True,
            progress_contains="checkpoint'ten sürdürüldü",
        ),
        rationale=(
            "İptal edilmiş çalışma cancelled terminaliyle biter; checkpoint'ten "
            "devam rota kararını YENİDEN hesaplamaz, aynı modla tamamlanır."
        ),
    ),
    EvalCase(
        case_id="l02",
        suite="lifecycle",
        areas=["checkpoint", "butce"],
        kind="resume",
        scenario="resume_deadline",
        title="Deadline dolan devam çalışması timeout ile biter",
        question="Asyncio kuyruğunda önerilen üst sınır aralığı kaçtır?",
        article_id=ASYNCIO_ARTICLE_ID,
        expected=Expectation(status="failed", error_code="timeout"),
        rationale=(
            "Devam ettirilen çalışmaya verilen kalan süre dolduğunda süreç asılı "
            "kalmaz; anlaşılır timeout terminali üretilir."
        ),
    ),
    EvalCase(
        case_id="l03",
        suite="lifecycle",
        areas=["butce"],
        kind="execute",
        title="Token bütçesi tükenince anlaşılır bütçe hatası",
        question="Asyncio kuyruğunda önerilen üst sınır aralığı kaçtır?",
        article_id=ASYNCIO_ARTICLE_ID,
        budget_overrides={"max_total_tokens": 1},
        expected=Expectation(status="failed", error_code="budget_exhausted"),
        rationale=(
            "Sunucu bütçesi token rezervasyonuna yetmez: akış çökmez, bütçe "
            "hatasıyla terminal sonuç döner."
        ),
    ),
    EvalCase(
        case_id="l04",
        suite="lifecycle",
        areas=["iptal", "web_ihtiyaci"],
        kind="resume",
        scenario="research_cancel",
        title="Araştırma iptali cancelled terminaliyle döner",
        question="Asyncio kuyruk yönetimi için güncel uygulamaları araştır ve derinlemesine incele.",
        article_id=ASYNCIO_ARTICLE_ID,
        web_wired=True,
        budget_profile=RESEARCH_PROFILE,
        expected=Expectation(status="cancelled", mode="deep_research"),
        rationale="İptal sinyali araştırma graph'ında da cancelled terminaline eşlenir; kısmi rapor yanıltıcı olurdu.",
    ),
    EvalCase(
        case_id="l05",
        suite="lifecycle",
        areas=["checkpoint"],
        kind="resume",
        scenario="resume_evidence_stale",
        title="İçerik ilerlemişse kanıtlar yeniden kullanılmadan sürülür",
        question="Asyncio kuyruğunda önerilen üst sınır aralığı kaçtır?",
        article_id=ASYNCIO_ARTICLE_ID,
        expected=Expectation(
            status="completed",
            progress_contains="evidence_stale",
        ),
        rationale=(
            "Checkpoint sonrası makale revizyonu ilerledi: tam yeniden kullanım "
            "yanlış olur; güncel bağlamla sürülmesi ve bunun ilerleme olayında "
            "bildirilmesi beklenir."
        ),
    ),
    EvalCase(
        case_id="l06",
        suite="lifecycle",
        areas=["checkpoint"],
        kind="resume",
        scenario="resume_not_resumable",
        title="Geri gitmiş içerikte checkpoint devamı reddedilir",
        question="Asyncio kuyruğunda önerilen üst sınır aralığı kaçtır?",
        article_id=ASYNCIO_ARTICLE_ID,
        expected=Expectation(raises_error_code="stale_snapshot"),
        rationale=(
            "Checkpoint revizyonundan geri bir bağlama devam etmek bayat kanıt "
            "üretir; doğru davranış anlaşılır stale_snapshot reddidir."
        ),
    ),
    EvalCase(
        case_id="l07",
        suite="lifecycle",
        areas=["checkpoint"],
        kind="resume",
        scenario="resume_wrong_execution",
        title="Başka yürütme kimliğiyle devam reddedilir",
        question="Asyncio kuyruğunda önerilen üst sınır aralığı kaçtır?",
        article_id=ASYNCIO_ARTICLE_ID,
        expected=Expectation(raises_error_code="validation_error"),
        rationale=(
            "Checkpoint kararlı yürütme zincirine bağlıdır; farklı kimlikle gelen "
            "devam isteği anlaşılır validation_error ile reddedilir."
        ),
    ),
]

# ===========================================================================
# CACHE — önbellek anahtar sözleşmesi (plan A10 madde 5)
# ===========================================================================

_CACHE_CASES: list[EvalCase] = [
    EvalCase(
        case_id="c01",
        suite="cache",
        areas=["onbellek"],
        kind="cache",
        scenario="cache_same_content_same_key",
        title="Aynı içerik+istek aynı anahtarı üretir",
        question="Asyncio kuyruğunda önerilen üst sınır aralığı kaçtır?",
        article_id=ASYNCIO_ARTICLE_ID,
        expected=Expectation(),
        rationale=(
            "Aynı makale içeriği, dili ve kapsamıyla sorulan aynı soru aynı "
            "anahtarı üretmelidir; aksi halde önbellek boşuna ıska yapar."
        ),
    ),
    EvalCase(
        case_id="c02",
        suite="cache",
        areas=["onbellek"],
        kind="cache",
        scenario="cache_content_hash_changes_key",
        title="İçerik hash'i anahtara girer",
        question="Asyncio kuyruğunda önerilen üst sınır aralığı kaçtır?",
        article_id=ASYNCIO_ARTICLE_ID,
        expected=Expectation(),
        rationale=(
            "Makale revizyonu ilerleyince içerik hash'i değişir ve eski cevap "
            "anahtarı geçersiz kalmalıdır; aksi halde bayat cevap paylaşılır."
        ),
    ),
    EvalCase(
        case_id="c03",
        suite="cache",
        areas=["onbellek", "iki_dil"],
        kind="cache",
        scenario="cache_language_changes_key",
        title="Dil anahtara girer",
        question="Asyncio kuyruğunda önerilen üst sınır aralığı kaçtır?",
        article_id=ASYNCIO_ARTICLE_ID,
        expected=Expectation(),
        rationale="Aynı sorunun Türkçe ve İngilizce cevapları farklıdır; dil anahtarda olmalıdır.",
    ),
    EvalCase(
        case_id="c04",
        suite="cache",
        areas=["onbellek"],
        kind="cache",
        scenario="cache_scope_changes_key",
        title="Soru kapsamı anahtara girer",
        question="Asyncio kuyruğunda önerilen üst sınır aralığı kaçtır?",
        article_id=ASYNCIO_ARTICLE_ID,
        expected=Expectation(),
        rationale=(
            "Genel, makale ve seçim kapsamlı istekler farklı bağlam taşır; kapsam "
            "anahtarda yoksa seçim-bağlı cevap genel anahtarla paylaşılır."
        ),
    ),
    EvalCase(
        case_id="c05",
        suite="cache",
        areas=["onbellek", "takip_sorulari"],
        kind="cache",
        scenario="cache_config_and_conversation",
        title="Yapılandırma sürümü anahtarı değiştirir; konuşmalı sorular ortak önbelleğe girmez",
        question="Asyncio kuyruğunda önerilen üst sınır aralığı kaçtır?",
        article_id=ASYNCIO_ARTICLE_ID,
        expected=Expectation(),
        rationale=(
            "Prompt/şema sürümü değişince anahtar değişmelidir; konuşma geçmişi "
            "veya seçili metin taşıyan istekler ise ORTAK önbelleğe hiç girmemelidir."
        ),
    ),
]

CASES: list[EvalCase] = [
    *_ROUTING_CASES,
    *_QA_CASES,
    *_GUIDANCE_CASES,
    *_RESEARCH_CASES,
    *_LIFECYCLE_CASES,
    *_CACHE_CASES,
]


def case_by_id(case_id: str) -> EvalCase | None:
    return next((case for case in CASES if case.case_id == case_id), None)


def cases_for_suite(suite: str) -> list[EvalCase]:
    if suite == "all":
        return list(CASES)
    return [case for case in CASES if case.suite == suite]
