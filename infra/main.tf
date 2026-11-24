terraform {
  required_version = ">= 1.6.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ------------------------------------------------------------------------------
# Enable Required Sovereign GCP APIs (Vertex AI, Run, Secret Manager, DLP, Trace)
# ------------------------------------------------------------------------------
locals {
  required_apis = [
    "aiplatform.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "sqladmin.googleapis.com",
    "bigquery.googleapis.com",
    "cloudtrace.googleapis.com",
    "dlp.googleapis.com",
    "discoveryengine.googleapis.com",
  ]
}

resource "google_project_service" "enabled_services" {
  for_each           = toset(local.required_apis)
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# ------------------------------------------------------------------------------
# Least-Privilege IAM Service Account (Sutradhar Runtime Identity)
# ------------------------------------------------------------------------------
resource "google_service_account" "sutradhar_runtime_sa" {
  account_id   = "sutradhar-kyc-copilot-${var.environment}"
  display_name = "Arthashastra KYC Copilot Least-Privilege Runtime SA"
}

locals {
  runtime_iam_roles = [
    "roles/aiplatform.user",
    "roles/secretmanager.secretAccessor",
    "roles/cloudsql.client",
    "roles/bigquery.dataEditor",
    "roles/cloudtrace.agent",
    "roles/dlp.user",
    "roles/discoveryengine.viewer",
  ]
}

resource "google_project_iam_member" "sutradhar_runtime_roles" {
  for_each = toset(local.runtime_iam_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.sutradhar_runtime_sa.email}"
}

# ------------------------------------------------------------------------------
# Mudra Secret Manager Resources (Zero Hardcoded Keys)
# ------------------------------------------------------------------------------
resource "google_secret_manager_secret" "mudra_gemini_api_key" {
  secret_id = "kyc-copilot-gemini-api-key"
  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }
  depends_on = [google_project_service.enabled_services]
}

resource "google_secret_manager_secret" "mudra_registry_mcp_token" {
  secret_id = "kyc-copilot-registry-mcp-token"
  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }
  depends_on = [google_project_service.enabled_services]
}

resource "google_secret_manager_secret" "mudra_checker_approval_key" {
  secret_id = "kyc-copilot-checker-approval-key"
  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }
  depends_on = [google_project_service.enabled_services]
}

# ------------------------------------------------------------------------------
# Smriti Persistent Digital Twin Database (Cloud SQL PostgreSQL)
# ------------------------------------------------------------------------------
resource "google_sql_database_instance" "smriti_digital_twin_db" {
  name                = "smriti-kyc-digital-twin-${var.environment}"
  database_version    = "POSTGRES_16"
  region              = var.region
  deletion_protection = true

  settings {
    tier = var.cloud_sql_tier

    backup_configuration {
      enabled = true
    }

    ip_configuration {
      ipv4_enabled = true
    }
  }

  depends_on = [google_project_service.enabled_services]
}

resource "google_sql_database" "smriti_schema_db" {
  name     = "smriti_kyc"
  instance = google_sql_database_instance.smriti_digital_twin_db.name
}

# ------------------------------------------------------------------------------
# Perpetual KYC (cKYC) & 90-Day Transaction Analytics (BigQuery)
# ------------------------------------------------------------------------------
resource "google_bigquery_dataset" "ckyc_analytics_dataset" {
  dataset_id  = "arthashastra_ckyc_${var.environment}"
  location    = var.region
  description = "90-day commercial banking transaction telemetry and cKYC materiality signals."

  depends_on = [google_project_service.enabled_services]
}

# ------------------------------------------------------------------------------
# Cloud Run v2 Service — A2A Endpoint & cKYC Webhook Runner
# ------------------------------------------------------------------------------
resource "google_cloud_run_v2_service" "sutradhar_a2a_service" {
  name     = "arthashastra-kyc-copilot-${var.environment}"
  location = var.region

  template {
    service_account = google_service_account.sutradhar_runtime_sa.email

    containers {
      image = var.container_image

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = var.region
      }
      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "true"
      }
      env {
        name  = "ENABLE_SECRET_MANAGER"
        value = "true"
      }
      env {
        name  = "ENABLE_CLOUD_DLP"
        value = "true"
      }
      env {
        name  = "ENABLE_CLOUD_TRACE"
        value = "true"
      }
      env {
        name  = "KYC_STORAGE_BACKEND"
        value = "gcp"
      }
      env {
        name  = "CLOUD_SQL_CONNECTION_NAME"
        value = google_sql_database_instance.smriti_digital_twin_db.connection_name
      }
    }
  }

  depends_on = [
    google_project_service.enabled_services,
    google_project_iam_member.sutradhar_runtime_roles,
  ]
}
