FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install .
ENTRYPOINT ["captcha-mcp"]
