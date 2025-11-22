AI Empower Enterprise RAG Service (V4)

This repository contains the source code and Infrastructure as Code (IaC) for the Version 4.0 deployment of the AI Empower Retrieval-Augmented Generation (RAG) Service.

V4 represents a major architectural upgrade from V3, moving from synchronous Cloud Functions to a high-scale, asynchronous microservice pipeline designed to handle multi-gigabyte medical textbooks without timeout failures.

🚀 Architecture Summary

The V4 system is deployed as a Serverless Fan-Out Architecture on Google Cloud Platform (GCP).

Core Technology Stack:

IaC: Terraform

Compute: Google Cloud Run (Containerized)

Orchestration: Google Cloud Pub/Sub & Eventarc

Database: Firestore Native Mode (Multi-Tenant Vector Search)

Models: Gemini 2.5 Pro (Generation) and text-embedding-004 (Embedding)

Pipeline Flow:

GCS Upload: A user uploads a PDF/PPTX file to a client-specific path on the GCS bucket (/uploads/{client_id}/).

Dispatch: Eventarc triggers the Ingestion Dispatcher (Cloud Run). The dispatcher quickly splits the file into individual page-level tasks.

Queue: Tasks are published to the ingestion-tasks Pub/Sub topic.

Process: The Ingestion Worker (Cloud Run) pulls messages concurrently, performing Parent-Child Indexing and writing results to Firestore.

Retrieve: The Retrieval API (Cloud Run) handles user queries, retrieves relevant Parent Chunks, injects Chat History, and calls Gemini 2.5 Pro.

🗂️ Repository Structure

The project is logically divided into three main components:

ai-empower-rag-v4/
├── .gitignore
├── terraform/                # Infrastructure as Code (IaC) files
│   ├── main.tf               # Core resources (Bucket, Pub/Sub, Index)
│   ├── variables.tf          # Environment variables (project_id, region)
│   └── iam.tf                # Service Account and Role Bindings
├── src/                      # Source code for Cloud Run Microservices
│   ├── ingestion-dispatcher/ # GCS event handler (Fan-Out logic)
│   │   ├── main.py
│   │   └── Dockerfile
│   ├── ingestion-worker/     # Pub/Sub handler (Parent-Child indexing/embedding)
│   │   ├── main.py
│   │   └── Dockerfile
│   └── retrieval-api/        # REST API (Vector Search, LLM call, Memory persistence)
│       ├── main.py
│       └── Dockerfile
└── frontend_app/             # Streamlit Cloud application files
    ├── app.py                # Main Streamlit UI
    └── requirements.txt      # Python dependencies for Streamlit Cloud


⚙️ Deployment Guide for Implementers

This guide assumes the implementer has the following installed: Git, Terraform, gcloud CLI, and Docker.

Phase 1: Terraform Infrastructure

All infrastructure components, including Service Accounts and the Firestore Vector Index, are provisioned here.

Initialize & Apply: Navigate to the terraform/ directory and run:

terraform init
terraform apply


Note: This command handles the complex dependency chain, including creating the Firestore Vector Index.

Phase 2: Deploying Microservices (Cloud Run)

The services must be deployed in this order to establish the pipeline connections.

Enable Core APIs (Crucial Step for a fresh project):

gcloud services enable cloudbuild.googleapis.com run.googleapis.com eventarc.googleapis.com artifactregistry.googleapis.com aiplatform.googleapis.com


Deploy Dispatcher (from src/ingestion-dispatcher):

gcloud run deploy rag-dispatcher-v4 --source . --region us-central1 --service-account rag-dispatcher-sa@test-rag-backend-v4.iam.gserviceaccount.com --allow-unauthenticated


Wire Eventarc Trigger (Connects GCS to the Dispatcher. Requires manual IAM grants for Cloud Storage Agent):

# IMPORTANT: Update Project Number with the actual number (e.g., 873142271416)
PROJECT_NUMBER=[YOUR_PROJECT_NUMBER]

gcloud projects add-iam-policy-binding test-rag-backend-v4 --member="serviceAccount:service-$PROJECT_NUMBER@gs-project-accounts.iam.gserviceaccount.com" --role="roles/pubsub.publisher"

gcloud eventarc triggers create dispatcher-trigger --location us-central1 --destination-run-service rag-dispatcher-v4 --destination-run-region us-central1 --event-filters "type=google.cloud.storage.object.v1.finalized" --event-filters "bucket=ai-empower-rag-v4-uploads" --service-account rag-dispatcher-sa@test-rag-backend-v4.iam.gserviceaccount.com


Deploy Worker (from src/ingestion-worker. COPY THE SERVICE URL):

gcloud run deploy rag-worker-v4 --source . --region us-central1 --service-account rag-worker-sa@test-rag-backend-v4.iam.gserviceaccount.com --allow-unauthenticated


Wire Pub/Sub Push: (Connects the queue to the Worker).

# IMPORTANT: Replace [YOUR_WORKER_URL] with the URL copied above.
gcloud pubsub subscriptions update ingestion-workers-sub --push-endpoint=[YOUR_WORKER_URL]


Deploy Retrieval API (from src/retrieval-api. COPY THE API URL for the frontend):

gcloud run deploy rag-retrieval-v4 --source . --region us-central1 --service-account rag-worker-sa@test-rag-backend-v4.iam.gserviceaccount.com --allow-unauthenticated


Phase 3: Frontend Deployment (Streamlit Cloud)

The frontend uses the rag-retrieval-v4 URL and requires a Service Account JSON key for secure document uploading.

Set Secrets: Ensure the JSON key for the rag-frontend-uploader Service Account (used in V3) is configured in Streamlit Cloud Secrets under the key: gcp_service_account.

Deploy App: Deploy the frontend_app/app.py file from this repository to Streamlit Cloud.

🧪 Verification: Smoke Test

To verify the end-to-end pipeline and conversational memory:

Trigger Ingestion: Upload a sample PDF to the GCS Bucket path: gs://ai-empower-rag-v4-uploads/uploads/test_client/sample.pdf.

Verify Indexing: Tail the Worker logs and confirm INFO:root:Indexed Page X: Y Parents created.

gcloud beta run services logs tail rag-worker-v4 --project test-rag-backend-v4 --region us-central1


Test Memory (via UI or cURL): Use the following 3-part sequence via the Streamlit UI to confirm conversational memory is injected into the LLM prompt:

Q1: "What are the complications of a splenectomy?"

Q2: "What are the complications of a mastectomy?"

Q3: "What are the differences between the complications of the two?"
