# Expense Tracker API

An asynchronous expense-tracking backend built with Python 3.11+, FastAPI, SQLAlchemy 2.0, Pydantic v2, PostgreSQL, Redis, Alembic, Celery, and S3-compatible object storage.

Developed for a Python Backend Developer Assessment, this project focuses on secure authentication, user-scoped data access, financial precision, concurrency safety, background processing, CSV imports, and private receipt storage.

## Features

- Password hashing, access/refresh tokens, refresh rotation, and reuse protection.
- Redis-backed login rate limiting.
- User-scoped expense and category operations.
- Expense CRUD, filtering, and keyset pagination.
- Decimal-based monetary values.
- Idempotent request handling and ETag/If-Match optimistic concurrency.
- Monthly reports and currency conversion.
- Transactional outbox processing for asynchronous events and budget checks.
- Background CSV imports with row-level validation/reporting.
- Presigned receipt upload/download URLs using S3-compatible storage.
- Docker Compose development environment.

## Technology stack

| Area | Technology |
|---|---|
| Language | Python 3.11+ |
| API | FastAPI |
| Validation | Pydantic v2 |
| ORM | SQLAlchemy 2.0 async |
| Database | PostgreSQL |
| Migrations | Alembic |
| Cache / broker | Redis |
| Background jobs | Celery and outbox worker |
| Object storage | S3-compatible storage (S3Mock locally) |
| Tests | pytest, pytest-asyncio |

## Architecture

- **API:** handles HTTP requests, validation, authentication, and application operations.
- **PostgreSQL:** stores application data, imports, idempotency records, and outbox events.
- **Redis:** supports login rate limiting and the Celery broker.
- **CSV worker:** processes import jobs outside the HTTP request lifecycle.
- **Outbox worker:** processes pending database events, including budget checks and receipt cleanup.
- **Object storage:** stores private receipt objects and provides temporary presigned URLs.

The transactional outbox records an event in the same database transaction as the business operation that generated it. A separate worker processes the event asynchronously.

## Prerequisites

- Git
- Docker Desktop with Docker Compose
- Terminal (PowerShell, Windows Terminal, or Bash)

For a non-Docker setup, install Python 3.11+, PostgreSQL, and Redis separately.

## Quick start with Docker

### 1. Clone the repository

```bash
git clone https://github.com/sardarmuhammadusmanrashid/expense-tracker.git
cd expense-tracker
```

### 2. Configure environment variables

Create a `.env` file in the project root. Use the exact variable names expected by `app/core/config.py` and `docker-compose.yml`.

The configuration includes application settings, PostgreSQL credentials/URL, Redis URL, JWT secret and lifetimes, password hashing settings, and S3 credentials/endpoint.

Example S3Mock settings for container-to-container access:

```env
S3_ENDPOINT_URL=http://s3mock:9090
S3_ACCESS_KEY=test
S3_SECRET_KEY=test
S3_BUCKET_NAME=expense-receipts
S3_REGION=us-east-1
```

Set a strong, unique `SECRET_KEY` and database password. Never commit `.env` or production credentials.

### 3. Build and start services

```bash
docker compose up --build -d
docker compose ps
```

View logs:

```bash
docker compose logs -f api
docker compose logs -f worker
docker compose logs -f csv_worker
```

The Compose stack runs the API, PostgreSQL, Redis, and configured worker services. S3Mock is used for local S3-compatible receipt testing when present in the Compose configuration.

### 4. Apply database migrations

After PostgreSQL is available and the API container is running:

```bash
docker compose exec api alembic upgrade head
```

This initializes or updates the database schema to the latest Alembic revision.

## Environment configuration

Check `app/core/config.py`, `.env.example` (if present), and `docker-compose.yml` for the exact required names/defaults. Common settings include:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `POSTGRES_PASSWORD` | Database password, if used by Compose |
| `REDIS_URL` | Redis connection string |
| `SECRET_KEY` | Token signing secret |
| `ALGORITHM` | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access-token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh-token lifetime |
| `PASSWORD_HASH_ALGORITHM` | Password hashing configuration |
| `S3_ENDPOINT_URL` | S3/S3Mock endpoint |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | Storage credentials |
| `S3_BUCKET_NAME` | Receipt bucket |
| `S3_REGION` | Storage region |

Keep secrets out of source control.

## Database migrations

Alembic migration scripts are stored in the project's migration versions directory.

Apply all migrations:

```bash
docker compose exec api alembic upgrade head
```

Check current revision:

```bash
docker compose exec api alembic current
```

View migration history:

```bash
docker compose exec api alembic history
```

After changing SQLAlchemy models, generate a migration:

```bash
docker compose exec api alembic revision --autogenerate -m "describe_schema_change"
```

Review the generated migration for indexes, constraints, defaults, foreign keys, and data migrations before applying it:

```bash
docker compose exec api alembic upgrade head
```

Roll back one revision when appropriate:

```bash
docker compose exec api alembic downgrade -1
```

Do not edit migrations already applied in shared/deployed environments. Create a new revision instead.

## Run and inspect the API

With the API running:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI schema: `http://localhost:8000/openapi.json`

The API version prefix is configured in application settings (for example, `API_V1_PREFIX`). Use Swagger UI to inspect the exact routes, request/response schemas, and authentication requirements.

## Background workers

### Outbox worker

The outbox worker polls pending database events and processes them asynchronously. Events include budget-check work and receipt cleanup.

```bash
docker compose logs -f worker
```

For failures, inspect worker logs and the event status/attempt information stored in the database.

### CSV worker

CSV imports are processed by Celery outside the initial HTTP request.

