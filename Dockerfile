FROM python:3.12-alpine AS builder

WORKDIR /app

RUN apk add --no-cache gcc musl-dev libffi-dev

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---

FROM python:3.12-alpine

WORKDIR /app

RUN apk add --no-cache libffi

COPY --from=builder /install /usr/local

COPY alembic/ alembic/
COPY alembic.ini .
COPY app/ app/
COPY scripts/ scripts/

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
