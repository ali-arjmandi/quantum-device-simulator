FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/data

ENV FLASK_APP=app
EXPOSE 5555

CMD ["gunicorn", "-b", "0.0.0.0:5555", "app:app"]
