"""API key authentication; an unset server key denies access."""
import secrets

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from app.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str | None = Security(api_key_header)) -> str:
    if not settings.agent_api_key or not api_key or not secrets.compare_digest(
        api_key.encode("utf-8"), settings.agent_api_key.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")
    return api_key