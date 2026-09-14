from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

class Settings(BaseSettings):
    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str
    SUPABASE_DB_URL: str
    REDIS_URL: str
    MOBILE_HASH_PEPPER: str
    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    CORS_ORIGINS: List[str] = ["*"]
    
    JWT_SECRET: str = ""
    JWT_ALGORITHM: str = "HS256"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
