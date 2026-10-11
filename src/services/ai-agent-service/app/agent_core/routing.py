"""Mod yönlendirme (plan A5): kurallar + belirsizlikte yapılandırılmış model çıktısı.

Plan A5: "Kesin durumlarda kuralları, belirsiz durumlarda yapılandırılmış
çıktı üreten router modelini kullan. LLM'nin ürettiği limitleri doğrudan
uygulama; doğrulanmış politika profiline eşle."

- Kesin durumlarda karar tamamen deterministiktir ve model çağrısı YAPMAZ
  (plan A1 kuralı: karar bir kez hesaplanır; ``01-agent-gelistirme-plani.md:186``).
- Belirsiz durumlarda ``router_model``'e yapılandırılmış JSON önerisi istenir
  [LG-WORKFLOWS#C1]; öneri doğrulanır ve sıkılanır: mod yalnız geçerli
  ``AgentMode`` değerine eşlenebilir, ``needs_web`` yalnız deep_research'te
  kabul edilir, açıklama sorusu yalnız soru metniyle birlikte kabul edilir ve
  modelin ürettiği HİÇBİR sayısal limit okunmaz — bütçe daima sunucunun
  doğrulanmış ``BudgetProfile``'ına (``budget_profile_id``) bağlanır.
- Yedi karar ölçütü (plan A5) sinyal kümesiyle karşılanır: doğrudan bilgi
  (fast), birden fazla bölüm (analysis), karşılaştırma/uyarlama (analysis),
  güncel dış kanıt (deep_research + needs_web), alt sorular/çok aşamalı
  araştırma (deep_research), açık kullanıcı tercihi (tercihe uyulur) ve
  makale bağlamının varlığı (eksikse açıklama sorusu; eksik kişisel bilgi
  asla tahminle tamamlanmaz).
- A5'te web araçları bağlı değildir (A6): ``needs_web=true`` kararlarının
  yürütmede özelliğin kullanılamaz olduğu doğru durumla bildirilir
  (``entrypoints.execute_plan``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from pydantic import Field, ValidationError

from .content.anchors import fold_text
from .content.retrieval import tokenize
from .errors import AgentErrorCode, PortError
from .models import (
    AgentMode,
    BusinessModel,
    ExecutionContext,
    ModePreference,
    RouteDecision,
    RunIntent,
    SourceScope,
)
from .ports import CancellationToken
from .ports.model import ModelProvider, ModelRequest

__all__ = [
    "RouterSuggestion",
    "AMBIGUOUS_QUESTION_THRESHOLD",
    "DEEP_RESEARCH_QUESTION_THRESHOLD",
    "MAX_ANSWER_HEADINGS",
    "build_router_request",
    "clarification_question_for",
    "decide_mode",
    "is_multi_part_question",
    "parse_router_suggestion",
    "route_for_context",
    "split_answer_headings",
]

#: Soru uzunluğu bu eşiği AŞAN ve çok bölümlü sorular araştırmaya yönlendirilir.
#: A1'den kalan eşik; A5'te tek başına uzunluk yetmez, çok bölümlülük de aranır
#: (kabul ölçütü: "uzun basit soru" fast'ta kalır).
DEEP_RESEARCH_QUESTION_THRESHOLD = 240

#: Sinyalsiz sorularda router modelinin devreye girdiği uzunluk eşiği.
AMBIGUOUS_QUESTION_THRESHOLD = 160

#: Analysis alt akışının ayıracağı en fazla cevap başlığı; aşan bölümler son
#: başlıkta birleşir (sınırsız alt soru yok — bütçe disiplini).
MAX_ANSWER_HEADINGS = 4

#: Derin araştırma gerektiren konu sinyalleri (tr/en). Alt dizin eşleşmesi,
#: küçük harfe katlanmış soru üzerinde yapılır.
_RESEARCH_SIGNALS = (
    "araştır", "incele", "derin", "rapor hazırla", "güncel durumu",
    "trend", "trends", "research", "deep dive", "state of", "literature",
    " alt soru", "kaç aşama",
)

#: Güncel dış kanıt belirteçleri (katlanmış belirteç düzeyi; "güncellerim"
#: gibi eylem fiillerini yakalamamak için alt dizin değil belirteç eşleşmesi).
_FRESHNESS_TOKENS = frozenset(
    {"guncel", "guncellici", "guncelligi", "guncelligini", "latest", "newest", "recent"}
)

#: Karşılaştırma/senaryo uyarlama belirteçleri (katlanmış belirteç düzeyi).
_COMPARISON_TOKENS = frozenset(
    {"fark", "farki", "karsilastir", "karsilastirma", "hangisi", "versus", "compare", "comparison", "difference"}
)

#: Açıklama/kod analizi sinyalleri: seçili metin varsa veya soru açıklama isterse.
_ANALYSIS_SIGNALS = (
    "açıkla", "nasıl çalışır", "kod", "ne yapıyor", "explain", "how does",
    "what does", "walk through", "review",
)

#: Makale bağlamına açık göndermeler; bağlam yokken belirsizlik sinyalidir
#: (ölçüt 7: "Gerekli makale bağlamı mevcut mu?").
_ARTICLE_REFERENCE_SIGNALS = (
    "bu makale", "makaledeki", "makalede", "yazıda", "yazardaki",
    "the article", "this article", "in the post", "yazıdaki",
)

#: Kişisel bağlam göndermeleri: profil/proje verisi olmadan bu sorular
#: tahminle cevaplanmaz, açıklama istenir (plan A5: "Eksik kişisel bilgi
#: tahminle tamamlanmasın"). Katlanmış metinde alt dizin.
_PERSONAL_CONTEXT_SIGNALS = (
    "projem", "kurulumum", "ortamim", "sistemim", "konfigurasyonum",
    "benim proj", "bana gore", "bende su", "bende soyle",
    "my project", "my setup", "my environment", "my config", "for my",
)


def _folded(text: str) -> str:
    return fold_text(text)


def _tokens_of(question: str) -> set[str]:
    return set(tokenize(question))


def _has_research_signal(question: str) -> bool:
    folded = _folded(question)
    return any(signal in folded for signal in _RESEARCH_SIGNALS)


def is_freshness_question(question: str) -> bool:
    """Soru güncel dış kanıt istiyor mu? (ölçüt 4; ``needs_web``).

    Belirteç düzeyi eşleşme, "nasıl güncellerim" gibi eylem sorularını
    araştırmaya yönlendirmeyi engeller.
    """
    return bool(_tokens_of(question) & _FRESHNESS_TOKENS)


def is_comparison_question(question: str) -> bool:
    """Soru karşılaştırma veya senaryoya uyarlama istiyor mu? (ölçüt 3)."""
    return bool(_tokens_of(question) & _COMPARISON_TOKENS)


def references_article(question: str) -> bool:
    """Soru bir makaleye açıkça mi gönderme yapıyor? (ölçüt 7 girdisi)."""
    folded = _folded(question)
    return any(signal in folded for signal in _ARTICLE_REFERENCE_SIGNALS)


def references_personal_context(question: str) -> bool:
    """Soru kullanıcının kişisel proje/ortam bilgisini mi gerektiriyor?"""
    folded = _folded(question)
    return any(signal in folded for signal in _PERSONAL_CONTEXT_SIGNALS)


# --- Çok bölümlü soru ayrıştırma (ölçüt 2; analysis alt akışının başlıkları) ---

_CLAUSE_BREAK_RE = re.compile(r"\?+|\n+|[;]")
_CONJUNCTION_SPLIT_RE = re.compile(r" ayrıca | veya | ve | plus | and ")


@dataclass(frozen=True)
class QuestionPart:
    """Çok bölümlü sorunun tek cevap başlığı; ``query`` retrieval sorgusudur."""

    text: str
    query: str


def split_answer_headings(
    question: str, *, max_headings: int = MAX_ANSWER_HEADINGS
) -> list[QuestionPart]:
    """Soruyu küçük cevap başlıklarına ayırır (plan A5 analysis alt akışı).

    Deterministik bölücü: soru işareti, satır sonu, noktalı virgül ve
    eşgüdümcü bağlaçlar ("ve/veya/ayrıca/and/plus"). Anlamlı terimi olmayan
    parçalar düşer; tek parça kalırsa soru bütünüdür. ``max_headings`` aşılırsa
    art parçalar son başlıkta birleşir — başlık sayısı bütçe sınırıdır.
    """
    text = " ".join(question.split())
    if not text:
        return []
    segments: list[str] = []
    for chunk in _CLAUSE_BREAK_RE.split(text):
        segments.extend(piece for piece in _CONJUNCTION_SPLIT_RE.split(chunk) if piece.strip())

    parts: list[QuestionPart] = []
    for segment in segments:
        cleaned = segment.strip(" ,.\t")
        if not cleaned or not _tokens_of(cleaned):
            continue
        parts.append(QuestionPart(text=cleaned, query=cleaned))
    if len(parts) <= 1:
        return [QuestionPart(text=text, query=text)] if text else []
    if len(parts) > max_headings:
        head, tail = parts[: max_headings - 1], parts[max_headings - 1 :]
        merged_tail = " ve ".join(part.text for part in tail)
        parts = [*head, QuestionPart(text=merged_tail, query=merged_tail)]
    return parts


def is_multi_part_question(question: str, *, max_headings: int = MAX_ANSWER_HEADINGS) -> bool:
    """Soru birden fazla bölümün ilişkilendirilmesini mi gerektiriyor? (ölçüt 2)."""
    return len(split_answer_headings(question, max_headings=max_headings)) > 1


def decide_mode(question: str, *, has_selection: bool, preference: ModePreference) -> AgentMode:
    """Deterministik mod kararı; ModelProvider kullanmaz.

    Sıra (plan A5 ölçütleri): açık tercih → seçili metin (analysis) →
    araştırma sinyali → güncellik (needs_web) → çok uzun ve çok bölümlü
    (deep_research) → çok bölümlü (analysis) → karşılaştırma (analysis) →
    açıklama sinyali (analysis) → fast.
    """
    if preference is not ModePreference.AUTO:
        return AgentMode(preference.value)

    if has_selection:
        return AgentMode.ANALYSIS
    if _has_research_signal(question):
        return AgentMode.DEEP_RESEARCH
    if is_freshness_question(question):
        return AgentMode.DEEP_RESEARCH
    multi_part = is_multi_part_question(question)
    if len(question) > DEEP_RESEARCH_QUESTION_THRESHOLD and multi_part:
        return AgentMode.DEEP_RESEARCH
    if multi_part:
        return AgentMode.ANALYSIS
    if is_comparison_question(question):
        return AgentMode.ANALYSIS
    folded = _folded(question)
    if any(signal in folded for signal in _ANALYSIS_SIGNALS):
        return AgentMode.ANALYSIS
    return AgentMode.FAST


def clarification_question_for(language: str) -> str:
    """Eksik bağlam/kişisel bilgi için deterministik açıklama sorusu.

    Eksik bilgi tahminle tamamlanmaz; kullanıcıdan istenir (plan A5).
    """
    if language.casefold().startswith("tr"):
        return (
            "Sorunuz kendi projenize veya kurulumunuza özgü bilgiler gerektiriyor; "
            "bu bilgiler elimde yok ve tahminle doldurulmaz. İlgili proje, ortam "
            "veya hata ayrıntılarını paylaşabilir misiniz?"
        )
    return (
        "Your question depends on details specific to your own project or setup; "
        "I do not have them and will not guess. Could you share the relevant "
        "project, environment or error details?"
    )


def _intent_for(
    question: str,
    *,
    has_selection: bool,
    mode: AgentMode,
    article_bound: bool,
) -> RunIntent:
    if mode is AgentMode.DEEP_RESEARCH:
        return RunIntent.RESEARCH
    folded = _folded(question)
    if has_selection or any(signal in folded for signal in _ANALYSIS_SIGNALS):
        return RunIntent.EXPLAIN
    if is_comparison_question(question):
        return RunIntent.COMPARE
    from .qa.text import is_generic_question  # yerel import: paket yükünü sınırlar

    if is_generic_question(question):
        return RunIntent.SUMMARIZE
    return RunIntent.ARTICLE_QA if article_bound else RunIntent.GENERAL


def _is_ambiguous(context: ExecutionContext, *, mode: AgentMode) -> bool:
    """Kuralların kesin karar veremediği durum: router modeli sorulur.

    Kesin durumlar: açık tercih, seçili metin, araştırma/güncellik,
    karşılaştırma, çok bölümlülük, açıklama sinyali ve kişisel-bilgi kuralı.
    Belirsiz: açık makale göndermesi olup bağlamın olmadığı sorular ve
    sinyalsiz uzun sorular.
    """
    if context.mode_preference is not ModePreference.AUTO:
        return False
    question = context.question
    if context.selected_text is not None:
        return False
    if _has_research_signal(question) or is_freshness_question(question):
        return False
    if mode is AgentMode.ANALYSIS:
        return False
    if references_personal_context(question):
        return False
    if references_article(question) and not (context.article_id or context.article_snapshot):
        return True
    return len(question) > AMBIGUOUS_QUESTION_THRESHOLD


_ROUTER_SYSTEM_PROMPT = (
    "Sen soru yönlendiren bir routersın. Yalnızca geçerli bir JSON nesnesi üret; "
    "başka metin yazma. Şema:\n"
    '{"intent": "article_qa|summarize|explain|compare|research|general", '
    '"selected_mode": "fast|analysis|deep_research", '
    '"needs_web": true|false, '
    '"needs_clarification": true|false, '
    '"clarification_question": "string veya null", '
    '"brief_reason": "kısa gerekçe"}\n'
    "Bütçe, limit veya sayısal değer üretme; onlar politika profiliyle belirlenir."
)


def build_router_request(context: ExecutionContext) -> ModelRequest:
    """Belirsiz durum için yapılandırılmış öneri isteği (deterministik)."""
    facts: list[str] = [f"Soru ({context.language}): {context.question}"]
    facts.append(
        "Makale bağlamı: var" if context.article_id or context.article_snapshot else "Makale bağlamı: yok"
    )
    if context.selected_text is not None:
        facts.append("Seçili metin: var")
    if context.conversation_history:
        facts.append("Konuşma geçmişi: var")
    return ModelRequest(
        prompt="\n".join(facts),
        system=_ROUTER_SYSTEM_PROMPT,
        metadata={"run_id": context.run_id, "role": "router", "output": "json"},
    )


class RouterSuggestion(BusinessModel):
    """Router modelinin doğrulanmış önerisi; yalnız kategorik alanlar taşır.

    Sayısal limit alanı YOKTUR: modelin ürettiği limitler hiçbir aşamada
    okunmaz, karar doğrulanmış politika profiline eşlenir (plan A5).
    """

    intent: RunIntent = RunIntent.ARTICLE_QA
    selected_mode: AgentMode = AgentMode.FAST
    needs_web: bool = False
    needs_clarification: bool = False
    clarification_question: str | None = Field(default=None, max_length=2000)
    brief_reason: str | None = Field(default=None, max_length=500)


def _parse_json_object(text: str) -> dict | None:
    """Model metninden ilk JSON nesnesini çıkarır; kod çiti toleranslı."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped).strip()
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match is None:
            return None
        try:
            parsed = json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            return None
    return parsed if isinstance(parsed, dict) else None


