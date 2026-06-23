from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    supabase_url: str
    supabase_publishable_key: str
    supabase_secret_key: str
    database_url: str

    anthropic_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    llm_model: str = "claude-sonnet-4-6"

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    mcp_port: int = 8001

    log_level: str = "INFO"


settings = Settings()  # type: ignore[call-arg]
