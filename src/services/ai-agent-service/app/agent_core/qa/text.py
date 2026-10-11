"""QA akışının deterministik metin yardımcıları (plan A4).

Gerçek LLM olmadan test edilebilir davranışın temeli buradaki saf
fonksiyonlardır: anlamlı terim çıkarımı (A3'ün Türkçe katlamalı
belirteçlemesiyle), genel-soru sınıfı, takip-sorusu sorgu kurulumu, tek
sorgu düzenleme denemesi ve seçili metnin makaleyle ilişki denetimi.

Kaynak ilişkisi: terim eşleşmesi A3 retrieval ile aynı ``fold_text`` +
``tokenize`` sözleşmesini kullanır; böylece soru-bölüm ilgisi indeksleme
ve arama ile aynı normalizasyonda ölçülür [ENG-CONTEXT#C1].
"""

from __future__ import annotations

from ..content.anchors import fold_text
from ..content.retrieval import tokenize
from ..models import ConversationTurn

__all__ = [
    "build_retrieval_query",
    "history_context_tokens",
    "is_generic_question",
    "is_related_to_article",
    "rewrite_query",
    "salient_tokens",
]

#: Anlam taşımayan yaygın sözcükler (katlanmış biçimde saklanır).
_STOPWORDS_RAW = (
    "bu", "şu", "o", "bunlar", "şunlar", "ve", "veya", "ile", "için", "gibi",
    "ama", "fakat", "ancak", "daha", "çok", "az", "bir", "kaç", "nasıl", "neden",
    "niye", "ne", "neyi", "neye", "kim", "nerede", "mı", "mi", "mu", "mü",
    "peki", "acaba", "ise", "de", "da", "ki", "göre", "diyor", "denir", "deniyor",
    "nedir", "misin", "mısın", "mısınız", "var", "yok", "olarak",
    "the", "a", "an", "is", "are", "was", "were", "be", "to", "of", "in", "on",
    "and", "or", "what", "which", "how", "why", "who", "where", "when",
    "this", "that", "these", "those", "it", "its", "does", "do", "can",
    "could", "should", "would", "about", "according",
)

_STOPWORDS = frozenset(fold_text(word) for word in _STOPWORDS_RAW)

#: "Bu makale ne anlatıyor?" gibi makaleyi bütün olarak soran kalıplar;
#: bölüm terimi gerektirmeyen sorularda makalenin kendisi kanıttır.
_GENERIC_SIGNALS = (
    "ana fikri", "ana fikir", "ne anlatıyor", "neyi anlatıyor", "neler anlatıyor",
    "hangi konu", "hangi konular", "genel olarak", "özeti", "özetle", "özetini",
    "makale nedir", "makale ne", "neler var", "what is this article about",
    "main idea", "main point", "in summary", "summarize the article",
    "article overview",
)

#: Terim sayımı ve sorgu kurulumunda kullanılan varsayılan alt sınır.
_MIN_TOKEN_LENGTH = 4

#: Sinyaller de katlanmış metinle karşılaştırılır (Türkçe karakter kaybına karşı).
_GENERIC_SIGNALS_FOLDED = tuple(fold_text(signal) for signal in _GENERIC_SIGNALS)


def salient_tokens(text: str, *, min_length: int = _MIN_TOKEN_LENGTH, max_tokens: int | None = None) -> list[str]:
    """Anlamlı terimleri döndürür: katlama + belirteçleme + dolgu sözcük süzümü.

    Yinelenenler korunmaz (ilk oluşum sırasıyla); ``max_tokens`` verilirse
    liste kırpılır. A3 ``tokenize`` sözleşmesiyle aynı normalizasyon.
    """

    seen: set[str] = set()
    tokens: list[str] = []
    for token in tokenize(text):
        if len(token) < min_length or token in _STOPWORDS or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
        if max_tokens is not None and len(tokens) >= max_tokens:
            break
    return tokens


def is_generic_question(question: str) -> bool:
    """Soru makaleyi bütün olarak mı soruyor (ana fikir/özet sınıfı)?

    Genel sınıfta bölüm düzeyinde terim örtüşmesi beklenmez; getirilen
    herhangi bir bölüm kanıt kabul edilir (plan A4 kabul ölçütü: "ana fikir").
    """

    folded = fold_text(question)
    if any(signal in folded for signal in _GENERIC_SIGNALS_FOLDED):
        return True
    # Tüm terimler dolguya düşmüşse soru içerik terimi taşımıyordur.
    return len(salient_tokens(question, min_length=3)) == 0


def history_context_tokens(
    question: str, history: list[ConversationTurn], *, max_tokens: int = 6
) -> list[str]:
    """Takip sorusu için konuşma geçmişinden taşınan bağlam terimleri.

    Yalnız soruda geçmeyen terimler alınır; sorgu zenginleştirmesi içindir,
    kanıt değildir (plan A4: "önceki model cevabını doğrulanmış kaynak
    yerine koyma").
    """

    if not history:
        return []
    question_tokens = set(salient_tokens(question, min_length=3))
    picked: list[str] = []
    seen: set[str] = set()
    for turn in reversed(history):
        for token in salient_tokens(turn.content, min_length=_MIN_TOKEN_LENGTH):
            if token in question_tokens or token in seen:
                continue
            seen.add(token)
            picked.append(token)
            if len(picked) >= max_tokens:
                return picked
    return picked


def build_retrieval_query(
    question: str, history: list[ConversationTurn] | None, *, max_history_tokens: int = 6
) -> str:
    """İlk arama sorgusu: soru + takip ise geçmişin bağlam terimleri.

    Takip soruları ("bunda", "peki" gibi), tamamlanmış konuşma geçmişindeki
    terimlerle hedef bölüme yönlendirilir (plan A4: "Takip sorularında
    tamamlanmış konuşma geçmişini kullan").
    """

    parts = [question.strip()]
    extra = history_context_tokens(question, history or [], max_tokens=max_history_tokens)
    if extra:
        parts.append(" ".join(extra))
    return " ".join(parts)


def rewrite_query(question: str) -> str:
    """Sınırlı sorgu düzenleme: sorunun kendi anlamlı terimleriyle odaklan.

    Düzenleme tek denemedir ve yalnız sorunun kendisinden terim alır;
    konuşma gürültüsü düşer [LG-RAG#C1]. Soru zaten yalınksa aynı sorgu
    döner; akış gereksiz ikinci arama yapmaz.
    """

    tokens = salient_tokens(question, max_tokens=8)
    return " ".join(tokens) if tokens else question.strip()


def is_related_to_article(selected_text: str, article_content: str) -> bool:
    """Seçili metin makaleden kopyalanmış mı? (plan A4: "selected_text
    değerinin makaleyle ilişkisini doğrula").

    Boşluk-normalize edilmiş alt dizin eşleşmesi kullanılır: kullanıcı
    seçimi biçim bozukluğuyla kopyalayabilir; ama birebir olmayan metin
    makale kanıtı sayılmaz.
    """

    normalized_selection = " ".join(selected_text.split())
    normalized_content = " ".join(article_content.split())
    if not normalized_selection:
        return False
    return normalized_selection in normalized_content
