"""Runtime settings, read from the environment (and a local .env file)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    # LLM used by the agent; any `init_chat_model` string ("provider:model").
    model: str = Field("anthropic:claude-sonnet-5", alias="MEDAGENT_MODEL")
    temperature: float | None = Field(None, alias="MEDAGENT_TEMPERATURE")

    tinyfish_api_key: str | None = Field(None, alias="TINYFISH_API_KEY")
    ncbi_api_key: str | None = Field(None, alias="NCBI_API_KEY")
    ncbi_email: str | None = Field(None, alias="NCBI_EMAIL")
    openfda_api_key: str | None = Field(None, alias="OPENFDA_API_KEY")

    data_dir: Path = Field(Path("./data"), alias="MEDAGENT_DATA_DIR")
    http_timeout: float = Field(20.0, alias="MEDAGENT_HTTP_TIMEOUT")
    tool: str = "medagent"

    @property
    def has_tinyfish(self) -> bool:
        return bool(self.tinyfish_api_key)


@lru_cache
def get_settings() -> Settings:
    # Export .env into os.environ too: LangChain model classes read their API keys from there.
    load_dotenv(override=False)
    return Settings()
