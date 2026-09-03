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

    callback_failed = get_variable("SURVEY_CALLBACK_FAILED")

    if callback_failed == "1":
        responses = []
        for q in questions:
            responses.append({
                "question_number": q["question_number"],
                "rating": 0,
                "reason": "CALLBACK_NO_ANSWER"
            })
        if responses:
            save_response(survey_id, agent, customer_num, queue, responses)
        return

    # To avoid callback loops if customer hangs up here, disable hangup handler
    set_variable("SURVEY_ID", "") 
    set_variable("SURVEY_STARTED", "1")

    responses = []
    hung_up = False

    for q in questions:
        if hung_up:
            responses.append({
                "question_number": q["question_number"],
                "rating": 0,
                "reason": "CUSTOMER_HANGUP"
            })
            continue

        audio_file = q["recording_path"]
        if audio_file.endswith(".wav"):
            audio_file = audio_file[:-4]

        res = send_command(f'GET DATA "{audio_file}" 10000 1')
        
        # If channel hangs up, res could be -1 or empty result with failure
        # Usually GET DATA returns "200 result=-1" on hangup
        if "result=-1" in res:
            hung_up = True
            responses.append({
                "question_number": q["question_number"],
                "rating": 0,
                "reason": "CUSTOMER_HANGUP"
            })
            continue
            
        dtmf = ""
        if res.startswith("200 result="):
            dtmf_part = res.split("=")[1].split(" ")[0]
            if dtmf_part and dtmf_part != "-1":
                dtmf = dtmf_part

        if not dtmf:
            responses.append({
                "question_number": q["question_number"],
                "rating": 0,
                "reason": "NO_RESPONSE"
            })
        elif dtmf not in ["1", "2", "3", "4", "5"]:
            responses.append({
                "question_number": q["question_number"],
                "rating": 0,
                "reason": "INVALID_DTMF"
            })
        else:
            responses.append({
                "question_number": q["question_number"],
                "rating": int(dtmf),
                "reason": ""
            })

    # Save to DB
    if responses:
        save_response(survey_id, agent, customer_num, queue, responses)
        if not hung_up:
            send_command('STREAM FILE "auth-thankyou" ""')

if __name__ == "__main__":
    main()
