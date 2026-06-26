import os

# Feishu Credentials
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")

# Google Cloud Configurations
# Specify your GCP Project ID
GCP_PROJECT = os.getenv("GCP_PROJECT", "")
GCP_LOCATION = os.getenv("GCP_LOCATION", "global")

# BQCA Configuration ID (This is the "Configuration ID" or "Agent ID" copied from the BigQuery Conversational Analytics UI)
BQCA_CONFIG_ID = os.getenv("BQCA_CONFIG_ID", "")
