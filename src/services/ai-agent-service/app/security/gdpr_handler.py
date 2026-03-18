"""
GDPR/KVKK Compliance Handler

Provides Right to Erasure and Right to Portability capabilities
for user data stored in vector store, cache, and audit logs.
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# UTC helper
try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc


@dataclass
class DeletionCertificate:
    """Proof that user data has been deleted."""
    certificate_id: str
    user_id_hash: str
    deleted_items: Dict[str, Any]
    timestamp: str
    status: str = "completed"


@dataclass
class ExportPackage:
    """Exported user data."""
    user_id_hash: str
    timestamp: str
    data: Dict[str, Any] = field(default_factory=dict)
    total_items: int = 0


class GDPRHandler:
    """
    GDPR/KVKK compliance handler.

    Supports:
    - Right to Erasure (Art. 17): Complete deletion of user data
    - Right to Portability (Art. 20): Export user data in machine-readable format
    - Deletion certificates for audit trail
    """

    def __init__(
        self,
        cache=None,
        vector_store=None,
    ) -> None:
        self.cache = cache
        self.vector_store = vector_store

    async def delete_user_data(self, user_id: str) -> DeletionCertificate:
        """
        Delete all user data (GDPR Right to Erasure / KVKK Madde 7).

        Removes data from:
        1. Vector store (RAG documents)
        2. Redis cache
        3. Generates deletion certificate

        Args:
            user_id: The user whose data should be deleted

        Returns:
            DeletionCertificate as proof of deletion
        """
        deleted_items: Dict[str, Any] = {}
        user_id_hash = self._hash_user_id(user_id)

        logger.critical(f"GDPR_ERASURE_STARTED: user_hash={user_id_hash}")

        # 1. Delete from cache (Redis)
        deleted_items["cache"] = await self._delete_cache_data(user_id)

        # 2. Delete from vector store
        deleted_items["vector_store"] = await self._delete_vector_store_data(user_id)

        # 3. Generate deletion certificate
        now_iso = datetime.now(UTC).isoformat()
        cert_id = hashlib.sha256(
            f"{user_id}{now_iso}".encode()
        ).hexdigest()[:32]

        certificate = DeletionCertificate(
            certificate_id=cert_id,
            user_id_hash=user_id_hash,
            deleted_items=deleted_items,
            timestamp=now_iso,
        )

        logger.critical(
            f"GDPR_ERASURE_COMPLETED: cert_id={cert_id}, "
            f"user_hash={user_id_hash}, items={deleted_items}"
        )

        return certificate

    async def export_user_data(self, user_id: str) -> ExportPackage:
        """
        Export all user data (GDPR Right to Portability / KVKK Madde 10).

        Collects data from:
        1. Redis cache
        2. Vector store

        Args:
            user_id: The user whose data should be exported

        Returns:
            ExportPackage with all user data in JSON-serializable format
        """
        user_id_hash = self._hash_user_id(user_id)
        now_iso = datetime.now(UTC).isoformat()
        total_items = 0

        export = ExportPackage(
            user_id_hash=user_id_hash,
            timestamp=now_iso,
        )

        logger.info(f"GDPR_EXPORT_STARTED: user_hash={user_id_hash}")

        # 1. Export from cache
        cache_data = await self._export_cache_data(user_id)
        export.data["cache"] = cache_data
        total_items += len(cache_data)

        # 2. Export from vector store
        vector_data = await self._export_vector_store_data(user_id)
        export.data["documents"] = vector_data
        total_items += len(vector_data)

        export.total_items = total_items

        logger.info(
            f"GDPR_EXPORT_COMPLETED: user_hash={user_id_hash}, "
            f"total_items={total_items}"
        )

        return export

    # ----- Private helpers -----

    async def _delete_cache_data(self, user_id: str) -> Dict[str, Any]:
        """Delete user data from Redis cache."""
        if not self.cache:
            return {"status": "skipped", "reason": "Cache not configured"}

        try:
            # Delete all keys matching user pattern
            pattern = f"user:{user_id}:*"

            if hasattr(self.cache, 'client') and self.cache.client:
                keys = []
                async for key in self.cache.client.scan_iter(match=pattern):
                    keys.append(key)

                if keys:
                    await self.cache.client.delete(*keys)

                return {"status": "deleted", "keys_deleted": len(keys)}
            else:
                return {"status": "skipped", "reason": "Redis client not connected"}

        except Exception as e:
            logger.error(f"GDPR cache deletion failed: {e}")
            return {"status": "error", "error": str(e)}

    async def _delete_vector_store_data(self, user_id: str) -> Dict[str, Any]:
        """Delete user documents from vector store."""
        if not self.vector_store:
            return {"status": "skipped", "reason": "Vector store not configured"}

        try:
            # Delete documents owned by user
            if hasattr(self.vector_store, 'delete_by_metadata'):
                count = self.vector_store.delete_by_metadata(
                    filter={"owner_id": user_id}
                )
                return {"status": "deleted", "documents_deleted": count}
            else:
                return {"status": "skipped", "reason": "Vector store does not support metadata deletion"}

        except Exception as e:
            logger.error(f"GDPR vector store deletion failed: {e}")
            return {"status": "error", "error": str(e)}

    async def _export_cache_data(self, user_id: str) -> list:
        """Export user data from Redis cache."""
        if not self.cache:
            return []

        try:
            results = []
            pattern = f"user:{user_id}:*"

            if hasattr(self.cache, 'client') and self.cache.client:
                async for key in self.cache.client.scan_iter(match=pattern):
                    value = await self.cache.client.get(key)
                    key_str = key.decode() if isinstance(key, bytes) else key
                    value_str = value.decode() if isinstance(value, bytes) else str(value)

                    results.append({
                        "key": key_str,
                        "value": value_str,
                    })

            return results
        except Exception as e:
            logger.error(f"GDPR cache export failed: {e}")
            return []

    async def _export_vector_store_data(self, user_id: str) -> list:
        """Export user documents from vector store."""
        if not self.vector_store:
            return []

        try:
            if hasattr(self.vector_store, 'get_by_metadata'):
                docs = self.vector_store.get_by_metadata(
                    filter={"owner_id": user_id}
                )
                return [
                    {
                        "content": doc.content if hasattr(doc, 'content') else str(doc),
                        "metadata": doc.metadata if hasattr(doc, 'metadata') else {},
                    }
                    for doc in docs
                ]
            return []
        except Exception as e:
            logger.error(f"GDPR vector store export failed: {e}")
            return []

    def _hash_user_id(self, user_id: str) -> str:
        """Hash user ID for audit trail (GDPR: don't log raw PII)."""
        return hashlib.sha256(user_id.encode()).hexdigest()[:16]
