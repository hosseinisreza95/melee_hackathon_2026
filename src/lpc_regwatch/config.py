"""Central configuration, read from environment (.env) only.

Why: the challenge requires no personal API key in the repo and an AI provider that is
replaceable by configuration. Every external dependency is declared here and nowhere else.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=False)

DISCLAIMER = (
    "This tool is not an official regulatory source. Regulatory Affairs validation is "
    "required before any official, commercial or operational use. No result must not be "
    "interpreted as no registration."
)


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{(ROOT / 'data' / 'lpc_regwatch.sqlite').as_posix()}")
    raw_dir: Path = Path(os.getenv("RAW_DIR", ROOT / "data" / "raw"))
    # AI provider: any OpenAI-compatible endpoint (OpenAI, Gemini OpenAI-compat, Azure OpenAI, local)
    ai_provider: str = os.getenv("AI_PROVIDER", "openai")
    ai_model: str = os.getenv("AI_MODEL", "gpt-5-mini")
    # Accepted key names: AI_API_KEY (documented), OPENAI_API_KEY, OPEN_AI (team convention). Never logged.
    ai_api_key: str = os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_AI") or ""
    ai_base_url: str | None = os.getenv("AI_BASE_URL") or None
    ai_reasoning_effort: str = os.getenv("AI_REASONING_EFFORT", "low")  # gpt-5 family: minimal | low | medium | high (answer latency vs depth)
    http_user_agent: str = os.getenv("HTTP_USER_AGENT", "lpc-regwatch/0.1 (regulatory watch)")
    # FR E-Phy scope: 'lallemand' = pilots + Lallemand/Danstar holders + pilot species; 'all' = every AUTORISE product
    # in France (the whole current French registry) plus the Lallemand-related ones of any status
    fr_ephy_scope: str = os.getenv("FR_EPHY_SCOPE", "lallemand")
    pipeline_schedule: str = os.getenv("PIPELINE_SCHEDULE", "30 3 * * *")  # cron of the nightly pipeline (UTC), advertised by /health
    api_base_url: str = os.getenv("API_BASE_URL", "http://localhost:8000")  # used by the Streamlit thin client
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")  # advertised in OpenAPI servers[]

    @property
    def ai_enabled(self) -> bool:
        return bool(self.ai_api_key)


settings = Settings()