def parse_router_suggestion(text: str) -> RouterSuggestion | None:
    """Model çıktısını doğrulanmış öneriye çevirir; geçersizse ``None``.

    Dönüşümde sıkma uygulanır: ``needs_web`` yalnız ``deep_research`` ile
    tutarlıysa kalır, açıklama sorusu boşsa ``needs_clarification`` düşer.
    """
    payload = _parse_json_object(text)
    if payload is None:
        return None
    mode_raw = payload.get("selected_mode") or payload.get("mode")
    intent_raw = payload.get("intent")
    try:
        mode = AgentMode(str(mode_raw))
    except ValueError:
        return None
    try:
        intent = RunIntent(str(intent_raw)) if intent_raw is not None else RunIntent.ARTICLE_QA
    except ValueError:
        intent = RunIntent.ARTICLE_QA
    needs_web = bool(payload.get("needs_web")) and mode is AgentMode.DEEP_RESEARCH
    question = payload.get("clarification_question")
    needs_clarification = bool(payload.get("needs_clarification")) and isinstance(question, str) and bool(question.strip())
    reason = payload.get("brief_reason")
    try:
        return RouterSuggestion(
            intent=intent,
            selected_mode=mode,
            needs_web=needs_web,
            needs_clarification=needs_clarification,
            clarification_question=question.strip() if needs_clarification and isinstance(question, str) else None,
            brief_reason=str(reason)[:500] if reason else None,
        )
    except ValidationError:
        return None


