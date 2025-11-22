variable "project_id" {
  description = "The GCP Project ID"
  type        = string
  default     = "test-rag-backend-v4"
}

variable "region" {
  description = "GCP Region"
  type        = string
  default     = "us-central1"
}

variable "bucket_name" {
  description = "Name of the V4 Storage Bucket"
  type        = string
  default     = "ai-empower-rag-v4-uploads"
}