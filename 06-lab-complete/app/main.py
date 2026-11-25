"""
Production AI Agent — Part 6 Final Project.
"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
import sys
import time

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r as redis_client, redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    """Format mọi dòng log của app thành 1 JSON object hợp lệ."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for attr in ("event", "path", "status", "ms", "environment"):
            val = getattr(record, attr, None)
            if val is not None:
                payload[attr] = val
        return json.dumps(payload, ensure_ascii=False)


def _configure_logging() -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    app_logger = logging.getLogger("app")
    app_logger.setLevel(logging.INFO)
    app_logger.handlers.clear()
    app_logger.addHandler(handler)
    app_logger.propagate = False
    return app_logger


logger = _configure_logging()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info(
        "Agent starting",
        extra={"event": "startup", "environment": settings.environment},
    )
    yield
    logger.info(
        "Agent shutting down gracefully",
        extra={"event": "shutdown", "environment": settings.environment},
    )
    if redis_client is not None:
        try:
            redis_client.close()
        except Exception:
            pass


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled error: %s",
        type(exc).__name__,
        extra={"event": "error", "path": request.url.path, "status": 500},
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = None


@app.get("/health")
def health():
    """Liveness check: luôn trả 200 khi process còn chạy."""
    return {"status": "ok"}


@app.get("/ready")
def ready():
    """Readiness check: 200 khi Redis sẵn sàng, 503 khi mất kết nối Redis."""
    if redis_healthy():
        return {"status": "ready"}
    return JSONResponse(
        status_code=503,
        content={"status": "not ready", "reason": "redis unavailable"},
    )


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    start = time.perf_counter()
    check_rate_limit(api_key)
    check_budget()

    answer = llm_ask(body.question)
    input_tokens = max(1, len(body.question.split()))
    output_tokens = max(1, len(answer.split()))
    cost_usd = record_cost(input_tokens, output_tokens)

    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info(
        "Handled /ask request",
        extra={"event": "request", "path": "/ask", "status": 200, "ms": elapsed_ms},
    )
    return {
        "question": body.question,
        "answer": answer,
        "cost_usd": cost_usd,
    }
