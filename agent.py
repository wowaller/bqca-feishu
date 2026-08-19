import os
import threading
import google.auth
from google.auth import impersonated_credentials
from google.cloud import geminidataanalytics
import config

class BqcaAgentBridge:
    """
    Bridge class to interact with the Google Cloud BigQuery Conversational Analytics (BQCA) service.
    Supports dynamic Service Account Impersonation per user/role, connection pooling, and stream parsing.
    """
    def __init__(self):
        # Base credentials of the runtime host / Cloud Run container
        self.base_credentials, _ = google.auth.default()
        
        # Client cache keyed by target_sa email (thread-safe)
        self._client_cache = {}
        self._lock = threading.Lock()
        
        self.parent_path = f"projects/{config.GCP_PROJECT}/locations/{config.GCP_LOCATION}"
        print(f"BQCA Bridge initialized for project: {config.GCP_PROJECT}, location: {config.GCP_LOCATION}")

    def get_chat_client(self, target_sa: str = None) -> geminidataanalytics.DataChatServiceClient:
        """
        Retrieves or creates a DataChatServiceClient impersonating the target Service Account.
        If target_sa is None, uses base credentials directly.
        """
        target_sa = target_sa or config.load_user_mapping().get("default_target_sa")

        with self._lock:
            if target_sa in self._client_cache:
                return self._client_cache[target_sa]

            if target_sa:
                print(f"Creating impersonated credentials for Target SA: {target_sa}")
                target_creds = impersonated_credentials.Credentials(
                    source_credentials=self.base_credentials,
                    target_principal=target_sa,
                    target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
                    lifetime=3600
                )
                client = geminidataanalytics.DataChatServiceClient(credentials=target_creds)
            else:
                print("Using default base credentials for BQCA chat client")
                client = geminidataanalytics.DataChatServiceClient(credentials=self.base_credentials)

            self._client_cache[target_sa] = client
            return client

    def get_or_create_conversation(
        self, 
        chat_client: geminidataanalytics.DataChatServiceClient, 
        conversation_id: str,
        agent_path: str
    ) -> str:
        """
        Ensures a conversation session exists in BQCA for the given conversation_id.
        Returns the conversation resource path.
        """
        conversation_path = chat_client.conversation_path(
            config.GCP_PROJECT, config.GCP_LOCATION, conversation_id
        )
        
        # Check if conversation already exists by trying to create it
        conversation = geminidataanalytics.Conversation(agents=[agent_path])
        try:
            chat_client.create_conversation(
                parent=self.parent_path,
                conversation_id=conversation_id,
                conversation=conversation
            )
            print(f"Created BQCA conversation session: {conversation_id}")
        except Exception as e:
            # If it already exists, reuse the session.
            print(f"Session '{conversation_id}' existing or re-used: {e}")
            
        return conversation_path

    def ask_agent(
        self, 
        conversation_id: str, 
        query: str, 
        target_sa: str = None, 
        agent_config_id: str = None
    ) -> dict:
        """
        Sends a user query to the BQCA agent under the impersonated target Service Account,
        processes the streaming response, and returns a structured dictionary.
        """
        target_sa = target_sa or config.load_user_mapping().get("default_target_sa")
        agent_id = agent_config_id or config.BQCA_CONFIG_ID

        try:
            # 1. Get impersonated chat client
            chat_client = self.get_chat_client(target_sa)
            agent_path = chat_client.data_agent_path(
                config.GCP_PROJECT, config.GCP_LOCATION, agent_id
            )

            # 2. Ensure the conversation session is active
            conversation_path = self.get_or_create_conversation(chat_client, conversation_id, agent_path)
            
            # 3. Build the chat request
            messages = [
                geminidataanalytics.Message(
                    user_message=geminidataanalytics.UserMessage(text=query)
                )
            ]
            
            data_agent_context = geminidataanalytics.DataAgentContext(
                data_agent=agent_path
            )
            
            chat_request = geminidataanalytics.ChatRequest(
                parent=conversation_path,
                messages=messages,
                data_agent_context=data_agent_context
            )
            
            # 4. Call the streaming chat API
            print(f"Sending query to BQCA agent '{agent_id}' as SA '{target_sa}': '{query}'")
            response_stream = chat_client.chat(request=chat_request)
            
            # 5. Parse the stream chunks
            accumulated_text = ""
            generated_sql = ""
            data_results = []
            follow_ups = []
            vega_config = None
            
            for chunk in response_stream:
                chunk_dict = geminidataanalytics.Message.to_dict(chunk)
                sys_msg = chunk_dict.get("system_message", {})
                
                # Check for Text Insights (text_type 1 is markdown body text, 2 is thinking/reasoning)
                text_block = sys_msg.get("text", {})
                if text_block:
                    parts = text_block.get("parts", [])
                    text_type = text_block.get("text_type")
                    
                    if text_type == 1:  # Core markdown response
                        accumulated_text += "\n".join(parts) + "\n"
                    elif text_type == 4:  # Suggested follow-up questions
                        follow_ups.extend(parts)
                
                # Check for SQL or Data Results
                data_block = sys_msg.get("data", {})
                if data_block:
                    sql = data_block.get("generated_sql")
                    if sql:
                        generated_sql = sql
                    
                    result = data_block.get("result", {})
                    if result:
                        rows = result.get("data", [])
                        if rows:
                            data_results.extend(rows)
                            
                # Check for Chart configuration
                chart_block = sys_msg.get("chart", {})
                if chart_block:
                    chart_res = chart_block.get("result", {})
                    if chart_res:
                        config_val = chart_res.get("vega_config", {})
                        if config_val:
                            vega_config = config_val
            
            # Clean up accumulated text spacing
            accumulated_text = accumulated_text.strip()
            
            return {
                "status": "success",
                "target_sa": target_sa,
                "text": accumulated_text,
                "sql": generated_sql.strip(),
                "data": data_results,
                "chart": vega_config,
                "follow_ups": follow_ups,
                "error": None
            }
            
        except Exception as e:
            print(f"Error communicating with BQCA agent as {target_sa}: {e}")
            return {
                "status": "error",
                "target_sa": target_sa,
                "text": None,
                "sql": None,
                "data": None,
                "chart": None,
                "follow_ups": [],
                "error": str(e)
            }

# Quick testing block
if __name__ == "__main__":
    import uuid
    bridge = BqcaAgentBridge()
    test_session = f"test-session-{uuid.uuid4().hex[:6]}"
    
    # Test high-privilege SA
    high_sa = "bqca-high-priv@binggang-lab.iam.gserviceaccount.com"
    res = bridge.ask_agent(test_session, "What are the top 5 countries by number of events?", target_sa=high_sa)
    print("\n--- BQCA BRIDGE TEST RESULT (HIGH PRIV) ---")
    print(f"Status: {res['status']}")
    print(f"Target SA: {res['target_sa']}")
    print(f"Text Insight:\n{res['text']}")
    print(f"SQL Used:\n{res['sql']}")
    print(f"Data Retrieved: {len(res['data'])} rows")
    if res['error']:
        print(f"Error: {res['error']}")
