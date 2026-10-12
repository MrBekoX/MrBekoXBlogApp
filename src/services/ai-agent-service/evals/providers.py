"""Değerlendirme koşucusunun sağlayıcı double'ları — TAMAMI test sağlayıcısı.

Ortamda GERÇEK LLM/embedding/web-arama sağlayıcısı YOKTUR. Bu modüldeki her
sınıf ``is_test_double = True`` taşır; koşucu bunlarla koştuğu her sonucu
``provider="test_executor"`` ile işaretler (A10: "Gerçek sağlayıcıyla
çalıştırılmayan sonuçları açıkça işaretle").

- ``GroundedTestModel``: prompt'un CONTEXT bloğundan ÇIKARIMLA (extractive)
  cevap kurar — uydurma iddia eklemez. Böylece iddia–kanıt desteği ölçümü,
  "dürüst bir üretici model" varsayımı altında boru hattının atıf denetimini
  ölçer; gerçek bir modelin sadakati BU KOŞUDAN ÖLÇÜLEMEZ.
- ``ScriptedRouterModel``: yalnız belirsiz router yolunu denemek için hazırlanmış
  JSON öneri döndürür; öneri içeriği küme etiketlerinden DEĞİL senaryo
  tanımından gelir.
- ``ScriptedSearchProvider``: araştırma sorgularını yerel sayfa URL'lerine
  eşler (arama sağlayıcısı double'ı); sayfalar yerel sunucudan GERÇEK HTTP
  ile okunur.
- ``LocalPageServer``: 127.0.0.1 üzerinde ``evals.articles.LOCAL_PAGES``
  gövdelerini sunan gerçek HTTP sunucusu (test altyapısı).
- ``EvalEmbeddingProvider``: hash-kova deterministik gömme (anlamsal model
  DEĞİLDİR; tests/qa helpers'daki desenin bağımsız kopyası).
- ``RecordingProgressSink`` / ``StubCancellationToken`` / ``PreCancelledToken``:
  port test double'ları (tests/test_doubles deseninin bağımsız kopyası).
"""

from __future__ import annotations

import re
import threading
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from agent_core.content.retrieval import tokenize
from agent_core.models import DomainProgress
from agent_core.ports import CancellationToken, WebSearchResult

__all__ = [
    "EvalEmbeddingProvider",
    "GroundedTestModel",
    "LocalPageServer",
    "PreCancelledToken",
    "RecordingProgressSink",
    "ScriptedRouterModel",
    "ScriptedSearchProvider",
    "SlowTestModel",
    "StubCancellationToken",
]

TEST_PROVIDER_ID = "test_executor"


# --- Gömme -------------------------------------------------------------------


class EvalEmbeddingProvider:
    """Hash-kova deterministik gömme; GERÇEK anlamsal model DEĞİLDİR."""

    is_test_double = True

    def __init__(self, dimensions: int = 64) -> None:
        self.dimensions = dimensions
        self.embedded_texts: list[str] = []
        self.call_count = 0

    async def embed(self, texts: Any, *, cancel: CancellationToken | None = None) -> list[list[float]]:
        import hashlib
        import math

        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dimensions
            for token in tokenize(text):
                digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
                vector[int.from_bytes(digest, "big") % self.dimensions] += 1.0
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            vectors.append([value / norm for value in vector])
        self.embedded_texts.extend(texts)
        self.call_count += 1
        return vectors


# --- Model (tek üretim çağrısı yolları: qa / analysis / research) -------------

_PROMPT_SECTION_SPLIT = "\n\n---\n\n"
_CONTEXT_LINE_RE = re.compile(r"^\[(?P<sid>[^\]]+)\](?:\s+\((?P<head>[^)]*)\))?\s*$")
_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+|\n+")


def _sentences(text: str) -> list[str]:
    return [piece.strip() for piece in _SENTENCE_RE.split(text) if len(piece.strip()) >= 12]


def _overlap_score(question_tokens: set[str], text: str) -> int:
    return len(question_tokens & set(tokenize(text)))


