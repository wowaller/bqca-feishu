import os

# Feishu Credentials
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")

# Google Cloud Configurations
GCP_PROJECT = os.getenv("GCP_PROJECT", "binggang-lab")
GCP_LOCATION = os.getenv("GCP_LOCATION", "global")

# BQCA Configuration ID (This is the "Configuration ID" or "Agent ID" copied from the BigQuery Conversational Analytics UI)
# Default points to the TPC-DS Retail Insights Agent
BQCA_CONFIG_ID = os.getenv("BQCA_CONFIG_ID", "agent_43f5970c-5ca6-47b1-8871-11615bf9e88a")
