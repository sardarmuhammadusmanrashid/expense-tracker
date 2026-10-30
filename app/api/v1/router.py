
from fastapi import APIRouter

from app.api.v1.routes import auth, categories, expenses,reports,notifications,csv_imports


api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(categories.router)
api_router.include_router(expenses.router)
api_router.include_router(reports.router)
api_router.include_router(notifications.router)
api_router.include_router(csv_imports.router)