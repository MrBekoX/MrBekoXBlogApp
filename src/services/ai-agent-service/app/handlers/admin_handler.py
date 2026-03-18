"""Admin handler for quarantine and queue management operations."""

import logging
from typing import Any

from app.infrastructure.messaging.rabbitmq_adapter import RabbitMQAdapter

logger = logging.getLogger(__name__)


class AdminHandler:
    """Handler for admin operations (quarantine stats, queue stats, replay)."""

    def __init__(self, broker: RabbitMQAdapter):
        self.broker = broker

    async def get_quarantine_stats(self, request: dict[str, Any]) -> dict[str, Any]:
        """
        Get quarantine queue statistics.

        Args:
            request: Request payload containing operation details

        Returns:
            Quarantine statistics
        """
        try:
            stats = await self.broker.get_quarantine_stats()
            logger.info(f"Retrieved quarantine stats: {stats}")
            return stats
        except Exception as e:
            logger.error(f"Failed to get quarantine stats: {e}")
            return {"error": str(e)}

    async def get_queue_stats(self, request: dict[str, Any]) -> dict[str, Any]:
        """
        Get main queue statistics.

        Args:
            request: Request payload containing operation details

        Returns:
            Queue statistics
        """
        try:
            stats = await self.broker.refresh_queue_stats()
            logger.info(f"Retrieved queue stats: {stats}")
            return stats
        except Exception as e:
            logger.error(f"Failed to get queue stats: {e}")
            return {"error": str(e)}

    async def replay_quarantine(
        self,
        request: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Replay quarantined messages to the main exchange.

        Args:
            request: Request payload with:
                - max_messages: Maximum messages to replay (default 10)
                - dry_run: If True, don't actually replay (default False)
                - taxonomy_prefixes: Filter by taxonomy prefixes
                - max_age_seconds: Filter by message age

        Returns:
            Replay operation result
        """
        max_messages = request.get("maxMessages", 10)
        dry_run = request.get("dryRun", False)
        taxonomy_prefixes = request.get("taxonomyPrefixes")
        max_age_seconds = request.get("maxAgeSeconds")

        try:
            result = await self.broker.replay_quarantine_messages(
                max_messages=max_messages,
                dry_run=dry_run,
                taxonomy_prefixes=taxonomy_prefixes,
                max_age_seconds=max_age_seconds
            )
            logger.info(f"Quarantine replay result: {result}")
            return result
        except Exception as e:
            logger.error(f"Failed to replay quarantine messages: {e}")
            return {"error": str(e)}
