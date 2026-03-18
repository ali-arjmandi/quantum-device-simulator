FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/data

ENV FLASK_APP=app
EXPOSE 5555

# gthread + threads: SSE monitor holds a thread; other requests use remaining threads (sync worker would block everything).
CMD ["gunicorn", "-k", "gthread", "-w", "1", "--threads", "8", "-b", "0.0.0.0:5555", "--timeout", "120", "app:app"]
