FROM node:20-slim AS web
WORKDIR /build
COPY web/package.json web/package-lock.json* ./
RUN npm install
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /srv
COPY pyproject.toml ./
COPY app/ app/
RUN pip install --no-cache-dir .
COPY --from=web /build/dist web/dist
ENV PORT=8000
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
