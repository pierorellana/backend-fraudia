from fastapi import APIRouter

from app.api.routes import agent
from app.api.routes import analytics
from app.api.routes import catalogs
from app.api.routes import claims
from app.api.routes import health
from app.api.routes import imports
from app.api.routes import risk
from app.api.routes import rules

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(claims.router, prefix="/claims", tags=["claims"])
api_router.include_router(risk.router, prefix="/risk", tags=["risk"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
api_router.include_router(imports.router, prefix="/imports", tags=["imports"])
api_router.include_router(agent.router, prefix="/agent", tags=["agent"])
api_router.include_router(rules.router, prefix="/rules", tags=["rules"])
api_router.include_router(catalogs.router, prefix="/catalogs", tags=["catalogs"])
