"""
Cost guard (tiêu chí 8) — theo dõi chi phí LLM trong Redis.
"""
from datetime import date
import logging

from fastapi import HTTPException
from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import r

logger = logging.getLogger(__name__)

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006


def _cost_keys() -> tuple[str, str]:
    today = date.today()
    return (
        f"cost:daily:{today.isoformat()}",
        f"cost:monthly:{today.strftime('%Y-%m')}",
    )


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    if r is None:
        return

    daily_key, monthly_key = _cost_keys()
    try:
        daily_val, monthly_val = r.mget(daily_key, monthly_key)
        daily_cost = float(daily_val) if daily_val is not None else 0.0
        monthly_cost = float(monthly_val) if monthly_val is not None else 0.0

        if daily_cost >= settings.daily_budget_usd or monthly_cost >= settings.monthly_budget_usd:
            raise HTTPException(status_code=402, detail="Budget exceeded")
    except HTTPException:
        raise
    except RedisError as exc:
        logger.warning("Redis unavailable in cost_guard.check_budget: %s", exc)


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = (input_tokens / 1000.0) * PRICE_INPUT_PER_1K + (
        output_tokens / 1000.0
    ) * PRICE_OUTPUT_PER_1K

    if r is None:
        return cost

    daily_key, monthly_key = _cost_keys()
    try:
        pipe = r.pipeline()
        pipe.incrbyfloat(daily_key, cost)
        pipe.expire(daily_key, 86400 * 2)
        pipe.incrbyfloat(monthly_key, cost)
        pipe.expire(monthly_key, 86400 * 35)
        pipe.execute()
    except RedisError as exc:
        logger.warning("Redis unavailable in cost_guard.record_cost: %s", exc)

    return cost
