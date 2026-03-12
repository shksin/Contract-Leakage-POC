"""Application configuration using Pydantic Settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Azure AI Foundry
    azure_ai_project_connection_string: str = ""
    azure_ai_model_deployment: str = "gpt-4o"

    # SharePoint
    sharepoint_site_url: str = "https://contoso.sharepoint.com/sites/contracts"
    sharepoint_contracts_library: str = "Contracts"
    sharepoint_mock_mode: bool = True

    # GCP BigQuery
    gcp_project_id: str = "orica-finance"
    gcp_dataset_id: str = "finance_data"
    gcp_credentials_path: str = ""
    bigquery_mock_mode: bool = True

    # Application
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"


settings = Settings()
