from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AuthorizationContext:
    """Identity context forwarded to backend authorization checks."""

    subject_type: str = "anonymous"
    subject_id: str | None = None
    roles: list[str] = field(default_factory=list)
    fingerprint: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "AuthorizationContext":
        payload = payload or {}
        subject_type = str(payload.get("subjectType") or payload.get("subject_type") or "anonymous").strip().lower()
        subject_id = payload.get("subjectId") or payload.get("subject_id")
        roles_raw = payload.get("roles") or []
        roles = [str(role).strip() for role in roles_raw if str(role).strip()]
        fingerprint = payload.get("fingerprint")
        return cls(
            subject_type=subject_type or "anonymous",
            subject_id=str(subject_id).strip() if subject_id else None,
            roles=roles,
            fingerprint=str(fingerprint).strip() if fingerprint else None,
        )

    @classmethod
    def anonymous(cls, fingerprint: str | None = None) -> "AuthorizationContext":
        return cls(subject_type="anonymous", fingerprint=fingerprint)

    def as_backend_payload(self, post_id: str, action: str) -> dict[str, Any]:
        return {
            "subjectType": self.subject_type,
            "subjectId": self.subject_id,
            "roles": self.roles,
            "postId": post_id,
            "action": action,
        }


@dataclass(slots=True)
class PostAccessDecision:
    allowed: bool
    post_id: str
    author_id: str | None = None
    visibility: str = "not_found"


class BackendAuthorizationClient:
    """Client for backend object-authorization decisions used by AI paths."""

    def __init__(
        self,
        backend_api_url: str | None = None,
        service_key: str | None = None,
        header_name: str | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._backend_api_url = (backend_api_url or settings.backend_api_url).rstrip("/")
        self._service_key = service_key or settings.internal_service_auth_key
        self._header_name = header_name or settings.internal_service_auth_header_name
        self._timeout_seconds = timeout_seconds

    def _build_internal_url(self) -> str:
        parts = urlsplit(self._backend_api_url)
        base = f"{parts.scheme}://{parts.netloc}".rstrip("/")
        return f"{base}/internal/v1/ai/post-access"

    async def authorize_post_access(
        self,
        post_id: str,
        action: str,
        auth_context: AuthorizationContext | None = None,
    ) -> PostAccessDecision:
        if not self._service_key:
            logger.error("Internal service auth key is not configured for backend authorization client")
            raise RuntimeError("backend_authorization_unavailable")

        context = auth_context or AuthorizationContext.anonymous()
        request_payload = context.as_backend_payload(post_id=post_id, action=action)
        url = self._build_internal_url()

        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(
                    url,
                    json=request_payload,
                    headers={self._header_name: self._service_key},
                )
        except httpx.HTTPError as exc:
            logger.error("Backend authorization request failed for post_id=%s: %s", post_id, exc)
            raise RuntimeError("backend_authorization_unavailable") from exc

        if response.status_code == 503:
            logger.error("Backend authorization unavailable for post_id=%s", post_id)
            raise RuntimeError("backend_authorization_unavailable")
        if response.status_code == 401:
            logger.error("Backend authorization rejected service credentials")
            raise RuntimeError("backend_authorization_unavailable")

        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") or {}
        return PostAccessDecision(
            allowed=bool(data.get("allowed", False)),
            post_id=str(data.get("postId") or post_id),
            author_id=str(data.get("authorId")) if data.get("authorId") else None,
            visibility=str(data.get("visibility") or "not_found"),
        )
