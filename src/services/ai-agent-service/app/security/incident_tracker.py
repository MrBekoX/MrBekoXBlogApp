from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import logging

logger = logging.getLogger(__name__)

# Determine UTC import
try:
    from datetime import UTC
except ImportError:
    from datetime import timezone
    UTC = timezone.utc

class IncidentPhase(str, Enum):
    """Incident response phases."""
    DETECTION = "detection"
    CONTAINMENT = "containment"
    ERADICATION = "eradication"
    RECOVERY = "recovery"
    POST_INCIDENT = "post_incident"
    RESOLVED = "resolved"

class IncidentSeverity(str, Enum):
    """Incident severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

@dataclass
class Incident:
    """Security incident."""
    id: str
    title: str
    description: str
    severity: IncidentSeverity
    phase: IncidentPhase
    created_at: str # ISO strings for easier json
    updated_at: str
    indicators: Dict = field(default_factory=dict)
    actions_taken: List[str] = field(default_factory=list)
    status_notes: List[str] = field(default_factory=list)
    resolved: bool = False

class IncidentTracker:
    """Track and manage security incidents."""

    def __init__(self, redis_client=None):
        self.redis = redis_client
        self._local_storage = {} # Fallback

    async def create_incident(
        self,
        title: str,
        description: str,
        severity: IncidentSeverity,
        indicators: dict = None
    ) -> Incident:
        """Create a new incident."""
        now_iso = datetime.now(UTC).isoformat()
        incident_id = hashlib.sha256(
            f"{title}{now_iso}".encode()
        ).hexdigest()[:16]

        incident = Incident(
            id=incident_id,
            title=title,
            description=description,
            severity=severity,
            phase=IncidentPhase.DETECTION,
            created_at=now_iso,
            updated_at=now_iso,
            indicators=indicators or {}
        )

        await self._save_incident(incident)

        logger.critical(
            f"INCIDENT_CREATED: {incident_id} - {title} ({severity.value})"
        )

        return incident

    async def update_phase(
        self,
        incident_id: str,
        new_phase: IncidentPhase,
        note: str = ""
    ):
        """Update incident phase."""
        incident = await self._get_incident(incident_id)
        if not incident:
            return

        incident.phase = new_phase
        incident.updated_at = datetime.now(UTC).isoformat()

        if note:
            incident.status_notes.append(f"{datetime.now(UTC).isoformat()}: {note}")

        await self._save_incident(incident)

        logger.info(f"INCIDENT_PHASE_UPDATED: {incident_id} -> {new_phase.value}")

    async def add_action(self, incident_id: str, action: str):
        """Record action taken."""
        incident = await self._get_incident(incident_id)
        if not incident:
            logger.warning(f"Add action failed: Incident {incident_id} not found")
            return

        incident.actions_taken.append(f"{datetime.now(UTC).isoformat()}: {action}")
        incident.updated_at = datetime.now(UTC).isoformat()

        await self._save_incident(incident)

        logger.info(f"INCIDENT_ACTION: {incident_id} - {action}")

    async def resolve(self, incident_id: str, summary: str = ""):
        """Mark incident as resolved."""
        incident = await self._get_incident(incident_id)
        if not incident:
            return

        incident.phase = IncidentPhase.RESOLVED
        incident.resolved = True
        incident.updated_at = datetime.now(UTC).isoformat()

        if summary:
            incident.status_notes.append(f"RESOLVED: {summary}")

        await self._save_incident(incident)

        logger.critical(f"INCIDENT_RESOLVED: {incident_id} - {summary}")

    async def _get_incident(self, incident_id: str) -> Optional[Incident]:
        """Get incident from storage."""
        if self.redis:
            try:
                data = await self.redis.get(f"incident:{incident_id}")
                if data:
                    return Incident(**json.loads(data))
            except Exception:
                pass
        
        return self._local_storage.get(incident_id)

    async def _save_incident(self, incident: Incident):
        """Save incident to storage."""
        if self.redis:
            try:
                await self.redis.set(
                    f"incident:{incident.id}",
                    json.dumps(incident.__dict__),
                    ex=86400 * 30  # Keep for 30 days
                )
            except Exception as e:
                logger.error(f"Incident Redis Save Error: {e}")
                
        self._local_storage[incident.id] = incident


