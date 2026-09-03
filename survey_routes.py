
# ==============================================================================
# SURVEY SYSTEM
# ==============================================================================

@app.route('/surveys')
@require_permission('queues', 'view')
def survey_list():
    surveys = db.get_all_surveys()
    return render_template('survey_list.html', surveys=surveys)

@app.route('/surveys/add', methods=['GET', 'POST'])
@require_csrf
@require_permission('queues', 'add')
def survey_add():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash("Survey name is required.", "danger")
            return redirect(url_for('survey_add'))

        files = request.files.getlist('recordings')
        recordings = []
        import tempfile
        import os
        import uuid
        dest_dir = "/var/lib/asterisk/sounds/custom/surveys"
        os.makedirs(dest_dir, exist_ok=True)
        
        for file in files:
            if file and file.filename:
                if len(recordings) >= 5:
                    break
                ext = os.path.splitext(file.filename)[1][:16]
                fd, temp_path = tempfile.mkstemp(suffix=ext)
                os.close(fd)
                file.save(temp_path)
                
                dest_name = f"survey_{uuid.uuid4().hex}"
                dest_path = os.path.join(dest_dir, f"{dest_name}.wav")
                
                success = asterisk_helper.save_and_convert_audio(temp_path, dest_path)
                if success:
                    recordings.append(f"custom/surveys/{dest_name}")
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                    
        if not recordings:
            flash("At least one valid recording is required.", "danger")
            return redirect(url_for('survey_add'))
            
        survey_id = db.add_survey(name, recordings)
        flash(f"Survey '{name}' created successfully with {len(recordings)} questions.", "success")
        return redirect(url_for('survey_list'))
        
    return render_template('survey_form.html', survey=None)

@app.route('/surveys/edit/<int:survey_id>', methods=['GET', 'POST'])
@require_csrf
@require_permission('queues', 'edit')
def survey_edit(survey_id):
    survey = db.get_survey(survey_id)
    if not survey:
        flash("Survey not found.", "danger")
        return redirect(url_for('survey_list'))
        
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash("Survey name is required.", "danger")
            return redirect(url_for('survey_edit', survey_id=survey_id))
            
        files = request.files.getlist('recordings')
        recordings = []
        import tempfile
        import os
        import uuid
        dest_dir = "/var/lib/asterisk/sounds/custom/surveys"
        os.makedirs(dest_dir, exist_ok=True)
        
        for file in files:
            if file and file.filename:
                if len(recordings) >= 5:
                    break
                ext = os.path.splitext(file.filename)[1][:16]
                fd, temp_path = tempfile.mkstemp(suffix=ext)
                os.close(fd)
                file.save(temp_path)
                
                dest_name = f"survey_{uuid.uuid4().hex}"
                dest_path = os.path.join(dest_dir, f"{dest_name}.wav")
                
                success = asterisk_helper.save_and_convert_audio(temp_path, dest_path)
                if success:
                    recordings.append(f"custom/surveys/{dest_name}")
                if os.path.exists(temp_path):
                    os.remove(temp_path)
        
        # If no new recordings, keep the old ones
        if not recordings:
            recordings = [q['recording_path'] for q in survey['questions']]
            
        if not recordings:
            flash("At least one valid recording is required.", "danger")
            return redirect(url_for('survey_edit', survey_id=survey_id))
            
        db.update_survey(survey_id, name, recordings)
        flash(f"Survey '{name}' updated successfully.", "success")
        return redirect(url_for('survey_list'))
        
    return render_template('survey_form.html', survey=survey)

@app.route('/surveys/delete/<int:survey_id>', methods=['POST'])
@require_csrf
@require_permission('queues', 'delete')
def survey_delete(survey_id):
    db.delete_survey(survey_id)
    flash("Survey deleted.", "success")
    return redirect(url_for('survey_list'))

