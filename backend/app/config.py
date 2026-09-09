from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "内容工坊 Content Studio"
    debug: bool = False

    database_url: str = (
        "postgresql+asyncpg://content_studio:CHANGE_ME@127.0.0.1:5432/content_studio"
    )
    jwt_secret: str = "CHANGE_ME"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"

    cors_origins: list[str] = ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
