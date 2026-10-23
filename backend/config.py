"""Application configuration and environment settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "AI-Assisted Bug Triage & Defect Management System"
    VERSION: str = "1.0.0-dev"
    API_V1_PREFIX: str = "/api/v1"
    ENVIRONMENT: str = "development"
    
    # Database
    DATABASE_URL: str = "sqlite:///./data/defect_triage.db"
    
    # Security & Auth
    SECRET_KEY: str = "cisc594-insecure-dev-secret-key-change-in-production-123456789"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