```bash
docker compose logs -f csv_worker
```

The worker uses the configured Redis broker. If jobs remain queued, check Redis and the CSV worker logs.

## API modules

Use Swagger UI for the exact route paths and schemas exposed by the current application.

| Module | Responsibility |
|---|---|
| Authentication | User authentication and token lifecycle |
| Categories | User-owned category operations |
| Expenses | Expense CRUD, filtering, pagination, idempotency, and receipts |
| Reports | Monthly reporting and expense summaries |
| Notifications | Budget-alert/notification functionality |
| CSV imports | Submit and inspect asynchronous import jobs |

Protected endpoints require a valid access token. User-owned resources should always be scoped to the authenticated user.

## Assessment implementation notes

This section explains the technical requirements addressed by the assessment. Verify exact behavior against the current source code and tests.

### Financial precision

Use Python `Decimal` and database numeric columns for money instead of binary floating-point values to avoid common rounding errors.

### Authentication and refresh tokens

The assessment expects secure password hashing, short-lived access tokens, longer-lived refresh tokens, refresh-token rotation, and protection against reuse of an old refresh token. Reuse is intended to invalidate the associated token family/session.

### Login rate limiting

The assessment specifies five failed login attempts per email within 15 minutes. A subsequent attempt should return HTTP 429 with a `Retry-After` header. Redis is used for rate-limit state.

### User data isolation

Expense and category queries must be scoped to the authenticated user's ID. Access to another user's resource should not disclose its existence; the assessment expects a not-found response.

### Expense listing and keyset pagination

The assessment specifies filtering and keyset pagination with stable ordering by `spent_on` descending and ID descending as a tie-breaker.

### Idempotency

Idempotency keys allow safe retries after timeouts. Expected behavior:
- Same key and same request body: replay the original result.
- Same key and different body: reject (assessment specifies HTTP 422).
- Concurrent requests with the same key: do not create duplicate expenses.
- Records expire after the configured retention period (assessment specifies 24 hours).

### Optimistic concurrency

Expense responses expose an ETag/version. Updates use `If-Match` to prevent stale clients overwriting newer data. The assessment specifies HTTP 428 when the precondition is missing and HTTP 412 when the version is stale. Version updates should be atomic.

### Monthly reports and currency conversion

The assessment asks for monthly/category summaries and comparison with the previous month. Currency conversion should use the rate for the expense date or the latest available rate before that date. Review the report query and tests for exact supported behavior.

### Transactional outbox and budget alerts

Outbox events are written in the same transaction as the related business change and processed later by a worker. The assessment expects retry-safe processing and deduplication of alerts for the same category, month, and threshold, including recalculation after expense edits/deletions.

### CSV imports

CSV imports are processed asynchronously. The assessment asks for row validation, partial success when some rows are invalid, row-level errors, duplicate-file protection, and support for files up to 100,000 rows without loading the entire file into memory. Verify these guarantees against the implementation and tests.

### Receipt storage

The receipt flow is:
1. Request a presigned upload URL for an expense.
2. Upload directly to the returned object-storage URL using the returned form fields.
3. Call the receipt confirmation endpoint.
4. The API verifies the stored object and its actual file signature (magic bytes), not just the filename or declared content type.
5. Request a temporary presigned download URL when needed.

The assessment specifies a 5 MB maximum and JPG, PNG, and PDF formats. Objects should remain private. Expense deletion should trigger receipt cleanup, with a retry/cleanup path if storage deletion fails.

For local S3Mock, containers can use the Compose hostname such as `http://s3mock:9090`. A browser on the host generally cannot resolve Docker service hostnames. Browser uploads need a presigned URL endpoint reachable by the browser (for example, the published host port), with the signature generated for that same endpoint.

## Testing

Run tests inside the API container:

```bash
docker compose exec api pytest -v
```

Run with coverage:

```bash
docker compose exec api pytest --cov=app --cov-report=term-missing
```

The assessment asks for at least 30 tests and 85% coverage. Important scenarios include authentication/token rotation/rate limiting, user data isolation, expense CRUD and pagination, concurrent idempotency, ETag preconditions, monthly reports, outbox retries/double processing, CSV validation/duplicates, and receipt type/size/magic-byte/deletion behavior.

Use PostgreSQL for integration tests. SQLite is not an equivalent substitute for PostgreSQL-specific behavior and concurrency guarantees.

Do not claim the test-count or coverage targets have passed until the commands have actually been run and their output reviewed.

## Troubleshooting

Check service status:

```bash
docker compose ps
```

Inspect logs:

```bash
docker compose logs --tail=100 api
docker compose logs --tail=100 worker
docker compose logs --tail=100 csv_worker
docker compose logs --tail=100 db
docker compose logs --tail=100 redis
```

**API cannot connect to PostgreSQL/Redis:** Inside Docker, use Compose service hostnames rather than `localhost`. Check environment variables and service health.

**Migration failure:** Check `alembic current`, `alembic history`, and database logs before retrying.

**CSV job remains queued:** Confirm Redis and the CSV worker are running and that the Celery broker URL points to the correct Redis service.

**Receipt URL does not work in the browser:** A URL containing a Compose hostname such as `s3mock` is normally reachable only inside the Docker network. Configure the presigned URL with a host-reachable endpoint for browser uploads.

## AI usage disclosure

AI assistance was used during development for brainstorming, implementation guidance, debugging, and documentation drafting. The project author is responsible for reviewing the implementation and validating behavior and test results. This README describes assessment expectations and intended behavior; it does not claim that a requirement has passed verification unless supported by actual test results.
