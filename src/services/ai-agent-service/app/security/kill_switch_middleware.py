from fastapi import Request, HTTPException
from app.security.kill_switch import kill_switch, KillSwitchState
import logging

logger = logging.getLogger(__name__)

async def kill_switch_middleware(request: Request, call_next):
    """Intercept requests and check KillSwitch permissions."""
    
    # We can try to identify user from headers/state if available
    # For now, we'll extract "client_id" or "user_id" from headers if present 
    # Or rely on downstream dependencies. 
    # But this middleware runs BEFORE dependencies usually.
    # We'll peek at Authorization header or use "anonymous".
    
    user_id = "anonymous"
    auth = request.headers.get("Authorization")
    # Very basic parsing, ideally we decode token, but that is heavy.
    # In restricted mode, we assume stricter checks downstream OR 
    # we explicitly check for known "super-admin" tokens/IPs.
    
    # For simulation, we check x-client-id custom header or just pass "unknown"
    # The kill_switch logic handles "unknown" by blocking in restricted mode.
    if request.headers.get("x-client-id"):
        user_id = request.headers.get("x-client-id")
        
    allowed = await kill_switch.is_allowed(user_id, request.url.path)
    
    if not allowed:
        current_state = await kill_switch.get_state()
        logger.warning(f"Request blocked by Kill Switch ({current_state})")
        
        detail = "Service is currently in maintenance or restricted mode."
        if current_state == KillSwitchState.EMERGENCY_SHUTDOWN:
            detail = "Service Unavailable due to Emergency Security Procedures."
            
        # Return 503 for maintenance/emergency
        from starlette.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={"detail": detail}
        )

    response = await call_next(request)
    return response
