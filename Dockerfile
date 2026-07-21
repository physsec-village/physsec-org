
FROM python:3.14.4-slim@sha256:2ca02f32b4d9d893863367ce07ec1972819f476dd38d8612f2a9cb6a41cbb727
WORKDIR /psv-website

RUN pip install --no-cache-dir uv==0.11.7

COPY ./pyproject.toml ./uv.lock /psv-website/
RUN uv sync --frozen --no-dev --no-install-project

ENV PATH="/psv-website/.venv/bin:$PATH"

COPY ./src /psv-website/src
COPY ./static /psv-website/static
COPY ./templates /psv-website/templates

EXPOSE 8080

CMD ["fastapi", "run", "src/main.py", "--proxy-headers", "--port", "8080"]
