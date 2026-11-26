"""Application configuration supplied through environment variables."""
import math
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    agent_api_key: str = field(default_factory=lambda: os.getenv("AGENT_API_KEY", ""))
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    rate_limit_per_minute: int = field(default_factory=lambda: int(os.getenv("RATE_LIMIT_PER_MINUTE", "10")))
    daily_budget_usd: float = field(default_factory=lambda: float(os.getenv("DAILY_BUDGET_USD", "1")))

    def __post_init__(self):
        if not 1 <= self.port <= 65535:
            raise ValueError("PORT must be between 1 and 65535")
        if self.rate_limit_per_minute < 1:
            raise ValueError("RATE_LIMIT_PER_MINUTE must be positive")
        if not math.isfinite(self.daily_budget_usd) or self.daily_budget_usd < 0:
            raise ValueError("DAILY_BUDGET_USD must be finite and non-negative")


settings = Settings()