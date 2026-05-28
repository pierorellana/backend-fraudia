from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.router import api_router
from app.core.config import settings
from app.core.exception_handlers import http_exception_handler
from app.core.exception_handlers import unhandled_exception_handler
from app.core.exception_handlers import validation_exception_handler
from app.db.base import Base
from app.db.schema import ensure_code_columns
from app.db.session import engine
from app.schemas.common import GeneralResponse
from app.schemas.common import success_response
from app import models  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_create_tables:
        Base.metadata.create_all(bind=engine)
    ensure_code_columns(engine)
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="API modular para deteccion explicable de riesgo en siniestros.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_prefix)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)


@app.get("/", response_model=GeneralResponse[dict[str, str]])
def root() -> GeneralResponse[dict[str, str]]:
    return success_response(
        {
            "service": settings.app_name,
            "docs": "/docs",
        }
    )
