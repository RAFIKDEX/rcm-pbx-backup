import sys
import os

sys.path.insert(0, '/root/RCM_7021')
from app import app
import db
import asterisk_helper

def test_duplicate_ivr():
    print("Testing duplicate IVR option mapping validation...")
    client = app.test_client()
    
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = 'admin'
        sess['role'] = 'Administrator'
    
    # Payload with duplicate keys (Option '1' mapped twice)
    payload = {
        "num": "7002",
        "name": "test_duplicate",
        "prompt_id": "prompt_97kjrsaj",
        "timeout": "10",
        "loops": "3",
        "fail_mode": "hangup",
        "fail_ext": "hangup",
        "mapping_keys[]": ["1", "1"],
        "mapping_dest_types[]": ["extension", "queue"],
        "mapping_dests[]": ["5001", "6500"]
    }
    
    response = client.post("/ivr/add", data=payload)
    print(f"Response status code: {response.status_code}")
    print(f"Response JSON: {response.get_json()}")
    
    assert response.status_code == 400
    json_data = response.get_json()
    assert json_data["status"] == "error"
    assert "Duplicate DTMF keys" in json_data["msg"]
    print("Success: Backend correctly blocked duplicate DTMF keys with 400 Bad Request.")

def test_valid_ivr():
    print("\nTesting valid unique IVR option mapping creation...")
    client = app.test_client()
    
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = 'admin'
        sess['role'] = 'Administrator'
        
    # First delete IVR 7002 if it exists
    ivrs = db.get_ivrs()
    ivrs = [ivr for ivr in ivrs if ivr.get('num') != '7002']
    db.save_ivrs(ivrs)
    
    # Payload with unique keys
    payload = {
        "num": "7002",
        "name": "test_valid",
        "prompt_id": "prompt_97kjrsaj",
        "timeout": "10",
        "loops": "3",
        "fail_mode": "hangup",
        "fail_ext": "hangup",
        "mapping_keys[]": ["1", "2"],
        "mapping_dest_types[]": ["extension", "queue"],
        "mapping_dests[]": ["5001", "6500"]
    }
    
    # We should mock redirect since it returns a 302 Redirect on success
    response = client.post("/ivr/add", data=payload)
    print(f"Response status code: {response.status_code}")
    
    # Check if saved to database
    saved_ivrs = db.get_ivrs()
    target_ivr = None
    for ivr in saved_ivrs:
        if ivr.get("num") == "7002":
            target_ivr = ivr
            break
            
    assert target_ivr is not None
    print("Saved IVR data:", target_ivr)
    assert len(target_ivr["mappings"]) == 2
    assert target_ivr["mappings"][0]["key"] == "1"
    assert target_ivr["mappings"][0]["dest_type"] == "extension"
    assert target_ivr["mappings"][1]["key"] == "2"
    assert target_ivr["mappings"][1]["dest_type"] == "queue"
    
    # Verify Asterisk Dialplan context
    print("Reading generated Asterisk dialplan context for IVR 7002...")
    with open("/etc/asterisk/extensions.ivr.gui.conf", "r") as f:
        dialplan = f.read()
        
    print("Dialplan Context content:")
    print(dialplan)
    
    assert "[ivr-7002]" in dialplan
    assert "exten => 1,1,Goto(internal,5001,1)" in dialplan
    assert "exten => 2,1,Queue(6500,tT)" in dialplan
    print("Success: Valid IVR created and Asterisk Dialplan context written flawlessly.")

if __name__ == "__main__":
    try:
        test_duplicate_ivr()
        test_valid_ivr()
        print("\nAll verification checks passed successfully!")
    except AssertionError as e:
        print(f"\nVerification FAILED: {e}")
        sys.exit(1)
