import os
import json
import logging
import hashlib
from flask import Flask, request
from google.cloud import storage
from google.cloud import firestore
from google.cloud.firestore_v1.vector import Vector
from langchain_google_vertexai import VertexAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from io import BytesIO
import base64

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Config
PROJECT_ID = os.environ.get("GCP_PROJECT", "test-rag-backend-v4")
db = firestore.Client(project=PROJECT_ID)
storage_client = storage.Client()
embeddings = VertexAIEmbeddings(model_name="text-embedding-004", project=PROJECT_ID)

def get_deterministic_id(key_string):
    """Generate a hash ID to ensure Idempotency [SRS 4.3]"""
    return hashlib.sha256(key_string.encode("utf-8")).hexdigest()

@app.route("/", methods=["POST"])
def process_task():
    envelope = request.get_json()
    if not envelope:
        return "Bad Request", 400

    # Decode Pub/Sub message
    if "message" not in envelope:
        return "Invalid Pub/Sub message format", 400
    
    pubsub_message = envelope["message"]
    data_str = base64.b64decode(pubsub_message["data"]).decode("utf-8")
    job = json.loads(data_str)

    bucket_name = job["bucket"]
    file_path = job["file_path"]
    page_num = job["page_num"]
    client_id = job["client_id"]

    logging.info(f"Worker processing Page {page_num} of {file_path}")

    try:
        # 1. Download Specific Page
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(file_path)
        content = blob.download_as_bytes()
        
        # 2. Parse Text (PDF)
        # Optimization: In a real huge file, we'd use range headers, 
        # but pypdf requires the whole file structure usually.
        # Since we are in Cloud Run, memory is cheap.
        reader = PdfReader(BytesIO(content))
        page = reader.pages[page_num]
        raw_text = page.extract_text()

        if not raw_text.strip():
            logging.warning("Empty page text.")
            return "OK", 200

        # 3. Parent Chunking (Context)
        # Large chunks for the LLM to read
        parent_splitter = RecursiveCharacterTextSplitter(chunk_size=2000, chunk_overlap=200)
        parent_chunks = parent_splitter.split_text(raw_text)

        batch = db.batch()
        batch_count = 0

        for p_idx, parent_text in enumerate(parent_chunks):
            # Generate deterministic Parent ID
            parent_key = f"{file_path}|{page_num}|{p_idx}"
            parent_id = get_deterministic_id(parent_key)
            
            parent_ref = db.collection("rag_parents").document(parent_id)
            batch.set(parent_ref, {
                "client_id": client_id,
                "source": file_path,
                "page": page_num,
                "content": parent_text
            })

            # 4. Child Chunking (Vectors)
            # Small chunks for precise matching
            child_splitter = RecursiveCharacterTextSplitter(chunk_size=400, chunk_overlap=50)
            child_chunks = child_splitter.split_text(parent_text)

            # Embed Batch of Children
            if child_chunks:
                vectors = embeddings.embed_documents(child_chunks)
                
                for c_idx, child_text in enumerate(child_chunks):
                    child_key = f"{parent_key}|{c_idx}"
                    child_id = get_deterministic_id(child_key)
                    
                    child_ref = db.collection("rag_children").document(child_id)
                    batch.set(child_ref, {
                        "client_id": client_id,
                        "parent_id": parent_id, # Link back to Parent
                        "content": child_text,
                        "embedding": Vector(vectors[c_idx])
                    })
                    batch_count += 2 # One parent + one child write

        # Commit to Firestore
        batch.commit()
        logging.info(f"Indexed Page {page_num}: {len(parent_chunks)} Parents created.")

        return "OK", 200

    except Exception as e:
        logging.error(f"Worker Failed: {e}")
        return f"Error: {e}", 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8080)