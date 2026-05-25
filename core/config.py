from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    db_user: str
    db_password: str
    db_host: str
    db_port: int = 5432
    db_name: str
    db_max_connections: int = 5
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

settings = Settings()
