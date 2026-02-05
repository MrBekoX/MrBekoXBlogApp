from typing import Dict
import logging
from app.security.kill_switch import kill_switch, KillSwitchState, KillSwitch
from app.security.incident_tracker import incident_tracker, IncidentTracker, IncidentPhase

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
