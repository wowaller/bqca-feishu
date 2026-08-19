import os
import json
import re
import threading
import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1, ReplyMessageRequest, ReplyMessageRequestBody
from agent import BqcaAgentBridge
import config

from chart_renderer import render_vega_to_png

# Initialize BQCA Bridge
bqca_bridge = BqcaAgentBridge()

def upload_image_sdk(file_path: str) -> str:
    """
    Uploads a local image file to Feishu and returns the image_key.
    Uses the official SDK-native Client to handle authentication automatically.
    """
    if not file_path or not os.path.exists(file_path):
        print(f"File not found for upload: {file_path}")
        return None
        
    try:
        with open(file_path, "rb") as f:
            request_body = lark.api.im.v1.CreateImageRequestBody.builder() \
                .image_type("message") \
                .image(f) \
                .build()
                
            request = lark.api.im.v1.CreateImageRequest.builder() \
                .request_body(request_body) \
                .build()
                
            response = lark_client.im.v1.image.create(request)
            
            if response.success():
                image_key = response.data.image_key
                print(f"Successfully uploaded image to Feishu, key: {image_key}")
                return image_key
            else:
                print(f"Failed to upload image to Feishu: {response.code} - {response.msg}")
                return None
    except Exception as e:
        print(f"Exception during Feishu image upload: {e}")
        return None

# Initialize Lark REST Client for replying to messages
lark_client = lark.Client.builder() \
    .app_id(config.FEISHU_APP_ID) \
    .app_secret(config.FEISHU_APP_SECRET) \
    .build()

# In-memory cache for Feishu user profiles (open_id -> profile dict)
_user_profile_cache = {}

def get_feishu_user_profile(open_id: str, chat_id: str = None) -> dict:
    """
    Fetches user profile (name, email, enterprise user_id) from Feishu.
    Uses Contact API first, and automatically falls back to IM Chat Member API
    so display names are always discovered even without extra enterprise contact scopes.
    """
    if not open_id:
        return {}
    if open_id in _user_profile_cache and _user_profile_cache[open_id].get("name"):
        return _user_profile_cache[open_id]
        
    profile = {
        "name": "",
        "email": "",
        "user_id": "",
        "department_ids": []
    }

    # 1. Try Contact API (requires contact:contact.base:readonly or contact:contact:readonly_as_app)
    try:
        from lark_oapi.api.contact.v3 import GetUserRequest
        req = GetUserRequest.builder().user_id(open_id).user_id_type("open_id").build()
        resp = lark_client.contact.v3.user.get(req)
        if resp.success() and resp.data and resp.data.user:
            u = resp.data.user
            profile["name"] = u.name or ""
            profile["email"] = u.email or ""
            profile["user_id"] = u.user_id or ""
            profile["department_ids"] = u.department_ids or []
            print(f"Fetched Contact profile for {open_id}: Name='{u.name}', Email='{u.email}'")
    except Exception as e:
        print(f"Note: Contact API query for {open_id}: {e}")

    # 2. If name is not yet found and chat_id is provided, resolve from IM Chat Members API
    if not profile["name"] and chat_id:
        try:
            from lark_oapi.api.im.v1 import GetChatMembersRequest
            req = GetChatMembersRequest.builder().chat_id(chat_id).member_id_type("open_id").build()
            resp = lark_client.im.v1.chat_members.get(req)
            if resp.success() and resp.data and resp.data.items:
                for item in resp.data.items:
                    if item.member_id == open_id and item.name:
                        profile["name"] = item.name
                        print(f"Discovered user display name via IM API for {open_id}: '{item.name}'")
                        break
        except Exception as e:
            print(f"Note: IM Chat Members API query for {open_id}: {e}")

    _user_profile_cache[open_id] = profile
    return profile

# In-memory cache for Feishu user groups (open_id -> list of group_ids)
_user_groups_cache = {}

