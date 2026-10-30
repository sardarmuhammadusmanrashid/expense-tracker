
from aioboto3 import Session
from botocore.exceptions import ClientError

from app.core.config import settings

MAX_RECEIPT_SIZE = 5 * 1024 * 1024

ALLOWED_TYPES = {
    "image/jpeg": (".jpg", b"\xff\xd8\xff"),
    "image/png": (".png", b"\x89PNG\r\n\x1a\n"),
    "application/pdf": (".pdf", b"%PDF-"),
}


def get_s3_client():
    session = Session()
    return session.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        region_name=settings.S3_REGION,
    )


async def ensure_bucket(client):
    try:
        await client.head_bucket(Bucket=settings.S3_BUCKET_NAME)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")

        if error_code not in ("404", "NoSuchBucket", "NotFound"):
            raise

        await client.create_bucket(Bucket=settings.S3_BUCKET_NAME)


async def create_upload(key: str, content_type: str) -> dict:
    if content_type not in ALLOWED_TYPES:
        raise ValueError("Unsupported receipt type.")

    async with get_s3_client() as client:
        await ensure_bucket(client)

        return await client.generate_presigned_post(
            Bucket=settings.S3_BUCKET_NAME,
            Key=key,
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 1, MAX_RECEIPT_SIZE],
            ],
            ExpiresIn=600,
        )


async def verify_receipt(key: str, expected_type: str) -> str:
    allowed = ALLOWED_TYPES.get(expected_type)

    if allowed is None:
        raise ValueError("Unsupported receipt type.")

    async with get_s3_client() as client:
        response = await client.head_object(
            Bucket=settings.S3_BUCKET_NAME,
            Key=key,
        )

        size = response["ContentLength"]

        if size < 1 or size > MAX_RECEIPT_SIZE:
            raise ValueError("Receipt must be between 1 byte and 5 MB.")

        file_response = await client.get_object(
            Bucket=settings.S3_BUCKET_NAME,
            Key=key,
        )

        body = file_response["Body"]

        try:
            header = await body.read(8)
        finally:
            await body.close()

    extension, signature = allowed

    if not header.startswith(signature):
        raise ValueError(
            "File content does not match the selected file type."
        )

    return extension


async def create_download_url(key: str) -> str:
    async with get_s3_client() as client:
        return await client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": settings.S3_BUCKET_NAME,
                "Key": key,
            },
            ExpiresIn=900,
        )


async def delete_object(key: str) -> None:
    async with get_s3_client() as client:
        await client.delete_object(
            Bucket=settings.S3_BUCKET_NAME,
            Key=key,
        )
