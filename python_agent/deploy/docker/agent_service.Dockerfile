FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \n    PYTHONDONTWRITEBYTECODE=1

COPY rs_core ./rs_core
COPY configs ./configs
COPY dic ./dic
COPY pyproject.toml ./
RUN pip install --no-cache-dir ".[serving]"

EXPOSE 8001
CMD ["uvicorn", "rs_core.serving.api.agent_app:app", "--host", "0.0.0.0", "--port", "8001"]
