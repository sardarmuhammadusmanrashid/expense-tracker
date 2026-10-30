import csv
import hashlib
import io
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.db.session import AsyncSessionLocal, get_db
from app.models.category import Category
from app.models.csv_import import CSVImport
from app.models.expense import Expense
from app.models.user import User

router = APIRouter(prefix="/csv-imports", tags=["CSV Imports"])

REQUIRED_COLUMNS = {
    "category_id",
    "amount",
    "currency",
    "spent_on",
}

BATCH_SIZE = 500
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


def parse_csv_row(row: dict, valid_category_ids: set[UUID]) -> dict:
    """Validate one CSV row and return Expense insert values."""

    try:
        category_id = UUID((row.get("category_id") or "").strip())
    except (ValueError, AttributeError):
        raise ValueError("category_id must be a valid UUID.")

    if category_id not in valid_category_ids:
        raise ValueError("Category does not belong to this user.")

    try:
        amount = Decimal((row.get("amount") or "").strip())
    except (InvalidOperation, AttributeError):
        raise ValueError("amount must be a valid decimal number.")

    if not amount.is_finite() or amount <= 0:
        raise ValueError("amount must be greater than zero.")

    currency = (row.get("currency") or "").strip().upper()

    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("currency must be a 3-letter currency code.")

    try:
        spent_on = date.fromisoformat((row.get("spent_on") or "").strip())
    except ValueError:
        raise ValueError("spent_on must use YYYY-MM-DD format.")

    description = (row.get("description") or "").strip() or None

    return {
        "user_id": None,  # Set by the import processor.
        "category_id": category_id,
        "amount": amount,
        "currency": currency,
        "description": description,
        "spent_on": spent_on,
    }


async def process_csv_import(import_id: UUID, user_id: UUID, file_bytes: bytes):
    """Process an uploaded CSV asynchronously in database batches."""

    async with AsyncSessionLocal() as db:
        import_job = await db.get(CSVImport, import_id)

        if import_job is None:
            return

        import_job.status = "processing"
        await db.commit()

        total_rows = 0
        successful_rows = 0
        failed_rows = 0
        errors = []
        batch = []

        try:
            text = file_bytes.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))

            headers = set(reader.fieldnames or [])

            missing_columns = REQUIRED_COLUMNS - headers
            if missing_columns:
                raise ValueError(
                    "Missing required CSV columns: "
                    + ", ".join(sorted(missing_columns))
                )

            # Load this user's categories once instead of querying for every row.
            category_result = await db.execute(
                select(Category.id).where(Category.user_id == user_id)
            )
            valid_category_ids = set(category_result.scalars().all())

            async def save_batch():
                nonlocal successful_rows, batch

                if not batch:
                    return

                await db.execute(insert(Expense), batch)
                successful_rows += len(batch)
                batch = []

                import_job.successful_rows = successful_rows
                import_job.failed_rows = failed_rows
                import_job.total_rows = total_rows
                import_job.errors = errors
                await db.commit()

            for row_number, row in enumerate(reader, start=2):
                total_rows += 1

                try:
                    values = parse_csv_row(row, valid_category_ids)
                    values["user_id"] = user_id
                    batch.append(values)

                    if len(batch) >= BATCH_SIZE:
                        await save_batch()

                except ValueError as exc:
                    failed_rows += 1

                    # Avoid an enormous JSON error payload for very large files.
                    if len(errors) < 5000:
                        errors.append(
                            {
                                "row": row_number,
                                "message": str(exc),
                            }
                        )

            await save_batch()

            import_job.total_rows = total_rows
            import_job.successful_rows = successful_rows
            import_job.failed_rows = failed_rows
            import_job.errors = errors
            import_job.status = "completed"
            import_job.completed_at = datetime.now(timezone.utc)

            await db.commit()

        except Exception as exc:
            await db.rollback()

            import_job = await db.get(CSVImport, import_id)
            if import_job is not None:
                import_job.status = "failed"
                import_job.total_rows = total_rows
                import_job.successful_rows = successful_rows
                import_job.failed_rows = failed_rows
                import_job.errors = errors + [
                    {"row": None, "message": str(exc)}
                ]
                import_job.completed_at = datetime.now(timezone.utc)
                await db.commit()


@router.post("/", status_code=202)
async def upload_csv(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="Please upload a .csv file.",
        )

    file_bytes = await file.read()

    if not file_bytes:
        raise HTTPException(status_code=400, detail="The CSV file is empty.")

    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="CSV file cannot exceed 20 MB.",
        )

    file_hash = hashlib.sha256(file_bytes).hexdigest()

    # Do not create another job for the same user's identical file.
    existing_result = await db.execute(
        select(CSVImport).where(
            CSVImport.user_id == current_user.id,
            CSVImport.file_hash == file_hash,
        )
    )
    existing = existing_result.scalar_one_or_none()

    if existing is not None:
        return {
            "message": "This file has already been imported or submitted.",
            "duplicate": True,
            "job_id": str(existing.id),
            "status": existing.status,
        }

    import_job = CSVImport(
        user_id=current_user.id,
        filename=file.filename,
        file_hash=file_hash,
        status="pending",
        total_rows=0,
        successful_rows=0,
        failed_rows=0,
        errors=[],
    )

    db.add(import_job)
    await db.commit()
    await db.refresh(import_job)

    # Save the uploaded file to a directory shared with the Celery worker.
    upload_dir = Path("uploads/csv_imports")
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_path = upload_dir / f"{import_job.id}.csv"
    file_path.write_bytes(file_bytes)

    # Queue the import job in Redis through Celery.
    from app.workers.csv_import_worker import process_csv_import_task

    process_csv_import_task.delay(
        str(import_job.id),
        str(current_user.id),
        str(file_path.resolve()),
    )

    return {
        "message": "CSV import accepted.",
        "duplicate": False,
        "job_id": str(import_job.id),
        "status": import_job.status,
    }

@router.get("/{import_id}")
async def get_csv_import_status(
    import_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(CSVImport).where(
            CSVImport.id == import_id,
            CSVImport.user_id == current_user.id,
        )
    )
    import_job = result.scalar_one_or_none()

    if import_job is None:
        raise HTTPException(
            status_code=404,
            detail="CSV import job not found.",
        )

    return {
        "job_id": str(import_job.id),
        "filename": import_job.filename,
        "status": import_job.status,
        "total_rows": import_job.total_rows,
        "successful_rows": import_job.successful_rows,
        "failed_rows": import_job.failed_rows,
        "errors": import_job.errors,
        "created_at": import_job.created_at,
        "completed_at": import_job.completed_at,
    }