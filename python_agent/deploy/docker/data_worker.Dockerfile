FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY rs_core ./rs_core
COPY configs ./configs
COPY dic ./dic
COPY pyproject.toml ./
RUN pip install --no-cache-dir ".[serving]"

CMD ["python", "-m", "rs_core.data.runtime.worker", "health"]
