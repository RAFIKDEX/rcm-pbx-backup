#!/usr/bin/env python3
import sys
import os
import uuid
import sqlite3
import datetime

def read_env():
    env = {}
    while True:
        line = sys.stdin.readline().strip()
        if not line:
            break
        parts = line.split(":", 1)
        if len(parts) == 2:
            env[parts[0].strip()] = parts[1].strip()
    return env

def send_command(cmd):
    sys.stdout.write(f"{cmd}\n")
    sys.stdout.flush()
    result = sys.stdin.readline().strip()
    return result

def get_variable(name):
    res = send_command(f'GET VARIABLE "{name}"')
    if res.startswith("200 result=1 ("):
        return res.split("(", 1)[1][:-1]
    return ""

def set_variable(name, value):
    send_command(f'SET VARIABLE "{name}" "{value}"')

def log(msg):
    send_command(f'VERBOSE "{msg}" 3')

def get_survey_questions(survey_id):
    db_path = "/root/RCM_7021/rcm_7021.db"
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT id, question_number, recording_path FROM survey_questions WHERE survey_id = ? ORDER BY question_number ASC", (survey_id,))
        questions = [{"id": row[0], "question_number": row[1], "recording_path": row[2]} for row in c.fetchall()]
        conn.close()
        return questions
    except Exception as e:
        log(f"DB Error: {e}")
        return []

def save_response(survey_id, agent, customer_num, queue, responses):
    db_path = "/root/RCM_7021/rcm_7021.db"
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT INTO survey_responses (survey_id, agent, customer_number, queue, timestamp) VALUES (?, ?, ?, ?, ?)",
                  (survey_id, agent, customer_num, queue, timestamp))
        response_id = c.lastrowid
        for resp in responses:
            c.execute("INSERT INTO survey_ratings (response_id, question_number, rating, reason) VALUES (?, ?, ?, ?)",
                      (response_id, resp["question_number"], resp["rating"], resp.get("reason", "")))
        conn.commit()
        conn.close()
    except Exception as e:
        log(f"DB Error saving response: {e}")

def main():
    env = read_env()
    survey_id = get_variable("SURVEY_ID")
    agent = get_variable("MEMBERINTERFACE")
    customer_num = get_variable("CUSTOMER_NUM")
    queue = get_variable("QUEUE_NUM")

    if not survey_id:
        log("No SURVEY_ID found.")
        return

    # Clean up agent PJSIP/1000 -> 1000
    if agent.startswith("PJSIP/"):
        agent = agent[6:]

    questions = get_survey_questions(survey_id)
    if not questions:
        log("No questions found for survey.")
        return

    # To avoid callback loops if customer hangs up here, disable hangup handler
    set_variable("SURVEY_ID", "") 

    responses = []

    for q in questions:
        audio_file = q["recording_path"].replace(".wav", "")
        # Strip .wav for AGI stream file
        if audio_file.endswith(".wav"):
            audio_file = audio_file[:-4]

        # Retry logic for DTMF
        dtmf = ""
        for i in range(3):
            res = send_command(f'GET DATA "{audio_file}" 5000 1')
            if res.startswith("200 result="):
                dtmf = res.split("=")[1].split(" ")[0]
                if dtmf in ["0", "1", "2", "3", "4", "5"]:
                    break
        
        if not dtmf or dtmf not in ["0", "1", "2", "3", "4", "5"]:
            log(f"Invalid or no DTMF for question {q['question_number']}")
            continue

        rating = int(dtmf)
        reason = ""

        if rating == 0:
            # Play a built-in prompt or just beep to ask for reason
            # The spec says: "If the caller presses 0, they should be prompted to leave a short voice message explaining why."
            send_command('STREAM FILE "beep" ""')
            record_file = f"/var/spool/asterisk/monitor/survey_reason_{uuid.uuid4().hex}"
            # RECORD FILE <filename> <format> <escape_digits> <timeout> [offset samples] [BEEP] [s=silence]
            res = send_command(f'RECORD FILE "{record_file}" "wav" "#" 30000 0 BEEP s=3')
            reason = record_file + ".wav"

        responses.append({
            "question_number": q["question_number"],
            "rating": rating,
            "reason": reason
        })

    # Save to DB
    if responses:
        save_response(survey_id, agent, customer_num, queue, responses)
        # Play a thank you prompt if desired
        send_command('STREAM FILE "auth-thankyou" ""')

if __name__ == "__main__":
    main()
