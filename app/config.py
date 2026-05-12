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

    @property
    def is_dev(self) -> bool:
        return self.env == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
