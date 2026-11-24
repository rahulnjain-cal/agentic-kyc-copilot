output "kyc_service_account_email" {
  description = "Least-privilege IAM service account email for the KYC Copilot runtime."
  value       = google_service_account.sutradhar_runtime_sa.email
}

output "a2a_cloud_run_url" {
  description = "HTTPS endpoint for the A2A KYC Copilot & cKYC webhook service."
  value       = google_cloud_run_v2_service.sutradhar_a2a_service.uri
}

output "smriti_cloud_sql_connection_name" {
  description = "Cloud SQL PostgreSQL connection name for Smriti Digital Twin storage."
  value       = google_sql_database_instance.smriti_digital_twin_db.connection_name
}

output "ckyc_bigquery_dataset_id" {
  description = "BigQuery dataset ID for 90-day transactions and cKYC monitoring signals."
  value       = google_bigquery_dataset.ckyc_analytics_dataset.dataset_id
}

output "mudra_secret_ids" {
  description = "Secret Manager resource IDs provisioned for zero-hardcoded-key injection."
  value = {
    gemini_api_key         = google_secret_manager_secret.mudra_gemini_api_key.secret_id
    registry_mcp_token     = google_secret_manager_secret.mudra_registry_mcp_token.secret_id
    checker_approval_token = google_secret_manager_secret.mudra_checker_approval_key.secret_id
  }
}
