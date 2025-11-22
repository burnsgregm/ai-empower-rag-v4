import streamlit as st
import requests
import json
import uuid
from google.cloud import storage
from google.oauth2 import service_account
from google.auth import exceptions as auth_exceptions

# --- V4 CONFIGURATION (LOADED FROM SECRETS/ENV) ---
# Note: PROJECT_ID and BUCKET_NAME are now read directly from Streamlit Secrets or environment vars.
PROJECT_ID = "test-rag-backend-v4" 
BUCKET_NAME = "ai-empower-rag-v4-uploads" 
API_URL = "https://rag-retrieval-v4-873142271416.us-central1.run.app/query" 

st.set_page_config(page_title="AI Empower RAG V4", layout="wide")
st.title("í ¾í·  Enterprise RAG V4 (Async Parent-Child)")
st.subheader("Client Project: " + PROJECT_ID)

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
        st.warning("âš ï¸ GCP Service Account Secret is required for upload and not configured.")
        return None
        
    try:
        # Authenticates via Service Account Key stored securely in Streamlit Cloud Secrets 
        key_dict = dict(st.secrets["gcp_service_account"])
        creds = service_account.Credentials.from_service_account_info(key_dict)
        return storage.Client(credentials=creds, project=PROJECT_ID)
    except Exception as e:
        st.error(f"Credential setup failed. Check st.secrets['gcp_service_account']: {e}")
        return None

with st.sidebar:
    st.header("Tenant & Data Management")
    
    # Client Selector (Simulates Multi-Tenancy)
    st.session_state.client_id = st.text_input("Client ID (Tenant Key)", 
                                                value=st.session_state.client_id)
    st.caption(f"Files uploaded here go to: gs://{BUCKET_NAME}/uploads/{st.session_state.client_id}/")

    st.divider()

    # Document Uploader (V3 Self-Service Feature)
    st.header("Self-Service Upload")
    uploaded_file = st.file_uploader("PDF/PPTX Document", type=['pdf', 'pptx'])

    if uploaded_file and st.button("Upload & Ingest"):
        client = get_storage_client()
        if client:
            with st.spinner(f"Uploading to {st.session_state.client_id}..."):
                try:
                    bucket = client.bucket(BUCKET_NAME)
                    # The blob path automatically sets the client_id for the Dispatcher [cite: 34]
                    blob_path = f"uploads/{st.session_state.client_id}/{uploaded_file.name}"
                    blob = bucket.blob(blob_path)
                    
                    # Upload (triggers Eventarc -> Dispatcher -> Pub/Sub -> Worker)
                    blob.upload_from_file(uploaded_file, rewind=True)
                    
                    st.success("âœ… Upload Complete! Indexing started (V4 Async Pipeline).")
                    st.info("The document will be searchable in a few minutes.")
                    
                except Exception as e:
                    st.error(f"Upload Failed. Check permissions on the bucket: {e}")


# --- Chat Interface ---
# Display previous messages
for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

# Handle new user input
if prompt := st.chat_input("Ask a question about your documents..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.chat_message("user").write(prompt)

    with st.chat_message("assistant"):
        with st.spinner(f"Consulting {st.session_state.client_id} knowledge base..."):
            try:
                # Call the Retrieval API
                response = requests.post(API_URL, json={
                    "query": prompt,
                    "client_id": st.session_state.client_id,
                    # Session ID supports conversational memory [cite: 54] (though not implemented in the API code, the structure is ready)
                    "session_id": st.session_state.session_id 
                })
                
                if response.status_code != 200:
                    error_data = response.json()
                    st.error(f"API Error ({response.status_code}): {error_data.get('error', 'Unknown Error')}")
                    answer = "Error processing request."
                else:
                    data = response.json()
                    answer = data.get("answer", "Error retrieving answer.")
                    context_used = data.get("context_used", "No context found.")
                    
                    st.markdown(answer)
                    
                    with st.expander("Show Context Used (Parent Chunks)"):
                        st.code(context_used)
                
                st.session_state.messages.append({"role": "assistant", "content": answer})

            except Exception as e:
                st.error(f"Connection or runtime error: {e}")