FROM python:3.12-slim
WORKDIR /srv
COPY pyproject.toml ./
COPY app/ app/
COPY web/dist/ web/dist/
RUN pip install --no-cache-dir .
ENV PORT=8000
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
