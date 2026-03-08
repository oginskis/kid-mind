FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxcb1 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./

ENV UV_TORCH_BACKEND=cpu
RUN uv sync --frozen --no-dev

COPY src/ src/
COPY streamlit_app.py chunk_kids_cli.py agent_cli.py ./
COPY assets/ assets/
COPY .streamlit/ .streamlit/

EXPOSE 8501
CMD ["uv", "run", "streamlit", "run", "streamlit_app.py", "--server.address=0.0.0.0"]
