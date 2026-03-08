
FROM python:3.14
WORKDIR /psv-website

COPY ./pyproject.toml /psv-website/pyproject.toml
RUN pip install --no-cache-dir --upgrade .

COPY ./src /psv-website/src
COPY ./static /psv-website/static
COPY ./templates /psv-website/templates

EXPOSE 8080

CMD ["fastapi", "run", "src/main.py", "--proxy-headers", "--port", "8080"]
