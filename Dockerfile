FROM node:22-alpine AS frontend-builder

WORKDIR /frontend

COPY package.json package-lock.json vite.config.js index.html ./
COPY frontend/ frontend/
RUN npm ci && npm run build

# ---

FROM python:3.12-alpine AS builder

WORKDIR /app

RUN apk add --no-cache gcc musl-dev libffi-dev

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---

FROM python:3.12-alpine

WORKDIR /app

RUN apk add --no-cache libffi su-exec

COPY --from=builder /install /usr/local

COPY alembic/ alembic/
COPY alembic.ini .
COPY app/ app/
COPY --from=frontend-builder /frontend/app/static/vue app/static/vue
COPY scripts/ scripts/
COPY docker-entrypoint.sh /docker-entrypoint.sh

RUN addgroup -S app && adduser -S -G app app && \
    mkdir -p /app/data && \
    chown -R app:app /app && \
    chmod +x /docker-entrypoint.sh && \
    pip uninstall -y pip setuptools

EXPOSE 8000

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
