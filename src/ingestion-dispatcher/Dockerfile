FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run uses port 8080 by default
CMD ["functions-framework", "--target=handle_upload", "--port=8080"]