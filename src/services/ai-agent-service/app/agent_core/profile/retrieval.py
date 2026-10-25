"""Canonical profile retrieval using lexical evidence and real embeddings.

Only public sections of a pinned profile snapshot become candidates. BM25 and
versioned TR/EN aliases establish evidence sufficiency; the production worker's
OpenAI provider reranks candidates with reciprocal rank fusion. Semantic scores
cannot create evidence when lexical retrieval finds no relevant source.

Bounded caches distinguish profile revision/hash, embedding model/dimensions,
and exact evidence text, including editor notes. The synchronous lexical API
remains available for source inspection and deterministic evidence checks.
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from dataclasses import dataclass

from ..content.anchors import fold_text
from ..content.config import EmbeddingModelConfig
from ..content.postgres import validate_vectors
from ..content.retrieval import RRF_K, bm25_scores, cosine_similarity, tokenize
from ..models import AgentMode
from ..ports import CancellationToken, EmbeddingProvider
from ..telemetry import trace_operation
from .chunking import CHUNKER_VERSION, ProfileChunk, chunk_document
from .detection import ProfileIdentity, owner_name_tokens
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
        self.owner_tokens = owner_name_tokens(ProfileIdentity.from_document(document))
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

        owner = {_stem(token) for token in self.owner_tokens}
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
    """Configured semantic provider and the index identity of its real vectors."""

    provider: EmbeddingProvider
    model: EmbeddingModelConfig


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
        self._embedding = embedding
        #: Kurulan indeks sayısı (aynı snapshot yeniden indekslenmez — testlerde ölçülür).
        self.index_builds = 0

    @property
    def semantic_model(self) -> str | None:
        return self._embedding.model.model_id if self._embedding is not None else None

    @staticmethod
    def _index_key(document: ProfileDocument) -> tuple:
        snap = document.snapshot
        return (snap.profile_id, snap.revision, snap.content_hash, CHUNKER_VERSION, INDEX_VERSION)

    @staticmethod
    def _vector_key(index: ProfileIndex, chunk: ProfileChunk, model: EmbeddingModelConfig) -> tuple:
        snapshot = index.snapshot
        evidence_hash = hashlib.sha256(chunk.evidence_text.encode("utf-8")).hexdigest()
        return (
            model.model_id, model.dimensions, snapshot.profile_id, snapshot.revision,
            snapshot.content_hash, chunk.source_id, evidence_hash,
        )

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
        with trace_operation("retrieval"):
            return await self._retrieve_async(document, query, language=language, budget=budget, cancel=cancel)

    async def _retrieve_async(
        self,
        document: ProfileDocument,
        query: str,
        *,
        language: str,
        budget: RetrievalBudget,
        cancel: CancellationToken | None = None,
    ) -> RetrievalResult:
        """Rerank source-backed candidates with the configured semantic provider."""

        if cancel is not None:
            cancel.raise_if_cancelled()
        if self._embedding is None:
            return self.retrieve(document, query, language=language, budget=budget)
        normalized = normalize_query(query)
        snap = document.snapshot
        model_id = self._embedding.model.model_id
        cache_key = (
            snap.profile_id, snap.revision, snap.content_hash, language.casefold()[:2], normalized,
            budget.top_k, budget.max_context_tokens, CHUNKER_VERSION, INDEX_VERSION,
            model_id, self._embedding.model.dimensions,
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
        keys = [self._vector_key(index, chunk, embedding.model) for chunk in candidates]
        # Snapshot references before awaiting HTTP. Another request may evict
        # these LRU entries while this request is producing its missing vectors.
        with self._lock:
            local_vectors = {key: self._chunk_vectors[key] for key in keys if key in self._chunk_vectors}
            for key in local_vectors:
                self._chunk_vectors.move_to_end(key)
        missing = [(chunk, key) for chunk, key in zip(candidates, keys, strict=True) if key not in local_vectors]
        texts = [normalized] + [chunk.evidence_text for chunk, _ in missing]
        vectors = await embedding.provider.embed(texts, cancel=cancel)
        validate_vectors(vectors, len(texts), embedding.model.dimensions)
        if cancel is not None:
            cancel.raise_if_cancelled()
        query_vector = vectors[0]
        for (_, key), vector in zip(missing, vectors[1:], strict=True):
            local_vectors[key] = vector
        with self._lock:
            for key, vector in local_vectors.items():
                self._chunk_vectors[key] = vector
                self._chunk_vectors.move_to_end(key)
            while len(self._chunk_vectors) > self._cache_capacity * 4:
                self._chunk_vectors.popitem(last=False)
        chunk_vectors = [local_vectors[key] for key in keys]
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

