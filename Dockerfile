FROM python:3.11-slim

# Build arguments for versioning
ARG VERSION=dev
ARG BUILD_DATE
ARG VCS_REF

# Labels for image metadata
LABEL org.opencontainers.image.title="Tattoo Booking Bot"
LABEL org.opencontainers.image.description="WhatsApp-based tattoo booking bot"
LABEL org.opencontainers.image.version="${VERSION}"
LABEL org.opencontainers.image.created="${BUILD_DATE}"
LABEL org.opencontainers.image.revision="${VCS_REF}"
LABEL org.opencontainers.image.source="https://github.com/${GITHUB_REPOSITORY:-unknown}"

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn[standard] pydantic-settings sqlalchemy psycopg2-binary stripe httpx alembic

COPY . /app

# Copy version file if it exists
COPY VERSION /app/VERSION 2>/dev/null || echo "${VERSION}" > /app/VERSION

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
