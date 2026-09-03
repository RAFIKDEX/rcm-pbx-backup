def get_all_surveys():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM surveys ORDER BY name")
    rows = [dict(r) for r in cursor.fetchall()]
    for row in rows:
        cursor.execute("SELECT * FROM survey_questions WHERE survey_id = ? ORDER BY question_number", (row['id'],))
        row['questions'] = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def get_survey(survey_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM surveys WHERE id = ?", (survey_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
    survey = dict(row)
    cursor.execute("SELECT * FROM survey_questions WHERE survey_id = ? ORDER BY question_number", (survey_id,))
    survey['questions'] = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return survey

def add_survey(name, questions_recordings):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO surveys (name) VALUES (?)", (name,))
    survey_id = cursor.lastrowid
    for i, path in enumerate(questions_recordings):
        cursor.execute("INSERT INTO survey_questions (survey_id, question_number, recording_path) VALUES (?, ?, ?)", (survey_id, i+1, path))
    conn.commit()
    conn.close()
    return survey_id

def update_survey(survey_id, name, questions_recordings):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE surveys SET name = ? WHERE id = ?", (name, survey_id))
    cursor.execute("DELETE FROM survey_questions WHERE survey_id = ?", (survey_id,))
    for i, path in enumerate(questions_recordings):
        cursor.execute("INSERT INTO survey_questions (survey_id, question_number, recording_path) VALUES (?, ?, ?)", (survey_id, i+1, path))
    conn.commit()
    conn.close()

def delete_survey(survey_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM surveys WHERE id = ?", (survey_id,))
    conn.commit()
    conn.close()

def save_survey_response(survey_id, queue, agent, customer_number, original_callid, ratings):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO survey_responses (survey_id, queue, agent, customer_number, original_callid) VALUES (?, ?, ?, ?, ?)",
        (survey_id, queue, agent, customer_number, original_callid)
    )
    response_id = cursor.lastrowid
    for q_num, data in ratings.items():
        cursor.execute(
            "INSERT INTO survey_ratings (response_id, question_number, rating, reason) VALUES (?, ?, ?, ?)",
            (response_id, q_num, data['rating'], data['reason'])
        )
    conn.commit()
    conn.close()
    return response_id
