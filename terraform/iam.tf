# 1. Dispatcher Service Account (Triggers from Eventarc)
resource "google_service_account" "dispatcher_sa" {
  account_id   = "rag-dispatcher-sa"
  display_name = "V4 Ingestion Dispatcher"
}

# 2. Worker Service Account (Heavy Lifter)
resource "google_service_account" "worker_sa" {
  account_id   = "rag-worker-sa"
  display_name = "V4 Ingestion Worker"
}

# --- Permissions ---

# Allow Dispatcher to Publish to Pub/Sub
resource "google_pubsub_topic_iam_member" "dispatcher_pub" {
  topic  = google_pubsub_topic.ingestion_topic.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.dispatcher_sa.email}"
}

# Allow Dispatcher to Read from Bucket
resource "google_storage_bucket_iam_member" "dispatcher_read" {
  bucket = google_storage_bucket.rag_bucket.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.dispatcher_sa.email}"
}

# Allow Worker to Subscribe
resource "google_pubsub_subscription_iam_member" "worker_sub" {
  subscription = google_pubsub_subscription.ingestion_sub.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${google_service_account.worker_sa.email}"
}

# Allow Worker to Read Files
resource "google_storage_bucket_iam_member" "worker_read" {
  bucket = google_storage_bucket.rag_bucket.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.worker_sa.email}"
}

# Allow Worker to Write to Firestore
resource "google_project_iam_member" "worker_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.worker_sa.email}"
}

# Allow Worker to use Vertex AI
resource "google_project_iam_member" "worker_ai" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.worker_sa.email}"
}