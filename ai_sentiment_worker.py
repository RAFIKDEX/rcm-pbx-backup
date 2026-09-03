import sqlite3
import time
import random
import os

DB_PATH = "/root/RCM_7021/rcm_queue.db"

# Simulated AI processing
def analyze_call_audio(call_id, recording_path):
    # In a real scenario, we would use:
    # 1. whisper.load_model("tiny") -> transcript
    # 2. Extract keywords from transcript
    
    # Mocking the AI output for demonstration
    sentiments = ["Happy", "Neutral", "Angry"]
    weights = [0.4, 0.5, 0.1] # 10% angry calls
    sentiment = random.choices(sentiments, weights=weights, k=1)[0]
    
    transcripts = {
        "Happy": "Thank you so much for your help! The service was excellent. I will definitely recommend you.",
        "Neutral": "Okay, I understand. Please update my account with this information. Thanks, goodbye.",
        "Angry": "This is ridiculous! I have been waiting for 20 minutes and nobody solved my issue. I want a refund now!"
    }
    
    summaries = {
        "Happy": "Customer called to inquire about service, was very satisfied with the resolution.",
        "Neutral": "Customer called to update account information. Standard call.",
        "Angry": "Customer complained about long wait times and unresolved issues. Demanded a refund."
    }
    
    # Simulate processing time
    time.sleep(0.5)
    
    return transcripts[sentiment], sentiment, summaries[sentiment]

def process_pending_calls():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Get calls that have a recording but haven't been analyzed yet
    # Since recording paths are empty in the test DB, we will just fetch recent answered calls
    c.execute("""
        SELECT q.call_id, q.recording_path 
        FROM queue_calls q
        LEFT JOIN rcm_call_analysis a ON q.call_id = a.call_id
        WHERE a.call_id IS NULL AND q.status = 'CONNECT'
        ORDER BY q.entry_time DESC
        LIMIT 50
    """)
    pending_calls = c.fetchall()
    
    if not pending_calls:
        print("[AI Worker] No pending calls to analyze.")
        conn.close()
        return

    print(f"[AI Worker] Found {len(pending_calls)} pending calls for analysis.")
    
    for row in pending_calls:
        call_id = row["call_id"]
        recording_path = row["recording_path"]
        
        try:
            transcript, sentiment, summary = analyze_call_audio(call_id, recording_path)
            c.execute("""
                INSERT INTO rcm_call_analysis (call_id, transcript, sentiment, summary)
                VALUES (?, ?, ?, ?)
            """, (call_id, transcript, sentiment, summary))
            conn.commit()
            print(f"[AI Worker] Analyzed call {call_id}: Sentiment -> {sentiment}")
        except Exception as e:
            print(f"[AI Worker] Error analyzing call {call_id}: {e}")
            
    conn.close()

if __name__ == "__main__":
    print("Starting AI Sentiment Background Worker...")
    while True:
        try:
            process_pending_calls()
        except Exception as e:
            print(f"[AI Worker] Fatal error: {e}")
        # Run every 60 seconds
        time.sleep(60)
