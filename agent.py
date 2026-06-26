import os
import pandas as pd
from google.cloud import geminidataanalytics
import config

class BqcaAgentBridge:
    """
    Bridge class to interact with the existing Google Cloud BigQuery Conversational Analytics (BQCA) service.
    Acts as an API client that manages conversations and parses BQCA streams.
    """
    def __init__(self):
        # Initialize the DataChatServiceClient
        self.chat_client = geminidataanalytics.DataChatServiceClient()
        
        # Build the resource paths
        self.agent_path = self.chat_client.data_agent_path(
            config.GCP_PROJECT, config.GCP_LOCATION, config.BQCA_CONFIG_ID
        )
        self.parent_path = f"projects/{config.GCP_PROJECT}/locations/{config.GCP_LOCATION}"
        
        print(f"BQCA Bridge initialized with Agent: {self.agent_path}")

    def get_or_create_conversation(self, conversation_id: str) -> str:
        """
        Ensures a conversation session exists in BQCA for the given conversation_id.
        Returns the conversation resource path.
        """
        conversation_path = self.chat_client.conversation_path(
            config.GCP_PROJECT, config.GCP_LOCATION, conversation_id
        )
        
        # Check if conversation already exists by trying to create it
        # BQCA manages the state; if it exists, it returns a 400 or 409.
        conversation = geminidataanalytics.Conversation(agents=[self.agent_path])
        try:
            print(f"Creating BQCA conversation session: {conversation_id}")
            self.chat_client.create_conversation(
                parent=self.parent_path,
                conversation_id=conversation_id,
                conversation=conversation
            )
            print(f"Successfully created BQCA session: {conversation_id}")
        except Exception as e:
            # If it already exists, we can safely ignore the error and reuse the session.
            print(f"Session '{conversation_id}' already exists or was initialized: {e}")
            
        return conversation_path

    def ask_agent(self, conversation_id: str, query: str) -> dict:
        """
        Sends a user query to the BQCA agent, processes the streaming response,
        and returns a structured dictionary of insights, tables, SQL, and follow-ups.
        """
        try:
            # 1. Ensure the conversation session is active
            conversation_path = self.get_or_create_conversation(conversation_id)
            
            # 2. Build the chat request
            messages = [
                geminidataanalytics.Message(
                    user_message=geminidataanalytics.UserMessage(text=query)
                )
            ]
            
            data_agent_context = geminidataanalytics.DataAgentContext(
                data_agent=self.agent_path
            )
            
            chat_request = geminidataanalytics.ChatRequest(
                parent=conversation_path,
                messages=messages,
                data_agent_context=data_agent_context
            )
            
            # 3. Call the streaming chat API
            print(f"Sending query to BQCA agent: '{query}'")
            response_stream = self.chat_client.chat(request=chat_request)
            
            # 4. Parse the stream chunks
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
                    # Capture generated SQL
                    sql = data_block.get("generated_sql")
                    if sql:
                        generated_sql = sql
                    
                    # Capture query result rows
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
                "text": accumulated_text,
                "sql": generated_sql.strip(),
                "data": data_results,
                "chart": vega_config,
                "follow_ups": follow_ups,
                "error": None
            }
            
        except Exception as e:
            print(f"Error communicating with BQCA agent: {e}")
            return {
                "status": "error",
                "text": None,
                "sql": None,
                "data": None,
                "follow_ups": [],
                "error": str(e)
            }

# Quick testing block
if __name__ == "__main__":
    import uuid
    bridge = BqcaAgentBridge()
    test_session = f"test-session-{uuid.uuid4().hex[:6]}"
    
    # Test a sample query
    res = bridge.ask_agent(test_session, "What is the total sales price in November 1999?")
    print("\n--- BQCA BRIDGE TEST RESULT ---")
    print(f"Status: {res['status']}")
    print(f"Text Insight:\n{res['text']}")
    print(f"SQL Used:\n{res['sql']}")
    print(f"Data Retrieved: {len(res['data'])} rows")
    if res['data']:
        print(res['data'][:2])
    print(f"Suggested Follow-ups: {res['follow_ups']}")
    if res['error']:
        print(f"Error: {res['error']}")
