FROM python:3.11-slim
WORKDIR /srv
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY . .
WORKDIR /srv/backend
ENV PYTHONUNBUFFERED=1
# Seed the synthetic data on first start (skipped if customers already exist), then serve API + console.
CMD ["sh", "-c", "python -m seed.bootstrap && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
