# 1. Storage Bucket
resource "google_storage_bucket" "rag_bucket" {
  name          = var.bucket_name
  location      = var.region
  force_destroy = false
  uniform_bucket_level_access = true
}

# 2. Pub/Sub Topic
resource "google_pubsub_topic" "ingestion_topic" {
  name = "ingestion-tasks"
}

# 3. Pub/Sub Subscription
resource "google_pubsub_subscription" "ingestion_sub" {
  name  = "ingestion-workers-sub"
  topic = google_pubsub_topic.ingestion_topic.name
  ack_deadline_seconds = 600 
  
  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }
}

# 4. Enable Firestore API
resource "google_project_service" "firestore" {
  service = "firestore.googleapis.com"
  disable_on_destroy = false
}

# 5. Create the Database Instance (NEW STEP)
# This creates the actual "(default)" database in Native mode
resource "google_firestore_database" "database" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"
  
  # Wait for API enablement
  depends_on = [google_project_service.firestore]
}

# 6. Vector Index
resource "google_firestore_index" "vector_index" {
  collection = "rag_children"
  database   = google_firestore_database.database.name

  fields {
    field_path = "client_id"
    order      = "ASCENDING"
  }

  fields {
    field_path = "embedding"
    vector_config {
      dimension = 768
      flat {}
    }
  }
}