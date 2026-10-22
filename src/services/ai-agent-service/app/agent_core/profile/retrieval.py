"""Profil corpus'u için yerel lexical retrieval (BM25 + TR/EN alias genişletme).

- Yalnız pinlenmiş belgenin ``retrievable`` (public) bölümleri indekslenir;
  makale, web, kullanıcı geçmişi veya seçili metin bu depoya KARIŞMAZ —
  indeks girdisi yalnız ``ProfileDocument``'tir.
- Saf araçlar yeniden kullanılır: ``content.anchors.fold_text`` (Türkçe
  katlama), ``content.retrieval.tokenize`` ve ``bm25_scores``.
- Türkçe ek toleransı: belirteçler 5 karakterlik köke indirgenir
  ("egitimini" → "egiti"; "universite"/"university" → "unive").
- TR/EN alias genişletme: ``profile.json`` bölüm alias'ları sürümlüdür ve
  profille birlikte gelir. Alias eşleşmesi yalnız ilgili bölümün skorunu
  artırır; yeni olgu taşımaz (modele alias metni gönderilmez).
- Sahip adı belirteçleri (sample, author, mrbekox) düşük ağırlıkla sayılır:
  her soru Sample'ı anar, ayırt edici değildir.
- Bütçe: soruya bağlı sınırlı top-k ve toplam bağlam token bütçesi
  (fast 4/1800, analysis 6/2800, deep_research 8/3800).
- Önbellek: indeks snapshot başına bir kez kurulur (aynı snapshot yeniden
  indekslenmez); sorgu sonucu sınırlı LRU'dadır. Anahtarlar profile_id,
  revision, content_hash, dil, normalize sorgu, top-k, bütçe, chunker ve
  indeks sürümünü kapsar. Bu yol gerçek anlamsal embedding DEĞİLDİR.
- Anlamsal genişleme portu (opsiyonel, ``ProfileEmbedding``): gerçek bir
  ``EmbeddingProvider`` verilirse lexical adaylar RRF ile yeniden sıralanır
  (``retrieve_async``). Yeterlilik kararı lexical kalır (embedding kanıt
  uydurmaz); önbellek anahtarına embedding model kimliği girer. Test double /
  hash sağlayıcısı (``is_test_double``) üretimde yok sayılır — anlamsal başarı
  diye sunulmaz. Varsayılan kompozisyonda embedding yoktur (vector DB önkoşul
  değildir).
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass

from typing import Any

from ..content.anchors import fold_text
from ..content.config import EmbeddingModelConfig
from ..content.retrieval import RRF_K, bm25_scores, cosine_similarity, tokenize
from ..models import AgentMode
from ..ports import CancellationToken
from .chunking import CHUNKER_VERSION, ProfileChunk, chunk_document
from .detection import owner_name_tokens
from .source import ProfileDocument

__all__ = [
    "DEFAULT_PROFILE_RETRIEVER",
    "INDEX_VERSION",
    "SUFFICIENCY_THRESHOLD",
    "MODE_RETRIEVAL_BUDGETS",
    "ProfileEmbedding",
    "ProfileIndex",
    "ProfileRetriever",
    "RetrievalBudget",
    "RetrievalResult",
    "RetrievedChunk",
    "budget_for_mode",
    "normalize_query",
]

INDEX_VERSION = "profile-bm25-alias/1"

#: Kök uzunluğu: Türkçe ekleri ve TR/EN ortak kökleri ("unive") birleştirir.
_STEM_LENGTH = 5
#: Sahip adı belirteçlerinin BM25 ağırlığı.
_OWNER_TOKEN_WEIGHT = 0.2
#: Alias eşleşmesi başına temel bölüm artışı (bölüm sayısına bölünür).
_ALIAS_BASE = 6.0
#: Genel/işlev kelimesi niteliğindeki alias'lar zayıf sayılır.
_GENERIC_ALIAS_WEIGHT = 0.4
_GENERIC_ALIASES = frozenset(
    {
        "who", "about", "kim", "hakkinda", "background", "focus", "odak", "approach", "yaklasim", "stack",
        "uses", "knows", "kullaniyor", "biliyor", "blog", "site", "test", "tests", "version", "surum",
        "skill", "skills", "x", "ai",
    }
)
#: Seçim eşikleri: mutlak alt sınır ve en iyi skora göre göreli oran.
_MIN_CHUNK_SCORE = 0.8
_RELATIVE_FLOOR = 0.25
#: Kanıt yeterliliği: en iyi skor bu eşiğin altındaysa cevap üretilmez.
SUFFICIENCY_THRESHOLD = 3.0

_STOPWORDS = frozenset(
    {
        # tr
        "ve", "ile", "bir", "bu", "su", "o", "ne", "mi", "mu", "da", "de", "ki", "icin", "gibi", "hangi",
        "nedir", "neler", "nelerdir", "var", "nasil", "olan", "olarak", "kadar", "daha", "cok", "en", "ya",
        "veya", "ama", "ise", "hem", "her", "ben", "sen", "biz", "siz", "onun", "onu", "beni", "bana",
        "sana", "peki", "acaba", "midir", "mudur", "misin", "musun", "oldu", "olur", "mi", "dir", "dur",
        "in", "un", "nin", "nun", "yi", "yu", "ye", "ya", "a", "e", "i", "u", "li", "lu",
        "anlat", "anlatir", "acikla", "aciklar", "ozetle", "soyle", "soyler", "bahset", "hakkinda",
        "kisaca", "lutfen", "sence", "bilgi", "ver", "verir", "misiniz", "musunuz",
        # en
        "the", "an", "is", "are", "was", "were", "be", "been", "of", "on", "at", "to", "for", "and",
        "or", "what", "which", "does", "do", "did", "he", "his", "him", "has", "have", "had", "with",
        "how", "whats", "s", "tell", "me", "please", "can", "could", "you", "your", "my", "it", "its",
        "this", "that", "there", "any", "some", "explain", "describe", "summarize", "about", "who",
        "give", "brief", "briefly", "list",
    }
)


@dataclass(frozen=True)
class RetrievalBudget:
    """Soruya bağlı sınırlı top-k ve toplam bağlam token bütçesi."""

    top_k: int
    max_context_tokens: int


#: Mod başına retrieval bütçesi (K1): farkı yalnız retrieval derinliğidir.
MODE_RETRIEVAL_BUDGETS: dict[AgentMode, RetrievalBudget] = {
    AgentMode.FAST: RetrievalBudget(top_k=4, max_context_tokens=1800),
    AgentMode.ANALYSIS: RetrievalBudget(top_k=6, max_context_tokens=2800),
    AgentMode.DEEP_RESEARCH: RetrievalBudget(top_k=8, max_context_tokens=3800),
}


def budget_for_mode(mode: AgentMode) -> RetrievalBudget:
    return MODE_RETRIEVAL_BUDGETS[mode]


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: ProfileChunk
    score: float


@dataclass(frozen=True)
class RetrievalResult:
    """Sınırlı ve sıralı retrieval sonucu."""

    chunks: tuple[RetrievedChunk, ...]
    normalized_query: str
    top_score: float
    alias_sections: tuple[str, ...]
    matched_terms: int
    sufficient: bool
    cached: bool = False
    #: Anlamsal yeniden sıralamada kullanılan embedding modeli; lexical-only'de None.
    semantic_model: str | None = None

    @property
    def section_ids(self) -> list[str]:
        seen: list[str] = []
        for item in self.chunks:
            if item.chunk.section_id not in seen:
                seen.append(item.chunk.section_id)
        return seen

    @property
    def context_tokens(self) -> int:
        return sum(item.chunk.token_count for item in self.chunks)


def normalize_query(text: str) -> str:
    """Önbellek anahtarı için normalize sorgu: katlanmış, boşlukları sadeleşmiş."""

    return " ".join(fold_text(text).split())


def _stem(token: str) -> str:
    return token[:_STEM_LENGTH] if len(token) > _STEM_LENGTH else token


def _content_tokens(text: str) -> list[str]:
    return [token for token in tokenize(text) if len(token) >= 2 and token not in _STOPWORDS]


@dataclass(frozen=True)
class _AliasPattern:
    alias: str
    tokens: tuple[str, ...]
    weight: float


def _alias_matches(alias_tokens: tuple[str, ...], query_tokens: list[str]) -> bool:
    """Alias belirteç dizisi sorguda bitişik geçiyor mu? (Türkçe ek toleranslı)."""

    size = len(alias_tokens)
    if size == 0 or size > len(query_tokens):
        return False
    for start in range(len(query_tokens) - size + 1):
        ok = True
        for offset, alias_token in enumerate(alias_tokens):
            query_token = query_tokens[start + offset]
            if query_token == alias_token:
                continue
            if len(alias_token) >= 4 and query_token.startswith(alias_token):
                continue
            # Türkçe mastar alias'ı ("ulaşmak") fiil köküyle eşleşir ("ulaşabilirim").
            if len(alias_token) >= 6 and alias_token.endswith(("mak", "mek")) and query_token.startswith(alias_token[:-3]):
                continue
            ok = False
            break
        if ok:
            return True
    return False


class ProfileIndex:
    """Tek profil snapshot'ının lexical indeksi (değişmez)."""

    def __init__(self, document: ProfileDocument, chunks: list[ProfileChunk]) -> None:
        self.snapshot = document.snapshot
        self.chunks = chunks
        self.section_order = {section.section_id: i for i, section in enumerate(document.sections)}
        docs: list[list[str]] = []
        for chunk in chunks:
            text = " ".join(
                [chunk.title, chunk.title_en or "", " ".join(chunk.heading_path), chunk.evidence_text]
            )
            docs.append([_stem(token) for token in _content_tokens(text)])
        self.doc_tokens = docs

        alias_sections: dict[str, set[str]] = {}
        raw_aliases: dict[str, list[str]] = {}
        for section in document.retrievable_sections():
            phrases: list[str] = []
            for values in section.aliases.values():
                for alias in values:
                    folded = " ".join(tokenize(alias))
                    if folded and folded not in phrases:
                        phrases.append(folded)
            raw_aliases[section.section_id] = phrases
            for folded in phrases:
                alias_sections.setdefault(folded, set()).add(section.section_id)
        self.alias_patterns: dict[str, list[_AliasPattern]] = {}
        for section_id, phrases in raw_aliases.items():
            patterns: list[_AliasPattern] = []
            for folded in phrases:
                tokens = tuple(folded.split())
                spread = len(alias_sections.get(folded, {section_id}))
                weight = _ALIAS_BASE / spread * (1.0 + 0.25 * (len(tokens) - 1))
                if folded in _GENERIC_ALIASES:
                    weight *= _GENERIC_ALIAS_WEIGHT
                patterns.append(_AliasPattern(alias=folded, tokens=tokens, weight=weight))
            self.alias_patterns[section_id] = patterns

    def alias_boosts(self, query: str) -> dict[str, float]:
        """Bölüm → alias artışı; eşleşme yoksa boş sözlük."""

        query_tokens = tokenize(query)
        boosts: dict[str, float] = {}
        for section_id, patterns in self.alias_patterns.items():
            total = sum(p.weight for p in patterns if _alias_matches(p.tokens, query_tokens))
            if total > 0:
                boosts[section_id] = total
        return boosts

    def score(self, query: str) -> tuple[list[float], dict[str, float], int]:
        """Parça başına skor, alias artışları ve eşleşen içerik terimi sayısı."""

        owner = {_stem(token) for token in owner_name_tokens()}
        terms: dict[str, float] = {}
        for token in _content_tokens(query):
            stem = _stem(token)
            terms[stem] = _OWNER_TOKEN_WEIGHT if stem in owner else 1.0
        totals = [0.0] * len(self.chunks)
        matched_terms = 0
        for term, weight in terms.items():
            scores = bm25_scores([term], self.doc_tokens)
            if any(value > 0 for value in scores) and weight >= 1.0:
                matched_terms += 1
            for index, value in enumerate(scores):
                totals[index] += weight * value
        boosts = self.alias_boosts(query)
        for index, chunk in enumerate(self.chunks):
            totals[index] += boosts.get(chunk.section_id, 0.0)
        return totals, boosts, matched_terms


