
from fastapi import FastAPI, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.api.v1.router import api_router

app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.DEBUG,
)
app.include_router(
    api_router,
    prefix=settings.API_V1_PREFIX,
)

@app.get("/")
async def root():
    return {
        "message": "Expense Tracker API is running"
    }


@app.get("/health")
async def health_check(
    db: AsyncSession = Depends(get_db),
):
    await db.execute(text("SELECT 1"))

    return {
        "status": "healthy",
        "database": "connected",
    }
