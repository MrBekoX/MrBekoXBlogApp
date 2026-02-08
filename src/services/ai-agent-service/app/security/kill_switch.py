from typing import Optional, Set
from datetime import datetime, timezone
import logging
from enum import Enum

logger = logging.getLogger(__name__)

class KillSwitchState(str, Enum):
    """Kill switch states."""
    NORMAL = "normal"
    ELEVATED_LOGGING = "elevated_logging"
    RESTRICTED_MODE = "restricted_mode"
    MAINTENANCE_MODE = "maintenance_mode"
    EMERGENCY_SHUTDOWN = "emergency_shutdown"

class KillSwitch:
    """Security incident kill switch."""

    def __init__(self, redis_client=None):
        self.redis = redis_client
        self.state_key = "security:kill_switch_state"
        # Local state as fallback
        self._local_state = KillSwitchState.NORMAL
        
    async def get_state(self) -> KillSwitchState:
        """Get current kill switch state."""
        if self.redis:
            try:
                state = await self.redis.get(self.state_key)
                if state:
                    # redis.get might return bytes
                    if isinstance(state, bytes):
                         state = state.decode()
                    return KillSwitchState(state)
            except Exception as e:
                logger.error(f"KillSwitch Redis Error: {e}")
                
        return self._local_state

    async def set_state(self, new_state: KillSwitchState, reason: str = ""):
        """Set kill switch state."""
        old_state = await self.get_state()

        if old_state == new_state:
            return

        logger.critical(
            f"KILL_SWITCH_STATE_CHANGED: {old_state} -> {new_state}. Reason: {reason}"
        )

        if self.redis:
            try:
                # Emergency shutdown must persist until manually cleared (no TTL)
                if new_state == KillSwitchState.EMERGENCY_SHUTDOWN:
                    await self.redis.set(self.state_key, new_state.value)
                elif new_state == KillSwitchState.NORMAL:
                    await self.redis.delete(self.state_key)
                else:
                    await self.redis.set(self.state_key, new_state.value, ex=3600)
            except Exception as e:
                logger.error(f"KillSwitch Redis Set Error: {e}")
        
        self._local_state = new_state

        # Notify
        await self._notify_state_change(new_state, reason)

    async def is_allowed(self, user_id: str, endpoint: str) -> bool:
        """Check if request is allowed based on current state."""
        state = await self.get_state()

        if state == KillSwitchState.NORMAL:
            return True

        elif state == KillSwitchState.ELEVATED_LOGGING:
            # All requests allowed, but with enhanced logging
            return True

        elif state == KillSwitchState.RESTRICTED_MODE:
            # Only known users allowed
            known_users = await self._get_known_users()
            is_allowed = user_id in known_users
            if not is_allowed:
                 logger.warning(f"KillSwitch: Blocked {user_id} in RESTRICTED_MODE")
            return is_allowed

        elif state == KillSwitchState.MAINTENANCE_MODE:
            # Only health checks allowed
            return endpoint.endswith("/health") or endpoint == "/"

        elif state == KillSwitchState.EMERGENCY_SHUTDOWN:
            # No requests allowed
            logger.critical(f"KillSwitch: Blocked {user_id} in EMERGENCY_SHUTDOWN")
            return False

        return True

    async def _get_known_users(self) -> Set[str]:
        """Get list of known/trusted users."""
        if self.redis:
            try:
                users = await self.redis.smembers("security:known_users")
                if users:
                    return {u.decode() if isinstance(u, bytes) else u for u in users}
            except Exception:
                pass
        
        # Fallback hardcoded admins
        return {"admin", "system", "dev-user"}

    async def _notify_state_change(self, state: KillSwitchState, reason: str):
        """Notify about state change."""
        # Send to monitoring
        logger.critical(f"SECURITY_ALERT: Kill switch activated - {state.value}. Reason: {reason}")

# Singleton
kill_switch = KillSwitch()
