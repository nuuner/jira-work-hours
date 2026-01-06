FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY hello.py vacation_optimizer.py ./

RUN uv sync --frozen --no-cache

EXPOSE 4012

CMD ["uv", "run", "fastapi", "run", "hello.py", "--port", "4012"] 
