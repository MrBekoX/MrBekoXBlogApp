from typing import Optional, Dict, List
from fastapi import Header, HTTPException, Depends
import httpx
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

class OAuth2Introspection:
    """OAuth 2.0 token introspection."""

    def __init__(self, introspection_url: str, client_id: str, client_secret: str):
        self.introspection_url = introspection_url
        self.client_id = client_id
        self.client_secret = client_secret
        # We'll use a single client or create per request? 
        # For simplicity and async safety in deps, we create per request or use a global one if we manage lifecycle.
        # Here we instantiate client in validate_token to avoid lifecycle issues in dependency injection for now,
        # or use a context manager.

    async def validate_token(self, token: str) -> Dict:
        """Validate JWT token via introspection endpoint."""
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.introspection_url,
                    data={
                        "token": token,
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                    },
                    timeout=5.0
                )
                response.raise_for_status()
                claims = response.json()

                if not claims.get("active"):
                    raise HTTPException(401, "Invalid or expired token")

                return claims

            except httpx.HTTPError as e:
                logger.error(f"Token introspection failed: {e}")
                # Fail open or closed? Closed for security.
                raise HTTPException(503, f"Authentication service unavailable: {e}")

# Scopes for AI agent operations
class OAuth2Scopes:
    ANALYZE = "ai:analyze"
    CHAT = "ai:chat"
    SUMMARIZE = "ai:summarize"
    ADMIN = "ai:admin"

class M2MAuthenticator:
    """Machine-to-Machine authentication."""

    def __init__(self, introspection_url: Optional[str], client_id: Optional[str], client_secret: Optional[str]):
        self.enabled = bool(introspection_url and client_id and client_secret)
        if self.enabled:
            self.introspection = OAuth2Introspection(
                introspection_url, client_id, client_secret
            )
        else:
            logger.warning("M2M Authentication is DISABLED (missing configuration)")

    async def authenticate(
        self,
        authorization: str = Header(None),
        required_scopes: Optional[List[str]] = None
    ) -> Dict:
        """Authenticate and validate token with scopes."""
        if not self.enabled:
            if settings.debug:
                logger.warning("OAuth not configured - using limited debug credentials")
                return {
                    "active": True,
                    "sub": "debug-user",
                    "scope": "ai:analyze",  # Minimal scope only
                    "client_id": "debug-client",
                    "iss": "debug",
                    "debug_mode": True,
                }
            raise HTTPException(status_code=503, detail="Authentication service not configured")

        if not authorization:
             raise HTTPException(401, "Missing Authorization header")

        # Extract Bearer token
        if not authorization.startswith("Bearer "):
            raise HTTPException(401, "Invalid Authorization header format. Expected 'Bearer <token>'")

        token = authorization[7:]  # Remove "Bearer " prefix

        # Introspect token
        claims = await self.introspection.validate_token(token)

        # Check scopes
        if required_scopes:
            token_scopes = claims.get("scope", "").split()
            # Basic scope check
            missing = [s for s in required_scopes if s not in token_scopes]

            if missing:
                raise HTTPException(
                    403,
                    f"Insufficient permissions. Missing scopes: {', '.join(missing)}"
                )

        return claims

# Singleton instance
m2m_auth = M2MAuthenticator(
    introspection_url=settings.oauth_introspection_url,
    client_id=settings.oauth_client_id,
    client_secret=settings.oauth_client_secret
)

# Dependency functions
async def require_analyze(claims: Dict = Depends(lambda: None)): # Fallback dummy default for signature
    pass
# We need actual dependency injection logic.
# Depends needs a callable that takes params.

async def get_auth_client(authorization: Optional[str] = Header(None)):
    return await m2m_auth.authenticate(authorization)

async def require_analyze_scope(authorization: Optional[str] = Header(None)):
    return await m2m_auth.authenticate(authorization, required_scopes=[OAuth2Scopes.ANALYZE])

async def require_chat_scope(authorization: Optional[str] = Header(None)):
    return await m2m_auth.authenticate(authorization, required_scopes=[OAuth2Scopes.CHAT])

async def require_admin_scope(authorization: Optional[str] = Header(None)):
    return await m2m_auth.authenticate(authorization, required_scopes=[OAuth2Scopes.ADMIN])
