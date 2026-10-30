import asyncio
from pathlib import Path
from uuid import UUID

from app.celery_app import celery_app


@celery_app.task(
    name="app.workers.csv_import_worker.process_csv_import_task"
)
def process_csv_import_task(
    import_id: str,
    user_id: str,
    file_path: str,
):
    path = Path(file_path)

    try:
        file_bytes = path.read_bytes()

        # Import inside the task to avoid a module import cycle.
        from app.api.v1.routes.csv_imports import process_csv_import

        asyncio.run(
            process_csv_import(
                UUID(import_id),
                UUID(user_id),
                file_bytes,
            )
        )
    finally:
        path.unlink(missing_ok=True)