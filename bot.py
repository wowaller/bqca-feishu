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

def clean_user_query(text: str) -> str:
    """
    Cleans the user query by removing Feishu-specific @-mentions and leading/trailing spaces.
    E.g., "<at id=\"ou_12345\">@BotName</at> Hello" -> "Hello"
    """
    # Remove XML-like at tags used by Feishu: <at id="ou_xxx">@name</at>
    cleaned = re.sub(r"<at[^>]*>[^<]*</at>", "", text)
    # Remove plain text @mentions if any
    cleaned = re.sub(r"^\s*@[^\s]+", "", cleaned)
    return cleaned.strip()

def build_interactive_card(query: str, res: dict, image_key: str = None) -> str:
    """
    Builds a Feishu Interactive Message Card JSON (Schema 2.0) based on the BQCA response.
    Includes support for displaying rendered visualization charts.
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
    if data_rows:
        # Build columns dynamically from the first row keys
        sample_row = data_rows[0]
        columns = []
        for col_name in sample_row.keys():
            columns.append({
                "name": col_name,
                "display_name": col_name.replace("_", " ").title(),
                "data_type": "text" # use text as default for clean rendering
            })
            
        # Format row values as strings for text rendering, limit to top 10
        formatted_rows = []
        for row in data_rows[:10]:
            formatted_row = {}
            for k, v in row.items():
                # Nice number formatting
                if isinstance(v, float):
                    formatted_row[k] = f"{v:,.2f}"
                elif isinstance(v, (int, float)):
                    formatted_row[k] = f"{v:,}"
                else:
                    formatted_row[k] = str(v)
            formatted_rows.append(formatted_row)
            
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
        
        # If there are more than 10 rows, add a subtle note
        if len(data_rows) > 10:
            elements.append({
                "tag": "markdown",
                "content": f"*Note: Showing top 10 of {len(data_rows)} total rows.*"
            })
            
        elements.append({
            "tag": "hr"
        })
        
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

def process_message_async(message_id: str, chat_id: str, query: str) -> None:
    """
    Runs the BQCA query, chart rendering, and card sending inside a background thread.
    This prevents Feishu from replaying/retrying the event due to HTTP timeout.
    """
    try:
        # 4. Call BQCA agent to get insights
        # We use chat_id as the BQCA conversation_id to keep conversational state per Feishu chat!
        res = bqca_bridge.ask_agent(conversation_id=chat_id, query=query)
        
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
        card_content = build_interactive_card(query, res, image_key=image_key)
        
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
            print(f"Failed to reply. Code: {response.code}, Msg: {response.msg}")
    except Exception as async_err:
        print(f"Exception in async processing thread: {async_err}")

def handle_message(data: P2ImMessageReceiveV1) -> None:
    """
    Main event handler triggered when the bot receives a message in Feishu.
    Averages less than 1ms execution time by offloading to a background thread,
    preventing Feishu event delivery timeouts and duplicates.
    """
    # 1. Ignore messages from other bots to prevent loops
    sender_type = data.event.sender.sender_type
    if sender_type != "user":
        return
        
    # 2. Extract message metadata
    message_id = data.event.message.message_id
    chat_id = data.event.message.chat_id
    
    # 2.5. Check if this is a stale/replayed event (older than 5 minutes)
    # Prevents processing historical retries from previous server sessions/crashes
    import time
    try:
        create_time_ms = int(data.header.create_time)
        current_time_ms = int(time.time() * 1000)
        age_seconds = (current_time_ms - create_time_ms) / 1000
        
        # If the event is older than 5 minutes (300 seconds), discard it
        if age_seconds > 300:
            print(f"Discarding stale/replayed event {message_id} (age: {age_seconds:.1f}s, created at: {create_time_ms})")
            return
    except Exception as ts_err:
        print(f"Warning: Could not verify event timestamp age: {ts_err}")
    
    # Parse the message content
    try:
        content_dict = json.loads(data.event.message.content)
        raw_query = content_dict.get("text", "")
    except Exception as e:
        print(f"Error parsing message content: {e}")
        return
        
    # 3. Clean the user query (remove @mentions, spaces)
    query = clean_user_query(raw_query)
    if not query:
        print("Empty query after cleaning. Ignoring.")
        return
        
    print(f"Received query from chat '{chat_id}': '{query}'")
    print(f"Acknowledging event and spawning background thread for query processing...")
    
    # Spawn background worker thread
    threading.Thread(
        target=process_message_async,
        args=(message_id, chat_id, query),
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
