"""
Cash Flow Intelligence MVP
FastAPI Application Entry Point
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.auth.rate_limit import limiter
from app.auth.router import router as auth_router
from app.config import settings
from app.database import close_db
from app.integrations.xero.router import router as xero_router
from app.insights.router import router as insights_router

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# Temporarily enable DEBUG logging for profitability calculator to trace P&L issues
logging.getLogger("app.insights.profitability_calculator").setLevel(logging.DEBUG)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """
    Application lifespan handler.
    Manages startup and shutdown of application resources.
    """
    # Startup
    print(f"🚀 Starting {settings.app_name} v{settings.app_version}")
    print(f"📍 Environment: {settings.environment}")
    print(f"🔧 Debug mode: {settings.debug}")
    print(f"🗄️  Database: Connected")
    
    yield
    
    # Shutdown
    print("🗄️  Closing database connections...")
    await close_db()
    print(f"👋 {settings.app_name} shutdown complete")


def create_application() -> FastAPI:
    """
    Application factory.
    Creates and configures the FastAPI application.
    """
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="A Multi-Tenant SaaS Backend for Cash Flow Intelligence",
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        openapi_url="/openapi.json" if settings.debug else None,
        lifespan=lifespan,
    )
    
    # Configure rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    
    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Register routers
    register_routers(app)
    
    return app


def register_routers(app: FastAPI) -> None:
    """
    Register all API routers.
    Will be expanded as we add more endpoints.
    """
    # Health check endpoint (always available)
    @app.get("/health", tags=["Health"])
    async def health_check():
        """Health check endpoint for monitoring."""
        return {
            "status": "healthy",
            "app": settings.app_name,
            "version": settings.app_version,
            "environment": settings.environment
        }
    
    @app.get("/", tags=["Root"])
    async def root():
        """Root endpoint with API information."""
        return {
            "message": f"Welcome to {settings.app_name} API",
            "version": settings.app_version,
            "docs": "/docs" if settings.debug else "Disabled in production",
        }
    
    # Authentication
    app.include_router(auth_router)
    
    # Integrations
    app.include_router(xero_router)
    
    # Insights
    app.include_router(insights_router)


# Create the application instance
app = create_application()


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )

