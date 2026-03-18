"""Admin message processor for handling admin operations via RabbitMQ."""

import json
import logging
from typing import Any, Callable, Optional
from datetime import datetime, timezone

import aio_pika
from aio_pika.abc import AbstractIncomingMessage

from app.infrastructure.messaging.rabbitmq_adapter import RabbitMQAdapter

logger = logging.getLogger(__name__)

# Admin routing keys
ADMIN_QUARANTINE_STATS_ROUTING_KEY = "admin.quarantine.stats.requested"
ADMIN_QUEUE_STATS_ROUTING_KEY = "admin.queue.stats.requested"
ADMIN_QUARANTINE_REPLAY_ROUTING_KEY = "admin.quarantine.replay.requested"

# Response routing keys
ADMIN_QUARANTINE_STATS_COMPLETED = "admin.quarantine.stats.completed"
ADMIN_QUEUE_STATS_COMPLETED = "admin.queue.stats.completed"
ADMIN_QUARANTINE_REPLAY_COMPLETED = "admin.quarantine.replay.completed"


class AdminMessageProcessor:
    """Processes admin operations from RabbitMQ queue."""

    def __init__(self, broker: RabbitMQAdapter):
        self.broker = broker

    async def process_message(self, body: bytes) -> tuple[bool, str]:
        """Process admin message and return (success, error)."""
        try:
            message_body = json.loads(body.decode("utf-8"))
            event_type = message_body.get("eventType", "")
            payload = message_body.get("payload", {})
            correlation_id = message_body.get("correlationId", "")

            logger.info(f"Processing admin message: {event_type}")

            if event_type == "admin.quarantine.stats.requested":
                return await self._handle_quarantine_stats(payload, correlation_id)
            elif event_type == "admin.queue.stats.requested":
                return await self._handle_queue_stats(payload, correlation_id)
            elif event_type == "admin.quarantine.replay.requested":
                return await self._handle_quarantine_replay(payload, correlation_id)
            else:
                logger.warning(f"Unknown admin event type: {event_type}")
                return False, f"Unknown event type: {event_type}"

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse admin message: {e}")
            return False, f"Invalid JSON: {e}"
        except Exception as e:
            logger.error(f"Error processing admin message: {e}", exc_info=True)
            return False, str(e)

    async def _handle_quarantine_stats(self, payload: dict, correlation_id: str) -> tuple[bool, str]:
        """Handle quarantine stats request."""
        try:
            stats = await self.broker.get_quarantine_stats()

            response = {
                "eventType": "admin.quarantine.stats.completed",
                "correlationId": correlation_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": stats
            }

            await self._publish_response(ADMIN_QUARANTINE_STATS_COMPLETED, response)
            logger.info(f"Quarantine stats response sent: {stats}")
            return True, ""

        except Exception as e:
            logger.error(f"Failed to get quarantine stats: {e}")
            error_response = {
                "eventType": "admin.quarantine.stats.completed",
                "correlationId": correlation_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": {"error": str(e)}
            }
            await self._publish_response(ADMIN_QUARANTINE_STATS_COMPLETED, error_response)
            return False, str(e)

    async def _handle_queue_stats(self, payload: dict, correlation_id: str) -> tuple[bool, str]:
        """Handle queue stats request."""
        try:
            stats = await self.broker.refresh_queue_stats()

            response = {
                "eventType": "admin.queue.stats.completed",
                "correlationId": correlation_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": stats
            }

            await self._publish_response(ADMIN_QUEUE_STATS_COMPLETED, response)
            logger.info(f"Queue stats response sent: {stats}")
            return True, ""

        except Exception as e:
            logger.error(f"Failed to get queue stats: {e}")
            error_response = {
                "eventType": "admin.queue.stats.completed",
                "correlationId": correlation_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": {"error": str(e)}
            }
            await self._publish_response(ADMIN_QUEUE_STATS_COMPLETED, error_response)
            return False, str(e)

    async def _handle_quarantine_replay(self, payload: dict, correlation_id: str) -> tuple[bool, str]:
        """Handle quarantine replay request."""
        try:
            max_messages = payload.get("maxMessages", 10)
            dry_run = payload.get("dryRun", False)
            taxonomy_prefixes = payload.get("taxonomyPrefixes")
            max_age_seconds = payload.get("maxAgeSeconds")

            result = await self.broker.replay_quarantine_messages(
                max_messages=max_messages,
                dry_run=dry_run,
                taxonomy_prefixes=taxonomy_prefixes,
                max_age_seconds=max_age_seconds
            )

            response = {
                "eventType": "admin.quarantine.replay.completed",
                "correlationId": correlation_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": result
            }

            await self._publish_response(ADMIN_QUARANTINE_REPLAY_COMPLETED, response)
            logger.info(f"Quarantine replay result: {result}")
            return True, ""

        except Exception as e:
            logger.error(f"Failed to replay quarantine messages: {e}")
            error_response = {
                "eventType": "admin.quarantine.replay.completed",
                "correlationId": correlation_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": {"error": str(e)}
            }
            await self._publish_response(ADMIN_QUARANTINE_REPLAY_COMPLETED, error_response)
            return False, str(e)

    async def _publish_response(self, routing_key: str, response: dict) -> None:
        """Publish response to the exchange."""
        try:
            await self.broker.publish_response(
                routing_key=routing_key,
                message=json.dumps(response).encode("utf-8")
            )
        except Exception as e:
            logger.error(f"Failed to publish admin response: {e}")


# Admin routing keys that this processor handles
ADMIN_ROUTING_KEYS = [
    ADMIN_QUARANTINE_STATS_ROUTING_KEY,
    ADMIN_QUEUE_STATS_ROUTING_KEY,
    ADMIN_QUARANTINE_REPLAY_ROUTING_KEY,
]
