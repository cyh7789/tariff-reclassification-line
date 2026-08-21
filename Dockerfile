# The snapshot ships inside the image on purpose: it is the frozen legal text a
# classification cites, so a revision and the schedule it read are one artifact.
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY fleet/ fleet/
COPY data/snapshots/ data/snapshots/

ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
CMD exec python -m uvicorn fleet.app.main:app --host 0.0.0.0 --port ${PORT:-8080}
