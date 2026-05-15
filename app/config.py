from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_system_user_token: str = ""
    meta_api_version: str = "v25.0"

    database_url: str = "sqlite:///./data/data.db"

    auth_username: str = "admin"
    auth_password: str = "mude-isso-em-producao"

    secret_key: str = "mude-isso-em-producao"
    env: str = "development"

    # LLM provider (OpenAI-compatible chat completions API).
    # Defaults to Groq + Llama 3.3 70B (free tier).
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""
    llm_model: str = "llama-3.3-70b-versatile"

    # Notion integration for campaign briefs sync
    notion_api_key: str = ""
    notion_database_id: str = ""
    notion_poll_minutes: int = 5

    @property
    def is_dev(self) -> bool:
        return self.env == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