def get_feishu_user_groups(open_id: str) -> list[str]:
    """
    Queries Feishu Contact API to get the user group IDs the user belongs to.
    Requires scope: contact:group:readonly or contact:group
    """
    if not open_id:
        return []
    if open_id in _user_groups_cache:
        return _user_groups_cache[open_id]
        
    try:
        from lark_oapi.api.contact.v3 import MemberBelongGroupRequest
        req = MemberBelongGroupRequest.builder() \
            .member_id(open_id) \
            .member_id_type("open_id") \
            .build()
        resp = lark_client.contact.v3.group.member_belong(req)
        if resp.success() and resp.data and resp.data.group_list:
            group_ids = [g for g in resp.data.group_list if g]
            _user_groups_cache[open_id] = group_ids
            print(f"Fetched Feishu User Groups for {open_id}: {group_ids}")
            return group_ids
        else:
            _user_groups_cache[open_id] = []
            return []
    except Exception as e:
        print(f"Note: Could not query Feishu User Groups for {open_id}: {e}")
        _user_groups_cache[open_id] = []
        return []

def extract_text_from_feishu_content(content_str: str) -> str:
    """
    Robustly extracts plain text from Feishu message content JSON across both 'text' and 'post' (rich-text) formats.
    """
    if not content_str:
        return ""
    try:
        data = json.loads(content_str)
    except Exception as e:
        print(f"Warning: Failed to parse content JSON: {e}")
        return content_str

    # 1. Standard text message format: {"text": "..."}
    if isinstance(data, dict) and "text" in data and isinstance(data["text"], str):
        return data["text"]

    # 2. Rich text 'post' format: {"title": "...", "content": [[{"tag": "text", "text": "..."}]]}
    extracted_texts = []
    if isinstance(data, dict):
        if data.get("title"):
            extracted_texts.append(str(data["title"]))

        def recurse_elements(obj):
            if isinstance(obj, dict):
                if obj.get("tag") in ("text", "a") and "text" in obj:
                    extracted_texts.append(str(obj["text"]))
                for v in obj.values():
                    recurse_elements(v)
            elif isinstance(obj, list):
                for item in obj:
                    recurse_elements(item)

        if "content" in data:
            recurse_elements(data["content"])
        elif "content_v2" in data:
            recurse_elements(data["content_v2"])

    return " ".join(extracted_texts).strip()

def clean_user_query(text: str) -> str:
    """
    Cleans the user query by removing Feishu-specific @-mentions, surrounding quotes, and leading/trailing spaces.
    E.g., "<at id=\"ou_12345\">@BotName</at> Hello" -> "Hello"
    """
    # Remove XML-like at tags used by Feishu: <at id="ou_xxx">@name</at>
    cleaned = re.sub(r"<at[^>]*>[^<]*</at>", "", text)
    # Remove plain text @mentions if any
    cleaned = re.sub(r"^\s*@[^\s]+", "", cleaned)
    cleaned = cleaned.strip()
    
    # Strip surrounding quotes if copied directly from prompt templates
    if (cleaned.startswith('"') and cleaned.endswith('"')) or \
       (cleaned.startswith('“') and cleaned.endswith('”')) or \
       (cleaned.startswith("'") and cleaned.endswith("'")):
        cleaned = cleaned[1:-1].strip()
        
    return cleaned

def build_unauthorized_card(query: str, user_id: str, open_id: str) -> str:
    """
    Builds an Access Denied card (Orange/Red template) when an unmapped user is blocked.
    """
    card = {
        "schema": "2.0",
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "🔒 Access Denied / 访问受限"
            },
            "template": "orange"
        },
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": f"**Question:** {query}\n\n"
                               f"Your Feishu account (`user_id`: `{user_id or 'N/A'}`, `open_id`: `{open_id or 'N/A'}`) "
                               f"is not mapped to an authorized BigQuery Service Account.\n\n"
                               f"Please contact your GCP Data Administrator to request access in `user_mapping.json`."
                }
            ]
        }
    }
    return json.dumps(card)

