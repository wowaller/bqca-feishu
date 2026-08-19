import json
import config
from agent import BqcaAgentBridge
from bot import build_interactive_card, build_unauthorized_card

def run_tests():
    print("==================================================")
    print("1. Testing Configuration & Identity Mapping")
    print("==================================================")
    print(f"GCP_PROJECT: {config.GCP_PROJECT}")
    print(f"GCP_LOCATION: {config.GCP_LOCATION}")
    print(f"BQCA_CONFIG_ID: {config.BQCA_CONFIG_ID}")
    
    # Test high-priv user
    sa_high, status_high, info_high = config.resolve_user_sa(user_id="user_high_priv_001")
    print(f"\nUser: user_high_priv_001 -> SA: {sa_high} | Status: {status_high} | Name: {info_high.get('name')}")
    assert "bqca-high-priv" in sa_high
    assert status_high == "mapped"
    
    # Test restricted user
    sa_rest, status_rest, info_rest = config.resolve_user_sa(user_id="user_restricted_002")
    print(f"User: user_restricted_002 -> SA: {sa_rest} | Status: {status_rest} | Name: {info_rest.get('name')}")
    assert "bqca-restricted" in sa_rest
    assert status_rest == "mapped"
    
    # Test unmapped user (fallback mode)
    sa_unmapped, status_unmapped, _ = config.resolve_user_sa(user_id="unknown_user_999")
    print(f"User: unknown_user_999 -> SA: {sa_unmapped} | Status: {status_unmapped}")
    assert status_unmapped == "fallback"
    assert "bqca-restricted" in sa_unmapped
    
    print("\n==================================================")
    print("2. Testing BQCA Chat with Impersonated SAs")
    print("==================================================")
    bridge = BqcaAgentBridge()
    query = "What are the top 5 countries by number of events?"
    
    print("\n--- Executing as High-Privilege User ---")
    res_high = bridge.ask_agent(
        conversation_id="e2e-test-session-high-01",
        query=query,
        target_sa=sa_high
    )
    print(f"High-Priv Status: {res_high['status']}")
    print(f"Generated SQL: {res_high['sql']}")
    print(f"Data rows returned: {len(res_high['data'])}")
    for r in res_high['data']:
        print(f"  {r}")
    assert res_high["status"] == "success"
    assert len(res_high["data"]) > 1  # Multiple countries visible
    
    print("\n--- Executing as Restricted User ---")
    res_rest = bridge.ask_agent(
        conversation_id="e2e-test-session-restricted-01",
        query=query,
        target_sa=sa_rest
    )
    print(f"Restricted Status: {res_rest['status']}")
    print(f"Generated SQL: {res_rest['sql']}")
    print(f"Data rows returned: {len(res_rest['data'])}")
    for r in res_rest['data']:
        print(f"  {r}")
    assert res_rest["status"] == "success"
    assert len(res_rest["data"]) == 1  # Only US visible
    
    print("\n==================================================")
    print("3. Testing Feishu Interactive Card Assembly")
    print("==================================================")
    card_json = build_interactive_card(query, res_high, user_info=info_high)
    card_obj = json.loads(card_json)
    print(f"Generated Card Header: {card_obj['header']['title']['content']}")
    print(f"Total Card Elements: {len(card_obj['body']['elements'])}")
    
    unauth_card_json = build_unauthorized_card(query, user_id="unknown_user_999", open_id="ou_unknown")
    unauth_card_obj = json.loads(unauth_card_json)
    print(f"Unauthorized Card Header: {unauth_card_obj['header']['title']['content']}")
    
    print("\n==================================================")
    print("✅ ALL LOCAL TESTS PASSED SUCCESSFULLY!")
    print("==================================================")

if __name__ == "__main__":
    run_tests()
