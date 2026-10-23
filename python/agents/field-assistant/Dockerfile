FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml README.md ./
COPY field_assistant ./field_assistant
COPY web ./web
RUN uv pip install --system --no-cache .
ENV PORT=8080 WEB_DIR=/app/web
CMD exec uvicorn field_assistant.server:app --host 0.0.0.0 --port ${PORT} --proxy-headers