def build_interactive_card(query: str, res: dict, image_key: str = None, user_info: dict = None) -> str:
    """
    Builds a Feishu Interactive Message Card JSON (Schema 2.0) based on the BQCA response.
    Includes support for displaying rendered visualization charts and identity badge.
    """
    if res["status"] == "error":
        # Return an error card (Red template)
        card = {
            "schema": "2.0",
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": "BQCA Query Error"
                },
                "template": "red"
            },
            "body": {
                "elements": [
                    {
                        "tag": "markdown",
                        "content": f"**Original Question:** {query}\n\n**An error occurred while processing your request:**\n```\n{res['error']}\n```"
                    }
                ]
            }
        }
        return json.dumps(card)

    # Build success card (Blue template)
    elements = []
    
    # 0. Role/Identity badge
    target_sa = res.get("target_sa", "")
    role_name = user_info.get("name") if user_info else "Authorized User"
    if target_sa:
        elements.append({
            "tag": "markdown",
            "content": f"🛡️ **Role Context:** `{role_name}` (`{target_sa.split('@')[0]}`)"
        })
        elements.append({"tag": "hr"})

    # 1. Main Insights Text
    insights_text = res.get("text", "No text insights returned by the agent.")
    elements.append({
        "tag": "markdown",
        "content": f"**Original Question:** {query}\n\n**Insights:**\n{insights_text}"
    })
    
    # 2. Add Divider
    elements.append({
        "tag": "hr"
    })
    
    # 3. Data Table Component
    data_rows = res.get("data", [])
    if data_rows and isinstance(data_rows, list) and len(data_rows) > 0:
        try:
            # Collect all unique column names preserving order
            all_cols = []
            for row in data_rows[:10]:
                if isinstance(row, dict):
                    for k in row.keys():
                        if k not in all_cols:
                            all_cols.append(k)
            
            if all_cols:
                columns = [
                    {
                        "name": col_name,
                        "display_name": col_name.replace("_", " ").title(),
                        "data_type": "text"
                    }
                    for col_name in all_cols
                ]
                
                formatted_rows = []
                for row in data_rows[:10]:
                    if not isinstance(row, dict):
                        continue
                    formatted_row = {}
                    for col in all_cols:
                        v = row.get(col)
                        if v is None:
                            formatted_row[col] = "-"
                        elif isinstance(v, float):
                            formatted_row[col] = f"{v:,.2f}" if not v.is_integer() else f"{int(v):,}"
                        elif isinstance(v, int):
                            formatted_row[col] = f"{v:,}"
                        else:
                            formatted_row[col] = str(v)
                    formatted_rows.append(formatted_row)
                
                if formatted_rows:
                    elements.append({
                        "tag": "markdown",
                        "content": f"**Query Results (Top {len(formatted_rows)} rows):**"
                    })
                    elements.append({
                        "tag": "table",
                        "page_size": 5,
                        "columns": columns,
                        "rows": formatted_rows
                    })
                    if len(data_rows) > 10:
                        elements.append({
                            "tag": "markdown",
                            "content": f"*Note: Showing top 10 of {len(data_rows)} total rows.*"
                        })
                    elements.append({"tag": "hr"})
        except Exception as tbl_err:
            print(f"Warning: Failed to render table component, skipping: {tbl_err}")
        
    # 3.5. Add Rendered Chart Component if image_key is provided
    if image_key:
        elements.append({
            "tag": "img",
            "img_key": image_key,
            "alt": {
                "tag": "plain_text",
                "content": "Data Visualization Chart"
            },
            "title": {
                "tag": "plain_text",
                "content": "📊 Data Visualization"
            },
            "mode": "fit_width",
            "preview": True
        })
        elements.append({
            "tag": "hr"
        })
        
    # 4. Collapsible SQL Panel
    sql_query = res.get("sql", "")
    if sql_query:
        elements.append({
            "tag": "collapsible_panel",
            "expanded": False,
            "header": {
                "title": {
                    "tag": "markdown",
                    "content": "**🔍 View Generated SQL**"
                }
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": f"```sql\n{sql_query}\n```"
                }
            ]
        })
        
    # 5. Suggested Follow-up Questions
    follow_ups = res.get("follow_ups", [])
    if follow_ups:
        follow_ups_markdown = "**💡 Suggested Follow-up Questions:**\n"
        for q in follow_ups:
            follow_ups_markdown += f"* {q}\n"
            
        elements.append({
            "tag": "hr"
        })
        elements.append({
            "tag": "markdown",
            "content": follow_ups_markdown
        })
        
    card = {
        "schema": "2.0",
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "BigQuery Conversational Insights"
            },
            "template": "blue"
        },
        "body": {
            "elements": elements
        }
    }
    
    return json.dumps(card)

