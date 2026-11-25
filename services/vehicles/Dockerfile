FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

# The service runs as a normal user, not root.
RUN useradd --system --uid 10001 --no-create-home appuser

WORKDIR /app

# Dependencies first: this layer is rebuilt only when requirements.txt changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy only what the service needs to run (no tests, no .env, no virtual environment).
COPY main.py .
COPY app/ app/
COPY migrations/ migrations/
COPY seed/ seed/

USER appuser
EXPOSE 8000

# One worker, several threads: the database migrations run once at start-up, never
# in two workers at the same time. The 120 s timeout covers a start-up that waits up
# to 90 s for a sleeping Azure SQL database to wake. Requests are logged by the app.
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 120 main:app"]
