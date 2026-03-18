from typing import Dict, Optional
import logging
from app.security.kill_switch import kill_switch, KillSwitchState, KillSwitch
from app.security.incident_tracker import (
    incident_tracker,
    IncidentTracker,
    IncidentPhase,
    IncidentSeverity,
)
from app.monitoring.metrics import record_runbook_hook

logger = logging.getLogger(__name__)

class IncidentRunbook:
    """Automated incident response runbook."""

    def __init__(self, kill_switch_instance: KillSwitch, incident_tracker_instance: IncidentTracker):
        self.kill_switch = kill_switch_instance
        self.incident_tracker = incident_tracker_instance

    async def execute_phase_1_detection(
        self,
        incident_id: str,
        indicators: Dict
    ):
        """Phase 1: Detection (0-15 minutes)."""
        logger.critical(f"EXECUTING_PHASE_1_DETECTION: {incident_id}")

        actions = [
            "Enable enhanced logging",
            "Capture system state",
            "Identify affected systems",
            "Notify security team"
        ]

        for action in actions:
            await self.incident_tracker.add_action(incident_id, action)
            # Mock executing specific action logic
            logger.info(f"Runbook executing: {action}")

        # Set Kill Switch to Elevated Logging (Safe First Step)
        await self.kill_switch.set_state(
            KillSwitchState.ELEVATED_LOGGING,
            reason=f"Incident {incident_id} detected"
        )

    async def execute_phase_2_containment(
        self,
        incident_id: str,
        indicators: Dict
    ):
        """Phase 2: Containment (15-60 minutes)."""
        logger.critical(f"EXECUTING_PHASE_2_CONTAINMENT: {incident_id}")
        
        # Assess Severity
        severity = self._assess_severity(indicators)
        
        actions = [
            f"Containment Level: {severity}",
            "Block suspicious IPs/users",
            "Increase rate limits"
        ]
        
        if severity in ["high", "critical"]:
             actions.append("Enable RESTRICTED MODE")

        for action in actions:
            await self.incident_tracker.add_action(incident_id, action)

        if severity in ["high", "critical"]:
            await self.kill_switch.set_state(
                KillSwitchState.RESTRICTED_MODE,
                reason=f"Incident {incident_id} - {severity} severity"
            )

        await self.incident_tracker.update_phase(
            incident_id,
            IncidentPhase.CONTAINMENT,
            note="Containment actions executed"
        )

    async def execute_recovery(self, incident_id: str):
        """Phase 4: Recovery."""
        await self.incident_tracker.add_action(incident_id, "Restoring normal operations")
        
        await self.kill_switch.set_state(
            KillSwitchState.NORMAL,
            reason=f"Incident {incident_id} resolved"
        )
        
        await self.incident_tracker.update_phase(
            incident_id,
            IncidentPhase.RECOVERY,
            note="Systems restored by Runbook"
        )

    def _assess_severity(self, indicators: Dict) -> str:
        """Assess incident severity."""
        score = 0
        if indicators.get("unauthorized_access", 0) > 10: score += 3
        if indicators.get("data_exfiltration", False): score += 3
        if indicators.get("pii_disclosed", False): score += 2
        if indicators.get("service_disruption", False): score += 1

        if score >= 7: return "critical"
        elif score >= 4: return "high"
        elif score >= 2: return "medium"
        return "low"

# Singleton
incident_runbook = IncidentRunbook(kill_switch, incident_tracker)


async def trigger_poison_message_runbook(
    taxonomy: str,
    reason: str,
    message_id: str,
    correlation_id: Optional[str] = None,
    routing_key: Optional[str] = None,
    delivery_attempt: int = 0,
) -> Optional[str]:
    """
    Minimal runbook hook for poison message quarantine events.

    Creates an incident and records key actions for SRE/SecOps triage.
    """
    hook_name = "poison_message_quarantine"
    try:
        severity = IncidentSeverity.MEDIUM
        taxonomy_lower = (taxonomy or "").lower()
        if taxonomy_lower.startswith("poison."):
            severity = IncidentSeverity.HIGH
        if delivery_attempt >= 10:
            severity = IncidentSeverity.CRITICAL

        title = f"Poison message quarantined ({taxonomy})"
        description = (
            f"Message {message_id} was quarantined by broker policy. "
            f"reason={reason}, routing_key={routing_key}, delivery_attempt={delivery_attempt}"
        )
        indicators = {
            "taxonomy": taxonomy,
            "reason": reason,
            "message_id": message_id,
            "correlation_id": correlation_id,
            "routing_key": routing_key,
            "delivery_attempt": delivery_attempt,
        }

        incident = await incident_tracker.create_incident(
            title=title,
            description=description,
            severity=severity,
            indicators=indicators,
        )
        await incident_tracker.add_action(
            incident.id, "Message moved to quarantine queue for manual triage"
        )
        await incident_tracker.add_action(
            incident.id, f"Correlation ID: {correlation_id or 'n/a'}"
        )
        await incident_tracker.update_phase(
            incident.id,
            IncidentPhase.DETECTION,
            note="Automated poison-message runbook hook executed",
        )
        record_runbook_hook(hook_name, "success")
        return incident.id

    except Exception as e:
        logger.error(f"Runbook hook failed for poison message {message_id}: {e}")
        record_runbook_hook(hook_name, "failure")
        return None
