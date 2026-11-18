# beertor seeder image — creates + fills the Beer collection in Weaviate.
# The image expects beer.db already built (build_db.py); it is a generated
# artifact (gitignored), so build it before docker build:
#   .venv/bin/python beertor/build_db.py
#
# Build context must be beertor/:
#   docker build -f beertor/Dockerfile -t sommebeer-data beertor/
FROM python:3.12-slim

RUN pip install --no-cache-dir weaviate-client==4.24.1

WORKDIR /app
COPY beer.db import_weaviate.py /app/

ENV WEAVIATE_HOST=localhost \
    WEAVIATE_PORT=8080 \
    WEAVIATE_GRPC_PORT=50051

# Run as a one-shot seeder (k8s Job): restartPolicy OnFailure until success.
# Re-running is idempotent (same UUIDs, drop+recreate collection).
CMD ["python", "import_weaviate.py"]