class GroundedTestModel:
    """CONTEXT'ten çıkarımla cevap kuran test sağlayıcısı (uydurma yok).

    Davranış: prompt'taki ``CONTEXT:`` bloğunun ``[kaynak]`` satırlarını
    ayrıştırır; soru belirteçleriyle en çok örtüşen cümleleri seçip birleştirir
    ve KULLANICININ DİLİ etiketiyle döner. CONTEXT boşsa yetersizlik cümlesi
    üretir (uydurma yapmaz). Seçili metin/başlıklar blokları soru belirteçlerine
    eklenir. Bütün çağrılar ``requests``'e yazılır.
    """

    is_test_double = True
    model_name = "grounded-test-model"

    def __init__(self, *, max_sentences: int = 5) -> None:
        self.max_sentences = max_sentences
        self.requests: list[Any] = []
        self.call_count = 0

    async def complete(self, request: Any, *, cancel: CancellationToken | None = None) -> Any:
        from agent_core.ports import ModelResponse, ModelUsage

        if cancel is not None:
            cancel.raise_if_cancelled()
        self.requests.append(request)
        self.call_count += 1

        prompt = request.prompt
        language = "tr"
        match = re.search(r"\((tr|en)(?:-[A-Za-z0-9]+)?\)", prompt)
        if match is not None:
            language = match.group(1)

        # Soru + başlık + seçili metin belirteçleri: CONTEXT dışındaki bloklar
        # seçim sinyalidir; yalnız CONTEXT cümleleri cevaba taşınır.
        context_text = ""
        selector_text = ""
        for section in prompt.split(_PROMPT_SECTION_SPLIT):
            if section.startswith("CONTEXT:"):
                context_text = section[len("CONTEXT:"):]
            else:
                selector_text += "\n" + section
        question_tokens = set(tokenize(selector_text))
        # İçerik satırlarını kaynak kimlikleriyle eşleştir.
        chunks: list[tuple[str, str, str]] = []  # (source_id, heading, body)
        current_sid = ""
        current_head = ""
        current_lines: list[str] = []
        for line in (context_text or "").splitlines():
            line = line.strip()
            header = _CONTEXT_LINE_RE.match(line)
            if header is not None:
                if current_lines:
                    chunks.append((current_sid, current_head, " ".join(current_lines)))
                    current_lines = []
                current_sid = header.group("sid") or ""
                current_head = header.group("head") or ""
                continue
            if line:
                current_lines.append(line)
        if current_lines:
            chunks.append((current_sid, current_head, " ".join(current_lines)))

        scored: list[tuple[int, str, str, str]] = []
        for sid, head, body in chunks:
            for sentence in _sentences(body):
                score = _overlap_score(question_tokens, f"{head} {sentence}")
                if score > 0:
                    scored.append((score, head, sentence, sid))
        scored.sort(key=lambda item: (-item[0], item[3], item[2]))
        picked = scored[: self.max_sentences]

        if not picked:
            note = (
                "Bu konuda elimde yeterli bilgi yok."
                if language == "tr"
                else "I do not have enough information on this."
            )
            return ModelResponse(
                text=note,
                model_name=self.model_name,
                usage=ModelUsage(prompt_tokens=48, completion_tokens=8),
                finished_at=datetime.now(timezone.utc),
            )

        parts: list[str] = []
        for _score, head, sentence, _sid in picked:
            prefix = f"{head}: " if head and language == "tr" else (f"{head} — " if head else "")
            parts.append(f"{prefix}{sentence}")
        answer = " ".join(parts)
        return ModelResponse(
            text=answer,
            model_name=self.model_name,
            usage=ModelUsage(prompt_tokens=96, completion_tokens=32),
            finished_at=datetime.now(timezone.utc),
        )


class SlowTestModel:
    """Model çağrısını yapay gecikmeyle yavaşlatan double (deadline ölçümü).

    ``resume(deadline_seconds=...)`` davranışının ölçülebilmesi için model
    çağrısı süre sınırından uzun sürmelidir; gerçek gecikme benzetimidir ve
    raporda gecikme metriklerine DAHİL EDİLMEZ.
    """

    is_test_double = True

    def __init__(self, inner: Any, delay_seconds: float) -> None:
        import asyncio

        self._inner = inner
        self._delay = delay_seconds
        self._asyncio = asyncio
        self.call_count = 0

    async def complete(self, request: Any, *, cancel: CancellationToken | None = None) -> Any:
        if cancel is not None:
            cancel.raise_if_cancelled()
        self.call_count += 1
        await self._asyncio.sleep(self._delay)
        return await self._inner.complete(request, cancel=cancel)