@app.route('/surveys/report/<int:survey_id>')
@require_permission('queues', 'view')
def survey_report(survey_id):
    survey = db.get_survey(survey_id)
    if not survey:
        flash("Survey not found.", "danger")
        return redirect(url_for('survey_list'))
        
    conn = db.get_db()
    c = conn.cursor()
    
    # Apply Time Filters
    time_filter = request.args.get('time_filter', 'today')
    custom_start = request.args.get('start', '')
    custom_end = request.args.get('end', '')
    
    date_where = "1=1"
    params = []
    
    # Calculate bounds (simplified for brevity)
    import datetime
    now = datetime.datetime.now()
    if time_filter == 'today':
        start = now.replace(hour=0, minute=0, second=0).strftime("%Y-%m-%d %H:%M:%S")
        date_where = "timestamp >= ?"
        params.append(start)
    elif time_filter == '7days':
        start = (now - datetime.timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        date_where = "timestamp >= ?"
        params.append(start)
    elif time_filter == '30days':
        start = (now - datetime.timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        date_where = "timestamp >= ?"
        params.append(start)
    elif time_filter == 'custom' and custom_start and custom_end:
        date_where = "timestamp BETWEEN ? AND ?"
        params.extend([custom_start, custom_end])
        
    params_with_survey = [survey_id] + params
    
    # Summary of Ratings per Queue
    c.execute(f"""
        SELECT sr.queue, srat.rating, COUNT(srat.id) as count
        FROM survey_responses sr
        JOIN survey_ratings srat ON sr.id = srat.response_id
        WHERE sr.survey_id = ? AND {date_where}
        GROUP BY sr.queue, srat.rating
    """, params_with_survey)
    queue_ratings = c.fetchall()
    
    # Summary of Ratings per Agent
    c.execute(f"""
        SELECT sr.agent, srat.rating, COUNT(srat.id) as count
        FROM survey_responses sr
        JOIN survey_ratings srat ON sr.id = srat.response_id
        WHERE sr.survey_id = ? AND {date_where}
        GROUP BY sr.agent, srat.rating
    """, params_with_survey)
    agent_ratings = c.fetchall()
    
    # Summary of Ratings per Question
    c.execute(f"""
        SELECT srat.question_number, srat.rating, COUNT(srat.id) as count
        FROM survey_responses sr
        JOIN survey_ratings srat ON sr.id = srat.response_id
        WHERE sr.survey_id = ? AND {date_where}
        GROUP BY srat.question_number, srat.rating
    """, params_with_survey)
    question_ratings = c.fetchall()
    
    conn.close()
    
    return render_template('survey_report.html', survey=survey, queue_ratings=queue_ratings, agent_ratings=agent_ratings, question_ratings=question_ratings, time_filter=time_filter, start=custom_start, end=custom_end)

@app.route('/surveys/report/<int:survey_id>/drilldown')
@require_permission('queues', 'view')
def survey_drilldown(survey_id):
    queue = request.args.get('queue')
    agent = request.args.get('agent')
    rating = request.args.get('rating')
    question = request.args.get('question')
    
    conn = db.get_db()
    c = conn.cursor()
    
    where = "sr.survey_id = ?"
    params = [survey_id]
    
    if queue:
        where += " AND sr.queue = ?"
        params.append(queue)
    if agent:
        where += " AND sr.agent = ?"
        params.append(agent)
    if rating:
        where += " AND srat.rating = ?"
        params.append(rating)
    if question:
        where += " AND srat.question_number = ?"
        params.append(question)
        
    c.execute(f"""
        SELECT sr.queue, sr.agent, sr.customer_number, sr.timestamp, srat.question_number, srat.rating, srat.reason
        FROM survey_responses sr
        JOIN survey_ratings srat ON sr.id = srat.response_id
        WHERE {where}
        ORDER BY sr.timestamp DESC
        LIMIT 100
    """, params)
    results = [dict(r) for r in c.fetchall()]
    conn.close()
    
    return jsonify({'results': results})
