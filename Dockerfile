FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=backend.config.settings.dev

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/var/media && chown -R app:app /app
USER app

EXPOSE 8000

CMD ["gunicorn", "backend.config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2"]
