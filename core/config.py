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

    # NCU Portal OAuth
    ncu_oauth_client_id: str = ""
    ncu_oauth_client_secret: str = ""
    ncu_oauth_redirect_uri: str = "http://localhost:8000/auth/callback"

    # JWT Security
    jwt_secret_key: str = "temporary_secret_key_change_me_in_production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    model_config = SettingsConfigDict(env_file='.env', extra='ignore')




settings = Settings()
