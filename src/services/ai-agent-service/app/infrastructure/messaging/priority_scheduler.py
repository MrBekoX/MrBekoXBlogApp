"""Priority-based scheduling for multi-queue consumption.

Uses a dual-semaphore design:
- global_semaphore: limits total concurrent Ollama requests
- chat_semaphore: reserves dedicated slots for chat
- low_semaphore: shared slot for authoring + background
"""

import asyncio
import logging
from enum import Enum

logger = logging.getLogger(__name__)


class QueuePriority(str, Enum):
    CHAT = "chat"
    AUTHORING = "authoring"
    BACKGROUND = "background"


class PriorityScheduler:
    """Weighted fair scheduler for multi-queue RabbitMQ consumption.

    Slot allocation:
    - Chat messages try chat_semaphore first, then low_semaphore (always prioritized)
    - Authoring/background messages only use low_semaphore
    - global_semaphore caps total in-flight work
    """

    SLOT_CHAT = "chat"
    SLOT_LOW = "low"

    def __init__(
        self,
        total_slots: int = 3,
        chat_slots: int = 2,
        low_priority_slots: int = 1,
    ):
        self._global_semaphore = asyncio.Semaphore(total_slots)
        self._chat_semaphore = asyncio.Semaphore(chat_slots)
        self._low_semaphore = asyncio.Semaphore(low_priority_slots)
        self._total_slots = total_slots
        self._chat_slots = chat_slots
        self._low_slots = low_priority_slots

    async def acquire(self, priority: QueuePriority) -> str:
        """Acquire a processing slot. Blocks until available.

        Chat can overflow into low_semaphore when chat_semaphore is full.
        Returns slot type string (SLOT_CHAT or SLOT_LOW) for correct release.
        """
        await self._global_semaphore.acquire()

        if priority == QueuePriority.CHAT:
            # Try chat slot first — locked() returns True when value==0
            # No TOCTOU risk: single-threaded asyncio, no await between check and acquire
            if not self._chat_semaphore.locked():
                await self._chat_semaphore.acquire()
                return self.SLOT_CHAT
            # Overflow: use low slot (blocking)
            await self._low_semaphore.acquire()
            return self.SLOT_LOW

        # Authoring and background use low slot only
        await self._low_semaphore.acquire()
        return self.SLOT_LOW

    def release(self, slot_type: str) -> None:
        """Release the processing slot using the token returned by acquire()."""
        if slot_type == self.SLOT_CHAT:
            self._chat_semaphore.release()
        else:
            self._low_semaphore.release()

        self._global_semaphore.release()

    @property
    def available_slots(self) -> int:
        return self._global_semaphore._value

    @property
    def stats(self) -> dict:
        return {
            "total_slots": self._total_slots,
            "available_global": self._global_semaphore._value,
            "available_chat": self._chat_semaphore._value,
            "available_low": self._low_semaphore._value,
        }
