"""Runtime configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    rutracker_login: str | None = None
    rutracker_password: str | None = None
    rutracker_cookies_path: Path = Field(Path(".cache/cookies.json"))
    rutracker_proxy_url: str | None = None
    rutracker_base_url: str = "https://rutracker.org"

    mcp_auth_token: str | None = None
    cache_path: Path = Field(Path(".cache/rutracker.sqlite"))
    cache_ttl_search_seconds: int = 3600
    cache_ttl_torrent_seconds: int = 86_400


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
