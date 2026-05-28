from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    db_user: str
    db_password: str
    db_host: str
    db_port: int = 5432
    db_name: str
    db_max_connections: int = 5

    # Gemini Config
    gemini_api_key: str = ""
    gemini_llm_model: str = "gemini-2.5-flash"
    gemini_embedding_model: str = "gemini-embedding-001"

    gemini_llm_rpm_limit: int = 5
    gemini_embedding_rpm_limit: int = 100
    gemini_max_embeddings_per_run: int = 900

    model_config = SettingsConfigDict(env_file='.env', extra='ignore')




settings = Settings()