def _rule_decision(context: ExecutionContext, *, mode: AgentMode) -> RouteDecision:
    """Kural tabanlı tam karar: 8 alan + sinyal gerekçesi."""
    question = context.question
    has_selection = context.selected_text is not None
    article_bound = bool(context.article_id or context.article_snapshot)
    freshness = is_freshness_question(question)
    research = _has_research_signal(question)
    explicit_deep = context.mode_preference is ModePreference.DEEP_RESEARCH
    intent = _intent_for(question, has_selection=has_selection, mode=mode, article_bound=article_bound)

    if context.mode_preference is not ModePreference.AUTO:
        reason = f"kullanıcı tercihi: {context.mode_preference.value}"
    elif has_selection:
        reason = "seçili metin açıklaması"
    elif research:
        reason = "araştırma sinyali: alt sorular/çok aşamalı araştırma"
    elif freshness:
        reason = "güncellik sorusu: güncel dış kanıt gerekiyor"
    elif is_multi_part_question(question):
        reason = "çok bölümlü soru: birden fazla bölüm ilişkilendirilmeli"
    elif is_comparison_question(question):
        reason = "karşılaştırma/uyarlama sorusu"
    elif any(signal in _folded(question) for signal in _ANALYSIS_SIGNALS):
        reason = "açıklama/kod analizi sorusu"
    else:
        reason = "kısa ve tekil soru: doğrudan bilgi araması yeterli"

    needs_clarification = references_personal_context(question)
    needs_web = mode is AgentMode.DEEP_RESEARCH and (explicit_deep or freshness or research)
    return RouteDecision(
        run_id=context.run_id,
        selected_mode=mode,
        intent=intent,
        source_scope=(
            SourceScope.ARTICLE_AND_WEB
            if needs_web
            else SourceScope.ARTICLE if article_bound
            else SourceScope.GENERAL
        ),
        needs_web=needs_web,
        needs_clarification=needs_clarification,
        clarification_question=(
            clarification_question_for(context.language) if needs_clarification else None
        ),
        brief_reason=reason,
        # LLM'in ürettiği limitler uygulanmaz: bütçe daima sunucu profiline bağlı.
        budget_profile_id=context.budget_profile.name,
        decided_at=datetime.now(timezone.utc),
    )