def process_message_async(message_id: str, chat_id: str, query: str, target_sa: str, user_info: dict) -> None:
    """
    Runs the BQCA query under the impersonated target SA, chart rendering, and card sending inside a background thread.
    This prevents Feishu from replaying/retrying the event due to HTTP timeout.
    """
    try:
        # 4. Call BQCA agent under the impersonated Service Account
        print(f"Processing query under Target SA: {target_sa} for chat: {chat_id}")
        res = bqca_bridge.ask_agent(conversation_id=chat_id, query=query, target_sa=target_sa)
        
        # 4.5. Render and Upload Chart if returned by BQCA
        image_key = None
        if res["status"] == "success" and res.get("chart"):
            try:
                print("BQCA returned a chart configuration. Rendering to image...")
                chart_file = render_vega_to_png(res["chart"], fallback_data=res.get("data"))
                
                print("Uploading rendered chart to Feishu...")
                image_key = upload_image_sdk(chart_file)
                
                # Clean up the local temporary chart file
                if chart_file and os.path.exists(chart_file):
                    os.remove(chart_file)
                    print("Temporary chart file cleaned up successfully.")
            except Exception as chart_err:
                print(f"Error rendering/uploading chart: {chart_err}")
        
        # 5. Build the interactive card JSON
        card_content = build_interactive_card(query, res, image_key=image_key, user_info=user_info)
        
        # 6. Send the reply back to the Feishu user/group
        request = ReplyMessageRequest.builder() \
            .message_id(message_id) \
            .request_body(ReplyMessageRequestBody.builder()
                          .content(card_content)
                          .msg_type("interactive")
                          .build()) \
            .build()
            
        response = lark_client.im.v1.message.reply(request)
        
        if response.success():
            print(f"Successfully sent insights card reply to message {message_id}")
        else:
            print(f"Failed to reply with interactive card. Code: {response.code}, Msg: {response.msg}")
            print("Attempting fallback reply with plain text...")
            try:
                fallback_text = f"💡 **Insights:**\n\n{res.get('text', 'No text returned.')}"
                if res.get('sql'):
                    fallback_text += f"\n\n**Generated SQL:**\n```sql\n{res['sql']}\n```"
                fallback_req = ReplyMessageRequest.builder() \
                    .message_id(message_id) \
                    .request_body(ReplyMessageRequestBody.builder()
                                  .content(json.dumps({"text": fallback_text}))
                                  .msg_type("text")
                                  .build()) \
                    .build()
                fallback_res = lark_client.im.v1.message.reply(fallback_req)
                if fallback_res.success():
                    print(f"Successfully sent fallback text reply to message {message_id}")
                else:
                    print(f"Fallback reply also failed: {fallback_res.code} - {fallback_res.msg}")
            except Exception as fb_err:
                print(f"Error sending fallback message: {fb_err}")
    except Exception as async_err:
        print(f"Exception in async processing thread: {async_err}")

