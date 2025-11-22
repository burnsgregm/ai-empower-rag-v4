import streamlit as st
import requests
import json
import uuid
from google.cloud import storage
from google.oauth2 import service_account
from google.auth import exceptions as auth_exceptions

# --- V4 CONFIGURATION (LOADED FROM SECRETS/ENV) ---
# Note: PROJECT_ID and BUCKET_NAME are currently hardcoded for deployment simplicity.
PROJECT_ID = "test-rag-backend-v4" 
BUCKET_NAME = "ai-empower-rag-v4-uploads" 
API_URL = "https://rag-retrieval-v4-873142271416.us-central1.run.app/query" 

st.set_page_config(page_title="Test Medical RAG V4", layout="wide")
st.title("Test Medical RAG V4")

# --- State Management (Persists Chat History) ---
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []
if "client_id" not in st.session_state:
    st.session_state.client_id = "test_client" # Default client ID, matching smoke test

# --- Secure Storage Client (V3 Feature Preservation) ---
@st.cache_resource(ttl=3600)
def get_storage_client():
    """Initializes Google Cloud Storage client using service account credentials stored in st.secrets."""
    if "gcp_service_account" not in st.secrets:
        st.warning("GCP Service Account Secret is required for upload and not configured.")
        return None
        
    try:
        # Authenticates via Service Account Key stored securely in Streamlit Cloud Secrets
        key_dict = dict(st.secrets["gcp_service_account"])
        creds = service_account.Credentials.from_service_account_info(key_dict)
        return storage.Client(credentials=creds, project=PROJECT_ID)
    except auth_exceptions.DefaultCredentialsError:
        st.error("Default Application Credentials not found.")
        return None
    except Exception as e:
        st.error(f"Credential setup failed. Check st.secrets['gcp_service_account']: {e}")
        return None

with st.sidebar:
    st.header("Tenant & Data Management")
    
    # Client Selector (Simulates Multi-Tenancy)
    st.session_state.client_id = st.text_input("Client ID (Tenant Key)", 
                                                value=st.session_state.client_id)
    # The GCS path detail is removed as requested.

    st.header("Self-Service Upload")
    uploaded_file = st.file_uploader("PDF/PPTX Document", type=['pdf', 'pptx'])

    if uploaded_file and st.button("Upload & Ingest"):
        client = get_storage_client()
        if client:
            with st.spinner(f"Uploading to {st.session_state.client_id}..."):
                try:
                    bucket = client.bucket(BUCKET_NAME)
                    # The blob path automatically sets the client_id for the Dispatcher
                    blob_path = f"uploads/{st.session_state.client_id}/{uploaded_file.name}"
                    blob = bucket.blob(blob_path)
                    
                    # Upload (triggers Eventarc -> Dispatcher -> Pub/Sub -> Worker)
                    blob.upload_from_file(uploaded_file, rewind=True)
                    
                    st.success("Upload Complete! Indexing started (V4 Async Pipeline).")
                    st.info("The document will be searchable in a few minutes.")
                    
                except Exception as e:
                    st.error(f"Upload Failed. Check permissions on the bucket: {e}")


# --- Chat Interface ---
# Display previous messages
for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

# Handle new user input
if prompt := st.chat_input("Ask a question about your documents..."):
    # 1. Add user message to history
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.chat_message("user").write(prompt)

    # 2. Call the V4 Retrieval API
    with st.chat_message("assistant"):
        with st.spinner(f"Consulting {st.session_state.client_id} knowledge base..."):
            try:
                # Call the Retrieval API
                response = requests.post(API_URL, json={
                    "query": prompt,
                    "client_id": st.session_state.client_id,
                    # Session ID supports conversational memory
                    "session_id": st.session_state.session_id 
                })
                
                # Handle API Error
                if response.status_code != 200:
                    error_data = response.json()
                    st.error(f"API Error ({response.status_code}): {error_data.get('error', 'Unknown Error')}")
                    answer = "Error processing request."
                else:
                    data = response.json()
                    answer = data.get("answer", "Error retrieving answer.")
                    # context_used is retrieved but not displayed as requested.
                    
                    # Display Answer
                    st.markdown(answer)
                                
                # 3. Add assistant message to history
                st.session_state.messages.append({"role": "assistant", "content": answer})

            except requests.exceptions.ConnectionError:
                st.error("Connection Failed. Ensure the Cloud Run URL is correct and the service is active.")
            except Exception as e:
                st.error(f"An unexpected error occurred: {e}")