def _merge_suggestion(
    context: ExecutionContext, base: RouteDecision, suggestion: RouterSuggestion
) -> RouteDecision:
    """Doğrulanmış öneriyi kural kararıyla birleştirir; değişmezler korunur.

    Eşleme kuralları: mod ve görev türü öneriden; ``needs_web`` yalnız
    ``deep_research`` ile; açıklama sorusu yalnız soru metniyle; bütçe profili
    daima sunucu profili. Mod önerisi deep_research'e çıkar ama gerekçe
    araştırma/güncellik sinyali taşımıyorsa ``needs_web`` false kalır (taşıma
    değişmezi: web bayrağı yalnız deep_research'te true).
    """
    mode = suggestion.selected_mode
    needs_web = suggestion.needs_web and mode is AgentMode.DEEP_RESEARCH
    article_bound = bool(context.article_id or context.article_snapshot)
    reason = suggestion.brief_reason or base.brief_reason
    return RouteDecision(
        run_id=context.run_id,
        selected_mode=mode,
        intent=suggestion.intent,
        source_scope=(
            SourceScope.ARTICLE_AND_WEB
            if needs_web
            else SourceScope.ARTICLE if article_bound
            else SourceScope.GENERAL
        ),
        needs_web=needs_web,
        needs_clarification=suggestion.needs_clarification,
        clarification_question=suggestion.clarification_question,
        brief_reason=f"router modeli önerisi: {reason}",
        budget_profile_id=context.budget_profile.name,
        decided_at=datetime.now(timezone.utc),
    )