class ScriptedRouterModel:
    """Belirsiz router yolunun merge/doğrulama davranışını deneyen double.

    ``suggestions``: soru alt-dizgisi → router JSON önerisi metni. Eşleşen
    anahtar yoksa hızlı makale-cevabı varsayılan önerisi döner. İçerik küme
    etiketinden türetilmez; senaryo tanımında verilir.
    """

    is_test_double = True

    def __init__(self, suggestions: dict[str, str] | None = None) -> None:
        self.suggestions = dict(suggestions or {})
        self.call_count = 0

    async def complete(self, request: Any, *, cancel: CancellationToken | None = None) -> Any:
        from agent_core.ports import ModelResponse, ModelUsage

        if cancel is not None:
            cancel.raise_if_cancelled()
        self.call_count += 1
        payload = None
        for key, suggestion in self.suggestions.items():
            if key in request.prompt:
                payload = suggestion
                break
        if payload is None:
            payload = (
                '{"intent": "article_qa", "selected_mode": "fast", "needs_web": false, '
                '"needs_clarification": false, "clarification_question": null, '
                '"brief_reason": "kısa ve tekil soru"}'
            )
        return ModelResponse(
            text=payload,
            model_name="scripted-router",
            usage=ModelUsage(prompt_tokens=24, completion_tokens=12),
            finished_at=datetime.now(timezone.utc),
        )


# --- Web arama sağlayıcısı double'ı ------------------------------------------


class ScriptedSearchProvider:
    """Sorguyu yerel sayfa URL'lerine eşleyen arama double'ı.

    Eşleme ``articles.SEARCH_INDEX`` anahtar sözcüklerindedir; eşleşme yoksa
    boş sonuç döner (arama sağlayıcısı boş sonuç döndüğünde akışın kısmi
    yolu ölçülür).
    """

    is_test_double = True

    def __init__(self, base_url: str, index: dict[str, list[str]]) -> None:
        self.base_url = base_url.rstrip("/")
        self.index = index
        self.queries: list[str] = []
        self.call_count = 0

    async def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        cancel: CancellationToken | None = None,
    ) -> list[WebSearchResult]:
        if cancel is not None:
            cancel.raise_if_cancelled()
        self.queries.append(query)
        self.call_count += 1
        folded = query.casefold()
        urls: list[str] = []
        for keyword, paths in self.index.items():
            if keyword in folded:
                urls.extend(self.base_url + path for path in paths)
        seen: set[str] = set()
        results: list[WebSearchResult] = []
        for url in urls:
            if url in seen or len(results) >= max_results:
                continue
            seen.add(url)
            results.append(
                WebSearchResult(
                    title=url.rsplit("/", 1)[-1],
                    url=url,
                    snippet=None,
                    retrieved_at=datetime.now(timezone.utc),
                )
            )
        return results


class _PageHandler(BaseHTTPRequestHandler):
    """Yerel sayfa sunucusu: yalnız GET; gövdeler articles.LOCAL_PAGES."""

    pages: dict[str, str] = {}

    def do_GET(self) -> None:  # noqa: N802 - http.server API'si
        body = self.pages.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        payload = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:  # sessiz sunucu
        return


class LocalPageServer:
    """127.0.0.1 üzerinde rastgele portta GERÇEK HTTP sunan test sunucusu.

    Araştırma akışı A6 araçları üzerinden bu sunucuya GERÇEK HTTP isteği
    atar (SSRF koruması, boyut/içerik türü sınırları devrededir); yalnız
    arama sağlayıcısı double'dır. ``environment="test"`` + ``allow_loopback``
    gerektirir (web izin modeli, D013/A6).
    """

    is_test_double = True

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = dict(pages)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("LocalPageServer başlatılmadı; 'with' bloğu kullanın")
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError("LocalPageServer başlatılmadı; 'with' bloğu kullanın")
        return int(self._server.server_address[1])

    def __enter__(self) -> "LocalPageServer":
        handler = type("BoundPageHandler", (_PageHandler,), {"pages": self.pages})
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None


# --- Port double'ları: iptal + ilerleme ---------------------------------------


class StubCancellationToken:
    """İptal edilmemiş token double'ı."""

    is_test_double = True

    @property
    def is_cancelled(self) -> bool:
        return False

    @property
    def reason(self) -> str | None:
        return None

    def raise_if_cancelled(self) -> None:
        return None


class PreCancelledToken:
    """İlk kontrolde iptal sinyali üreten token double'ı (iptal davranışı ölçümü)."""

    is_test_double = True

    def __init__(self, reason: str = "eval iptali") -> None:
        self._reason = reason

    @property
    def is_cancelled(self) -> bool:
        return True

    @property
    def reason(self) -> str | None:
        return self._reason

    def raise_if_cancelled(self) -> None:
        from agent_core.errors import AgentErrorCode, PortError

        raise PortError(AgentErrorCode.CANCELLED, self._reason, port="eval-cancel-token")


class RecordingProgressSink:
    """Yayınlanan DomainProgress olaylarını kaydeden sink double'ı."""

    is_test_double = True

    def __init__(self) -> None:
        self.events: list[DomainProgress] = []

    async def publish(self, progress: DomainProgress) -> None:
        self.events.append(progress)

    def text(self) -> str:
        return "\n".join(event.message for event in self.events)
