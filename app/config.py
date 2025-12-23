"""
Application Configuration
Loads settings from environment variables with validation
"""

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    Uses pydantic-settings for validation and type coercion.
    """
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # ============================================
    # Application Settings
    # ============================================
    app_name: str = "CashFlowIntelligence"
    app_version: str = "1.0.0"
    debug: bool = False
    environment: str = "development"
    secret_key: str = "change-this-in-production"
    
    # ============================================
    # Server Settings
    # ============================================
    host: str = "0.0.0.0"
    port: int = 8000
    
    # ============================================
    # Database
    # ============================================
    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/cashflow_db"
    
    # ============================================
    # JWT Authentication
    # ============================================
    jwt_secret_key: str = "change-this-jwt-secret-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    
    # ============================================
    # Xero API
    # ============================================
    xero_client_id: str = ""
    xero_client_secret: str = ""
    xero_redirect_uri: str = "http://localhost:8000/integrations/xero/callback"
    xero_scopes: str = "openid profile email offline_access accounting.transactions accounting.reports.read accounting.settings.read"
    
    # ============================================
    # OpenAI
    # ============================================
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    
    # ============================================
    # Cache Settings
    # ============================================
    cache_ttl_minutes: int = 15
    
    # ============================================
    # CORS Settings
    # ============================================
    cors_origins: str = "http://localhost:3000,http://localhost:5173"
    
    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS origins string into a list."""
        return [origin.strip() for origin in self.cors_origins.split(",")]
    
    @property
    def xero_scopes_list(self) -> List[str]:
        """Parse Xero scopes string into a list."""
        return [scope.strip() for scope in self.xero_scopes.split()]


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.
    Uses lru_cache to avoid loading .env file on every call.
    """
    return Settings()


# Export a default settings instance for convenience
settings = get_settings()

