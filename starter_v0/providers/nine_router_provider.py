from __future__ import annotations

import os

from providers.openai_provider import OpenAIProvider


class NineRouterProvider(OpenAIProvider):
    """9router's local OpenAI-compatible Chat Completions endpoint."""

    def __init__(self) -> None:
        super().__init__(
            api_key_env="NINE_ROUTER_API_KEY",
            base_url=os.getenv("NINE_ROUTER_BASE_URL", "http://127.0.0.1:20128/v1"),
            default_model=os.getenv("NINE_ROUTER_MODEL", "kr/claude-sonnet-4.5"),
        )
