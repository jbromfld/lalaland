FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml
COPY backend /app/backend
COPY frontend /app/frontend
RUN pip install --no-cache-dir .

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
