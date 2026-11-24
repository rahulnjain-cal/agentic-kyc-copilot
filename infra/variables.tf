variable "project_id" {
  description = "Google Cloud project ID for deploying the Arthashastra KYC Copilot."
  type        = string
}

variable "region" {
  description = "Sovereign GCP deployment region (defaults to UK FSI europe-west2)."
  type        = string
  default     = "europe-west2"
}

variable "environment" {
  description = "Deployment environment label (dev, staging, prod)."
  type        = string
  default     = "dev"
}

variable "container_image" {
  description = "Container image URI for the KYC Copilot Cloud Run / A2A service."
  type        = string
  default     = "europe-west2-docker.pkg.dev/example-project/kyc-copilot/arthashastra-kyc:latest"
}

variable "cloud_sql_tier" {
  description = "Cloud SQL machine tier for the Smriti Digital Twin PostgreSQL store."
  type        = string
  default     = "db-f1-micro"
}
