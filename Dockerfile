FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# SQLite data directory
RUN mkdir -p /data

ENV PORT=8000
ENV DB_PATH=/data/hub.db
ENV ADMIN_KEY=admin-secret
ENV HUB_URL=http://localhost:8000

EXPOSE 8000

VOLUME ["/data"]

CMD ["python", "server.py"]
