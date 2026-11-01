FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app ./app

RUN mkdir -p /data
ENV WASIGNAL_DATA_DIR=/data

EXPOSE 8000

# One worker on purpose: the outbox worker and scheduler are in-process and the
# store is SQLite. See docs/DEPLOYMENT.md before scaling out.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
