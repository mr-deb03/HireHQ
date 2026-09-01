"""AI provider selection.

The provider is chosen once from configuration and reused. If ``AI_PROVIDER=anthropic``
is set without credentials the process refuses to silently fall back to the heuristic
engine in production - a misconfigured deployment must be visible, not quietly degraded.
In development it falls back with a loud warning so local work is never blocked.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.core.exceptions import ProviderNotConfigured
from app.core.logging import get_logger
from app.providers.ai.base import AIProvider
from app.providers.ai.heuristic import HeuristicAIProvider

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def get_ai_provider() -> AIProvider:
    if settings.AI_PROVIDER == "anthropic":
        if not settings.AI_API_KEY:
            if settings.APP_ENV == "production":
                raise ProviderNotConfigured(
                    "Anthropic",
                    hint="AI_PROVIDER=anthropic requires AI_API_KEY to be set.",
                )
            logger.warning(
                "ai_provider_downgraded",
                reason="AI_PROVIDER=anthropic but AI_API_KEY is not set",
                using="heuristic-v1",
            )
            return HeuristicAIProvider()

        from app.providers.ai.anthropic_provider import AnthropicAIProvider

        logger.info("ai_provider_selected", provider="anthropic", model=settings.AI_MODEL)
        return AnthropicAIProvider()

    logger.info("ai_provider_selected", provider="heuristic-v1")
    return HeuristicAIProvider()


def reset_ai_provider() -> None:
    """Drop the cached provider. Used by tests that switch configuration."""
    get_ai_provider.cache_clear()