async def route_for_context(
    context: ExecutionContext,
    *,
    router_model: ModelProvider | None = None,
    cancel: CancellationToken | None = None,
) -> RouteDecision:
    """``ExecutionContext`` için bir kez rota kararı üretir.

    Kesin durumlarda kurallar uygulanır ve model çağrılmaz; belirsiz
    durumlarda ``router_model`` varsa yapılandırılmış öneri istenir, öneri
    doğrulanıp politika profiline eşlenir. Öneri geçersizse ya da model
    arızalanırsa (iptal hariç) deterministik kural kararı kullanılır ve bu
    gerekçede belirtilir.

    Raises:
        PortError: ``cancelled`` — iptal sinyali (model çağrısı sırasında).
    """
    mode = decide_mode(
        context.question,
        has_selection=context.selected_text is not None,
        preference=context.mode_preference,
    )
    decision = _rule_decision(context, mode=mode)
    if router_model is None or not _is_ambiguous(context, mode=mode):
        return decision

    try:
        response = await router_model.complete(build_router_request(context), cancel=cancel)
    except PortError as error:
        if error.code is AgentErrorCode.CANCELLED:
            raise
        return decision.model_copy(
            update={
                "brief_reason": (
                    f"{decision.brief_reason}; router modeli kullanılamadı "
                    f"({error.code.value}), deterministik kural uygulandı"
                )
            }
        )

    suggestion = parse_router_suggestion(response.text)
    if suggestion is None:
        return decision.model_copy(
            update={
                "brief_reason": (
                    f"{decision.brief_reason}; router modeli çıktısı doğrulanamadı, "
                    "deterministik kural uygulandı"
                )
            }
        )
    return _merge_suggestion(context, decision, suggestion)
