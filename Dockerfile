# RAG service image
FROM python:3.11-slim

RUN curl -LsSf https://astral.sh/uv/install.sh | sh

WORKDIR /app
COPY . /app

RUN uv sync --frozen

EXPOSE 8000
CMD ["uv", "run", "python", "-m", "uvicorn", "rag.api:app", "--host", "0.0.0.0", "--port", "8000"]
