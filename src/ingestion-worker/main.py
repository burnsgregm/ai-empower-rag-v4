# V5 WORKER CODE: DUAL-WRITE (Firestore for Search + Parquet for Archive)
import os
import json
import logging
import hashlib
from flask import Flask, request, jsonify
from google.cloud import storage
from google.cloud import firestore
from google.cloud.firestore_v1.vector import Vector
from langchain_google_vertexai import VertexAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from io import BytesIO
import base64
from google.cloud import firestore as fs_module

# V5 NEW IMPORTS
import pandas as pd
import pyarrow.parquet as pq
import pyarrow as pa
import tempfile
import time
import numpy as np # NEW: Used for cleaner list handling

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# --- Configuration ---
PROJECT_ID = os.environ.get("GCP_PROJECT", "test-rag-backend-v4")
ARCHIVE_BUCKET_NAME = "ai-empower-rag-v4-uploads"

db = firestore.Client(project=PROJECT_ID)
storage_client = storage.Client()
embeddings = VertexAIEmbeddings(model_name="text-embedding-004", project=PROJECT_ID)

def get_deterministic_id(key_string):
    """Generate a hash ID to ensure Idempotency"""
    return hashlib.sha256(key_string.encode("utf-8")).hexdigest()

@app.route("/", methods=["POST"])
def process_task():
    envelope = request.get_json()
    if not envelope or "message" not in envelope: return jsonify({"error": "Invalid Pub/Sub message"}), 400
    
    pubsub_message = envelope["message"]
    data_str = base64.b64decode(pubsub_message["data"]).decode("utf-8")
    job = json.loads(data_str)

    bucket_name = job["bucket"]
    file_path = job["file_path"]
    page_num = job["page_num"]
    client_id = job["client_id"]

    logging.info(f"Worker processing Page {page_num} of {file_path}")

    # Data structure to hold all chunks for Parquet export
    parquet_data = []

    try:
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(file_path)
        content = blob.download_as_bytes()
        reader = PdfReader(BytesIO(content))
        page = reader.pages[page_num]
        raw_text = page.extract_text()

        if not raw_text.strip(): return jsonify({"message": "Empty page text."}), 200

        parent_splitter = RecursiveCharacterTextSplitter(chunk_size=2000, chunk_overlap=200)
        parent_chunks = parent_splitter.split_text(raw_text)

        firestore_batch = db.batch()

        for p_idx, parent_text in enumerate(parent_chunks):
            parent_key = f"{file_path}|{page_num}|{p_idx}"
            parent_id = get_deterministic_id(parent_key)
            
            # --- 1. FIRESTORE WRITE: PARENT ---
            parent_ref = db.collection("rag_parents").document(parent_id)
            firestore_batch.set(parent_ref, {"client_id": client_id, "source": file_path, "page": page_num, "content": parent_text})

            # Child Chunking
            child_splitter = RecursiveCharacterTextSplitter(chunk_size=400, chunk_overlap=50)
            child_chunks = child_splitter.split_text(parent_text)

            if child_chunks:
                vectors = embeddings.embed_documents(child_chunks)
                
                for c_idx, vector_list in enumerate(vectors):
                    child_key = f"{parent_key}|{c_idx}"
                    child_id = get_deterministic_id(child_key)
                    child_text = child_chunks[c_idx]
                    
                    # --- 1. FIRESTORE WRITE: CHILD (for V5 search) ---
                    child_ref = db.collection("rag_children").document(child_id)
                    firestore_batch.set(child_ref, {"client_id": client_id, "parent_id": parent_id, "content": child_text, "embedding": Vector(vector_list)})

                    # --- 2. ACCUMULATE DATA FOR PARQUET (using pure Python list) ---
                    parquet_data.append({
                        "id": child_id,
                        "client_id": client_id,
                        "parent_id": parent_id,
                        "embedding": vector_list, # Store as raw Python list
                        "content": child_text,
                        "source": file_path,
                        "page": page_num,
                        "timestamp": time.time()
                    })

        # Final commit to Firestore
        firestore_batch.commit()

        # --- 3. PARQUET WRITE: ARCHIVE TO GCS ---
        if parquet_data:
            # V5 FIX: Use Pandas to create the table, as it handles list-of-lists conversion cleanly.
            df = pd.DataFrame(parquet_data)
            
            # Prepare schema for nested embedding column
            schema = pa.schema([
                pa.field('id', pa.string()),
                pa.field('client_id', pa.string()),
                pa.field('parent_id', pa.string()),
                pa.field('content', pa.string()),
                pa.field('source', pa.string()),
                pa.field('page', pa.int64()),
                pa.field('timestamp', pa.float64()),
                # Define embedding column as a list of floats (Vector Type)
                pa.field('embedding', pa.list_(pa.float32())) 
            ])
            
            table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
            
            # Write Table to a local temporary Parquet file
            temp_parquet_file = os.path.join(tempfile.gettempdir(), f"page_{page_num}_{client_id}_{get_deterministic_id(file_path)}.parquet")
            pq.write_table(table, temp_parquet_file)

            # Upload the Parquet file to the Archive path in GCS
            archive_blob_path = f"archive/{client_id}/{os.path.basename(file_path)}/page_{page_num}.parquet"
            archive_bucket = storage_client.bucket(ARCHIVE_BUCKET_NAME)
            archive_blob = archive_bucket.blob(archive_blob_path)
            archive_blob.upload_from_filename(temp_parquet_file)
            
            os.remove(temp_parquet_file)
            logging.info(f"V5 Archive successful for Page {page_num}: Wrote {len(parquet_data)} records to GCS Parquet.")


        logging.info(f"Indexing complete for Page {page_num}.")
        return jsonify({"message": f"Indexed page {page_num}"}), 200

    except Exception as e:
        logging.error(f"Worker Failed: {e}")
        # Returning 500 will cause Pub/Sub to retry the message
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8080)