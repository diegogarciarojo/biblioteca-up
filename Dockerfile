FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN DJANGO_SECRET_KEY=build-only-not-used-at-runtime-1234567890123456789012345678901234567890 python manage.py collectstatic --noinput \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin biblioteca \
    && mkdir -p /data \
    && chown -R biblioteca:biblioteca /app /data \
    && chmod +x /app/deploy/entrypoint.sh

USER biblioteca
EXPOSE 8000
ENTRYPOINT ["/app/deploy/entrypoint.sh"]
