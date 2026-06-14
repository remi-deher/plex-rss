FROM python:3.12-alpine

WORKDIR /app

RUN apk update && apk upgrade && \
    apk add --no-cache --virtual .build-deps gcc musl-dev libffi-dev && \
    apk add --no-cache libffi

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip uninstall -y pip setuptools && \
    apk del .build-deps

COPY . .

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
