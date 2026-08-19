import os
import json
from dotenv import load_dotenv

# Load local environment variables from .env file if present
load_dotenv()

# Feishu Credentials
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")

# Google Cloud Configurations
GCP_PROJECT = os.getenv("GCP_PROJECT", "")
GCP_LOCATION = os.getenv("GCP_LOCATION", "global")

# BQCA Configuration ID (This is the "Configuration ID" or "Agent ID" copied from the BigQuery Conversational Analytics UI)
BQCA_CONFIG_ID = os.getenv("BQCA_CONFIG_ID", "")

# Identity Mapping Configuration
USER_MAPPING_FILE = os.getenv("USER_MAPPING_FILE", os.path.join(os.path.dirname(__file__), "user_mapping.json"))

def load_user_mapping() -> dict:
    """
    Loads the user to service account mapping configuration from JSON file.
    """
    if not os.path.exists(USER_MAPPING_FILE):
        return {
            "unauthorized_action": "fallback",
            "default_target_sa": f"bqca-restricted@{GCP_PROJECT}.iam.gserviceaccount.com",
            "users": {},
            "roles": {}
        }
    try:
        with open(USER_MAPPING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: Failed to load {USER_MAPPING_FILE}: {e}")
        return {
            "unauthorized_action": "fallback",
            "default_target_sa": f"bqca-restricted@{GCP_PROJECT}.iam.gserviceaccount.com",
            "users": {},
            "roles": {}
        }

def resolve_user_sa(
    user_id: str = None, 
    open_id: str = None, 
    email: str = None, 
    name: str = None,
    group_ids: list[str] = None,
    department_ids: list[str] = None
) -> tuple[str | None, str, dict]:
    """
    Resolves the target GCP Service Account for a given Feishu user using RBAC hierarchy.
    Lookup order:
    1. Direct User Mapping (email, user_id, open_id, name)
    2. Feishu User Group Mapping (group_ids matched against 'groups' sorted by priority)
    3. Feishu Department Mapping (department_ids matched against 'departments')
    4. Fallback or Block based on 'unauthorized_action'

    Returns:
        (target_sa_email, status, user_metadata)
        status can be "mapped", "group_mapped", "dept_mapped", "fallback", or "unauthorized"
    """
    mapping = load_user_mapping()
    users = mapping.get("users", {})
    groups = mapping.get("groups", {})
    departments = mapping.get("departments", {})
    unauthorized_action = mapping.get("unauthorized_action", "fallback")
    default_sa = mapping.get("default_target_sa", f"bqca-restricted@{GCP_PROJECT}.iam.gserviceaccount.com")

    # 1. Direct User Match (email, user_id, open_id, name)
    key_candidates = []
    if email:
        key_candidates.extend([email.strip().lower(), email.strip()])
    if user_id:
        key_candidates.append(user_id.strip())
    if open_id:
        key_candidates.append(open_id.strip())
    if name:
        key_candidates.extend([name.strip().lower(), name.strip()])

    for candidate in key_candidates:
        if candidate in users:
            user_info = users[candidate]
            return user_info.get("target_sa"), "mapped", user_info
        for k, v in users.items():
            if k.lower() == candidate.lower():
                return v.get("target_sa"), "mapped", v

    # 2. Feishu User Group Match (via contact:group:readonly)
    if group_ids and groups:
        matched_groups = []
        for gid in group_ids:
            if gid in groups:
                g_info = groups[gid]
                priority = g_info.get("priority", 0)
                matched_groups.append((priority, g_info))
        if matched_groups:
            # Sort by highest priority
            matched_groups.sort(key=lambda x: x[0], reverse=True)
            best_group = matched_groups[0][1]
            return best_group.get("target_sa"), "group_mapped", best_group

    # 3. Feishu Department Match
    if department_ids and departments:
        for did in department_ids:
            if did in departments:
                dept_info = departments[did]
                return dept_info.get("target_sa"), "dept_mapped", dept_info

    # 4. Handle unmapped user
    if unauthorized_action == "block":
        return None, "unauthorized", {}
    
    # Default fallback
    return default_sa, "fallback", {"name": name or "Default Restricted Access", "target_sa": default_sa}
