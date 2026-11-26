"""Production agent: authentication, Redis guards and operational endpoints."""
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from redis.exceptions import RedisError

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
            **getattr(record, "fields", {}),
        }, ensure_ascii=False)


logger = logging.getLogger("production_agent")
handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger.handlers = [handler]
logger.setLevel(logging.INFO)
logger.propagate = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", extra={"fields": {"environment": settings.environment}})
    yield
    # Uvicorn drains in-flight requests before lifespan shutdown on SIGTERM.
    r.close()
    logger.info("shutdown")


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


@app.middleware("http")
async def observe_requests(request: Request, call_next):
    request_id = uuid.uuid4().hex
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        route = request.scope.get("route")
        logger.info("http_request", extra={"fields": {
            "request_id": request_id, "method": request.method,
            "route": route.path if route else "unmatched", "status": status,
            "ms": round((time.perf_counter() - started) * 1000, 2),
        }})


@app.exception_handler(RedisError)
async def redis_error(request: Request, exc: RedisError):
    logger.warning("redis_unavailable")
    return JSONResponse(status_code=503, content={"detail": "Storage unavailable; please retry"})


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    logger.error("internal_error", extra={"fields": {"type": type(exc).__name__}})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


class AskRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=100)


@app.get("/health")
def health():
    return {"status": "ok", "environment": settings.environment}


@app.get("/ready")
def ready():
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Redis unavailable")
    return {"ready": True}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)
    check_budget()
    answer = llm_ask(body.question)
    # The supplied mock has no tokenizer; estimate one token per four chars.
    input_tokens = max(1, len(body.question) // 4)
    output_tokens = max(1, len(answer) // 4)
    cost = record_cost(input_tokens, output_tokens)
    return {"question": body.question, "answer": answer, "usage": {
        "input_tokens": input_tokens, "output_tokens": output_tokens, "cost_usd": cost,
    }}