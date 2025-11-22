import functions_framework
import os
import json
import logging
from google.cloud import storage
from google.cloud import pubsub_v1
from pypdf import PdfReader
from io import BytesIO

# Configuration
PROJECT_ID = os.environ.get("GCP_PROJECT", "test-rag-backend-v4")
TOPIC_ID = "ingestion-tasks"
storage_client = storage.Client()
publisher = pubsub_v1.PublisherClient()
topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)

logging.basicConfig(level=logging.INFO)

@functions_framework.cloud_event
def handle_upload(cloud_event):
    data = cloud_event.data
    bucket_name = data["bucket"]
    file_path = data["name"]
    
    # 1. Filter and Identify Client
    if not (file_path.endswith(".pdf") or file_path.endswith(".pptx")):
        logging.info(f"Skipping non-supported file: {file_path}")
        return

    # Path format: uploads/{client_id}/{filename}
    parts = file_path.split("/")
    if len(parts) < 3:
        client_id = "default"
    else:
        client_id = parts[1]

    logging.info(f"Processing {file_path} for Client: {client_id}")

    # 2. Download to Memory (to count pages)
    # Note: We only read the metadata/cross-reference table, not the whole text here.
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(file_path)
    content = blob.download_as_bytes()
    
    try:
        if file_path.endswith(".pdf"):
            reader = PdfReader(BytesIO(content))
            total_pages = len(reader.pages)
        else:
            # Placeholder for PPTX page counting logic
            total_pages = 1 
        
        logging.info(f"Found {total_pages} pages in {file_path}")

        # 3. Fan-Out to Pub/Sub (One message per page)
        futures = []
        for page_num in range(total_pages):
            message_json = {
                "bucket": bucket_name,
                "file_path": file_path,
                "page_num": page_num,
                "client_id": client_id,
                "total_pages": total_pages
            }
            data_str = json.dumps(message_json).encode("utf-8")
            future = publisher.publish(topic_path, data_str)
            futures.append(future)

        # Wait for all to publish (optional, but safer for Cloud Run)
        for f in futures:
            f.result()

        logging.info(f"Successfully dispatched {total_pages} tasks.")

    except Exception as e:
        logging.error(f"Error dispatching {file_path}: {e}")
        raise e