@dataclass(frozen=True)
class ProfileEmbedding:
    """Opsiyonel anlamsal yeniden sıralama: ``EmbeddingProvider`` + model kimliği."""

    provider: Any
    model: EmbeddingModelConfig
    #: Yalnız testlerde: test double sağlayıcıyı kullanmaya izin verir.
    allow_test_double: bool = False

    @property
    def usable(self) -> bool:
        return self.allow_test_double or not getattr(self.provider, "is_test_double", False)


#: Anlamsal yeniden sıralamaya giren lexical aday çarpanı (top_k × N).
_SEMANTIC_CANDIDATE_FACTOR = 3


class ProfileRetriever:
    """Snapshot başına indeks önbelleği + sınırlı LRU sorgu önbelleği; thread-safe."""

    def __init__(
        self,
        *,
        index_capacity: int = 4,
        cache_capacity: int = 256,
        embedding: ProfileEmbedding | None = None,
    ) -> None:
        self._index_capacity = max(index_capacity, 1)
        self._cache_capacity = max(cache_capacity, 1)
        self._indexes: OrderedDict[tuple, ProfileIndex] = OrderedDict()
        self._results: OrderedDict[tuple, RetrievalResult] = OrderedDict()
        self._chunk_vectors: OrderedDict[tuple, list[float]] = OrderedDict()
        self._lock = threading.Lock()
        #: Test double/hash sağlayıcısı anlamsal sayılmaz: yok sayılır ve işaretlenir.
        self._embedding = embedding if embedding is not None and embedding.usable else None
        self.embedding_ignored = embedding is not None and self._embedding is None
        #: Kurulan indeks sayısı (aynı snapshot yeniden indekslenmez — testlerde ölçülür).
        self.index_builds = 0

    @property
    def semantic_model(self) -> str | None:
        return self._embedding.model.model_id if self._embedding is not None else None

    @staticmethod
    def _index_key(document: ProfileDocument) -> tuple:
        snap = document.snapshot
        return (snap.profile_id, snap.revision, snap.content_hash, CHUNKER_VERSION, INDEX_VERSION)

    def index_for(self, document: ProfileDocument) -> ProfileIndex:
        key = self._index_key(document)
        with self._lock:
            index = self._indexes.get(key)
            if index is not None:
                self._indexes.move_to_end(key)
                return index
        built = ProfileIndex(document, chunk_document(document))
        with self._lock:
            existing = self._indexes.get(key)
            if existing is not None:
                return existing
            self._indexes[key] = built
            self.index_builds += 1
            while len(self._indexes) > self._index_capacity:
                self._indexes.popitem(last=False)
        return built

    def has_profile_signal(self, document: ProfileDocument, query: str) -> bool:
        """Sorgu bir bölüm alias'ına değiyor mu? (takip sorusu çözümlemesi girdisi)."""

        return bool(self.index_for(document).alias_boosts(query))

    def retrieve(
        self,
        document: ProfileDocument,
        query: str,
        *,
        language: str,
        budget: RetrievalBudget,
    ) -> RetrievalResult:
        normalized = normalize_query(query)
        snap = document.snapshot
        cache_key = (
            snap.profile_id,
            snap.revision,
            snap.content_hash,
            language.casefold()[:2],
            normalized,
            budget.top_k,
            budget.max_context_tokens,
            CHUNKER_VERSION,
            INDEX_VERSION,
        )
        with self._lock:
            cached = self._results.get(cache_key)
            if cached is not None:
                self._results.move_to_end(cache_key)
                return RetrievalResult(
                    chunks=cached.chunks,
                    normalized_query=cached.normalized_query,
                    top_score=cached.top_score,
                    alias_sections=cached.alias_sections,
                    matched_terms=cached.matched_terms,
                    sufficient=cached.sufficient,
                    cached=True,
                )

        index = self.index_for(document)
        result = self._rank(index, normalized, budget)
        with self._lock:
            self._results[cache_key] = result
            while len(self._results) > self._cache_capacity:
                self._results.popitem(last=False)
        return result

    async def retrieve_async(
        self,
        document: ProfileDocument,
        query: str,
        *,
        language: str,
        budget: RetrievalBudget,
        cancel: CancellationToken | None = None,
    ) -> RetrievalResult:
        """Embedding yapılandırılmışsa lexical adayları RRF ile yeniden sıralar; yoksa ``retrieve``."""

        if self._embedding is None:
            return self.retrieve(document, query, language=language, budget=budget)
        normalized = normalize_query(query)
        snap = document.snapshot
        model_id = self._embedding.model.model_id
        cache_key = (
            snap.profile_id, snap.revision, snap.content_hash, language.casefold()[:2], normalized,
            budget.top_k, budget.max_context_tokens, CHUNKER_VERSION, INDEX_VERSION, model_id,
        )
        with self._lock:
            cached = self._results.get(cache_key)
            if cached is not None:
                self._results.move_to_end(cache_key)
                return RetrievalResult(**{**cached.__dict__, "cached": True})

        index = self.index_for(document)
        wide = RetrievalBudget(top_k=budget.top_k * _SEMANTIC_CANDIDATE_FACTOR, max_context_tokens=10**9)
        lexical = self._rank(index, normalized, wide)
        if not lexical.sufficient or not lexical.chunks:
            # Yeterlilik lexical kalır: embedding kanıt uydurmaz.
            result = self._rank(index, normalized, budget)
        else:
            result = await self._semantic_rerank(index, normalized, lexical, budget, cancel=cancel)
        with self._lock:
            self._results[cache_key] = result
            while len(self._results) > self._cache_capacity:
                self._results.popitem(last=False)
        return result

    async def _semantic_rerank(
        self,
        index: ProfileIndex,
        normalized: str,
        lexical: RetrievalResult,
        budget: RetrievalBudget,
        *,
        cancel: CancellationToken | None,
    ) -> RetrievalResult:
        embedding = self._embedding
        assert embedding is not None
        model_id = embedding.model.model_id
        candidates = [item.chunk for item in lexical.chunks]
        missing = [chunk for chunk in candidates if (model_id, chunk.source_id) not in self._chunk_vectors]
        texts = [normalized] + [chunk.evidence_text for chunk in missing]
        vectors = await embedding.provider.embed(texts, cancel=cancel)
        query_vector = vectors[0]
        with self._lock:
            for chunk, vector in zip(missing, vectors[1:]):
                self._chunk_vectors[(model_id, chunk.source_id)] = vector
            while len(self._chunk_vectors) > self._cache_capacity * 4:
                self._chunk_vectors.popitem(last=False)
            chunk_vectors = [self._chunk_vectors[(model_id, chunk.source_id)] for chunk in candidates]
        semantic_order = sorted(
            range(len(candidates)), key=lambda i: -cosine_similarity(query_vector, chunk_vectors[i])
        )
        fused = [0.0] * len(candidates)
        for rank, i in enumerate(range(len(candidates)), start=1):
            fused[i] += 1.0 / (RRF_K + rank)
        for rank, i in enumerate(semantic_order, start=1):
            fused[i] += 1.0 / (RRF_K + rank)
        order = sorted(range(len(candidates)), key=lambda i: -fused[i])
        selected: list[RetrievedChunk] = []
        used_tokens = 0
        for i in order:
            if len(selected) >= budget.top_k:
                break
            chunk = candidates[i]
            if used_tokens + chunk.token_count > budget.max_context_tokens:
                continue
            selected.append(RetrievedChunk(chunk=chunk, score=round(fused[i], 6)))
            used_tokens += chunk.token_count
        return RetrievalResult(
            chunks=tuple(selected),
            normalized_query=normalized,
            top_score=lexical.top_score,
            alias_sections=lexical.alias_sections,
            matched_terms=lexical.matched_terms,
            sufficient=bool(selected),
            semantic_model=model_id,
        )

    @staticmethod
    def _rank(index: ProfileIndex, normalized: str, budget: RetrievalBudget) -> RetrievalResult:
        if not normalized or not index.chunks:
            return RetrievalResult((), normalized, 0.0, (), 0, False)
        scores, boosts, matched_terms = index.score(normalized)
        order = sorted(
            range(len(index.chunks)),
            key=lambda i: (
                -scores[i],
                index.section_order.get(index.chunks[i].section_id, 0),
                index.chunks[i].chunk_index,
            ),
        )
        top = scores[order[0]] if order else 0.0
        floor = max(_MIN_CHUNK_SCORE, top * _RELATIVE_FLOOR)
        selected: list[RetrievedChunk] = []
        used_tokens = 0
        for i in order:
            if len(selected) >= budget.top_k:
                break
            if scores[i] < floor:
                break
            chunk = index.chunks[i]
            if used_tokens + chunk.token_count > budget.max_context_tokens:
                continue
            selected.append(RetrievedChunk(chunk=chunk, score=round(scores[i], 6)))
            used_tokens += chunk.token_count
        sufficient = bool(selected) and top >= SUFFICIENCY_THRESHOLD and (bool(boosts) or matched_terms > 0)
        return RetrievalResult(
            chunks=tuple(selected),
            normalized_query=normalized,
            top_score=round(top, 6),
            alias_sections=tuple(sorted(boosts)),
            matched_terms=matched_terms,
            sufficient=sufficient,
        )


#: Süreç genelinde paylaşılan varsayılan retriever (worker ömrü boyunca önbellek korunur).
DEFAULT_PROFILE_RETRIEVER = ProfileRetriever()

