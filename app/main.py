import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.routers.pastes import router

logger = logging.getLogger("uvicorn.error")
app = FastAPI(title="Pastebin Service", version="0.2.0")
app.include_router(router)


@app.exception_handler(SQLAlchemyError)
def database_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    # Do not log SQL parameters, user text or connection credentials.
    original = getattr(exc, "orig", None)
    logger.error(
        "Database operation failed: type=%s sqlstate=%s",
        type(exc).__name__,
        getattr(original, "sqlstate", None),
    )
    return JSONResponse(
        status_code=503, content={"detail": "Database operation failed"}
    )