def handle_message(data: P2ImMessageReceiveV1) -> None:
    """
    Main event handler triggered when the bot receives a message in Feishu.
    Resolves user identity to target Service Account and offloads to async background worker.
    """
    # 1. Ignore messages from other bots to prevent loops
    sender_type = data.event.sender.sender_type
    if sender_type != "user":
        return
        
    # 2. Extract message and user metadata
    message_id = data.event.message.message_id
    chat_id = data.event.message.chat_id
    
    sender_id_obj = getattr(data.event.sender, "sender_id", None)
    user_id = getattr(sender_id_obj, "user_id", None) if sender_id_obj else None
    open_id = getattr(sender_id_obj, "open_id", None) if sender_id_obj else None
    
    # 2.5. Check if this is a stale/replayed event (older than 5 minutes)
    import time
    try:
        create_time_ms = int(data.header.create_time)
        current_time_ms = int(time.time() * 1000)
        age_seconds = (current_time_ms - create_time_ms) / 1000
        
        if age_seconds > 300:
            print(f"Discarding stale/replayed event {message_id} (age: {age_seconds:.1f}s)")
            return
    except Exception as ts_err:
        print(f"Warning: Could not verify event timestamp age: {ts_err}")
    
    # Parse the message content (handles both standard 'text' and rich-text 'post')
    try:
        raw_query = extract_text_from_feishu_content(data.event.message.content)
    except Exception as e:
        print(f"Error parsing message content: {e}")
        return
        
    # 3. Clean the user query (remove @mentions, quotes, spaces)
    query = clean_user_query(raw_query)
    if not query:
        print(f"Empty query after cleaning (raw was: '{raw_query}'). Ignoring.")
        return
        
    # 4. Fetch User Profile and User Groups from Feishu Contact/IM API
    profile = get_feishu_user_profile(open_id, chat_id=chat_id) if open_id else {}
    email = profile.get("email")
    name = profile.get("name")
    if not user_id and profile.get("user_id"):
        user_id = profile.get("user_id")
    department_ids = profile.get("department_ids", [])
    group_ids = get_feishu_user_groups(open_id) if open_id else []

    # 4.1. Resolve Identity Mapping (Feishu user/group/dept -> Target SA)
    target_sa, auth_status, user_info = config.resolve_user_sa(
        user_id=user_id, 
        open_id=open_id, 
        email=email, 
        name=name,
        group_ids=group_ids,
        department_ids=department_ids
    )
    print(f"Received query from chat '{chat_id}' | name: '{name}', email: '{email}', groups: {group_ids} -> Target SA: {target_sa} (Status: {auth_status})")

    # 4.1. Handle unauthorized user if strict blocking is enabled
    if auth_status == "unauthorized" or not target_sa:
        print(f"Blocking unauthorized user: user_id={user_id}, open_id={open_id}")
        unauth_card = build_unauthorized_card(query, user_id=user_id, open_id=open_id)
        
        def reply_blocked():
            req = ReplyMessageRequest.builder() \
                .message_id(message_id) \
                .request_body(ReplyMessageRequestBody.builder()
                              .content(unauth_card)
                              .msg_type("interactive")
                              .build()) \
                .build()
            lark_client.im.v1.message.reply(req)

        threading.Thread(target=reply_blocked, daemon=True).start()
        return

    # 5. Spawn background worker thread with resolved SA credentials
    threading.Thread(
        target=process_message_async,
        args=(message_id, chat_id, query, target_sa, user_info),
        daemon=True
    ).start()
    
    # Return immediately (None) to send prompt ACK to Feishu
    return

def run_dummy_health_check_server():
    """
    Starts a lightweight HTTP server on the port specified by the PORT environment variable
    (defaulting to 8080) to satisfy Cloud Run's startup and health check probes.
    This runs in a background thread to avoid blocking the main WebSocket client.
    """
    import http.server
    port = int(os.environ.get("PORT", 8080))
    
    class HealthCheckHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            # Return HTTP 200 OK for any GET request to satisfy the probe
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
            
        def log_message(self, format, *args):
            # Suppress logging to keep container logs clean
            pass

    try:
        server = http.server.HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        print(f"Starting dummy health check HTTP server on port {port}...")
        server.serve_forever()
    except Exception as e:
        print(f"Warning: Failed to start dummy health check server: {e}")

def main():
    # 0. Start the dummy health check server in a background daemon thread.
    # This is critical to prevent Cloud Run from failing the container startup probe!
    threading.Thread(target=run_dummy_health_check_server, daemon=True).start()

    # Verify that app credentials are set
    if not config.FEISHU_APP_ID or not config.FEISHU_APP_SECRET:
        print("CRITICAL ERROR: FEISHU_APP_ID and FEISHU_APP_SECRET must be set as environment variables!")
        return

    # Build the event handler
    event_handler = lark.EventDispatcherHandler.builder("", "") \
        .register_p2_im_message_receive_v1(handle_message) \
        .build()
        
    # Build the WebSocket Client
    ws_client = lark.ws.Client(
        app_id=config.FEISHU_APP_ID,
        app_secret=config.FEISHU_APP_SECRET,
        event_handler=event_handler,
        log_level=lark.LogLevel.DEBUG
    )
    
    print("Starting Feishu WebSocket Bot Listener...")
    print("This connection will run continuously to receive chat events. Press Ctrl+C to exit.")
    
    # Start the event loop (blocking)
    ws_client.start()

if __name__ == "__main__":
    main()
