from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify, abort
import db
import rcm_queue_db
import asterisk_helper
from datetime import datetime

con_bp = Blueprint('con_bp', __name__)

@con_bp.route('/con/agent')
def con_agent():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    ext = session.get('extension_ext')
    if not ext:
        return render_template('error.html', message="Your user is not associated with an Extension. Only Agents can access this console.")
        
    config_queues = db.get_queues()
    agent_queues = []
    agent_type = "Dynamic"
    
    for q in config_queues:
        if str(ext) in [str(x) for x in q.get('static_agents', [])]:
            agent_queues.append(q)
            agent_type = "Static"
            
    # Add dynamic agents later if needed
    
    return render_template('con_agent.html', queues=agent_queues, agent_type=agent_type, ext=ext)

@con_bp.route('/con/supervisor')
def con_supervisor():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    user_id = str(session.get('user_id'))
    config_queues = db.get_queues()
    supervisor_queues = []
    
    for q in config_queues:
        supervisors = [str(x) for x in q.get('supervisors', [])]
        if user_id in supervisors or session.get('role') == 'admin':
            supervisor_queues.append(q)
            
    if not supervisor_queues and session.get('role') != 'admin':
        return render_template('error.html', message="You are not authorized as a Supervisor for any queue.")
        
    return render_template('con_supervisor.html', queues=supervisor_queues)

@con_bp.route('/api/con/agent/status')
def api_con_agent_status():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    
    ext = session.get('extension_ext')
    if not ext:
        return jsonify({"error": "Not an agent"}), 403
        
    live_status = rcm_queue_db.get_live_dashboard_status()
    agent_info = None
    caller = ""
    call_duration = 0
    current_qnum = ""
    
    for qnum, qdata in live_status.get("queues", {}).items():
        for member in qdata.get("roster", []):
            if str(member.get("extension")) == str(ext):
                if not agent_info or agent_info.get("status", 0) < member.get("status", 0):
                    agent_info = member
                    if agent_info.get("caller_id"):
                        caller = agent_info.get("caller_id")
                        call_duration = agent_info.get("call_duration", 0)
                        current_qnum = qnum
    
    if not agent_info:
        agent_info = {"status_text": "Available"}

    config_queues = db.get_queues()
    current_script = ""
    breaks = []
    
    for q in config_queues:
        if q.get("queue_number") == current_qnum:
            current_script = q.get("script", "")
        # Collect breaks
        for b in q.get("breaks", []):
            if b not in breaks:
                breaks.append(b)

    return jsonify({
        "status": agent_info.get("status_text", "Available"),
        "paused": agent_info.get("paused", 0),
        "paused_reason": agent_info.get("paused_reason", ""),
        "status_duration": agent_info.get("status_duration", 0),
        "caller": caller,
        "call_duration": call_duration,
        "queue": current_qnum,
        "script": current_script,
        "breaks": breaks,
        "login_time": agent_info.get("login_time", "")
    })

@con_bp.route('/api/con/agent/break', methods=['POST'])
def api_con_agent_break():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
        
    ext = session.get('extension_ext')
    if not ext:
        return jsonify({"error": "Not an agent"}), 403
        
    action = request.json.get("action")
    reason = request.json.get("reason", "Break")
    
    iface = f"PJSIP/{ext}"
    if action == "start":
        cmd = f"queue pause member {iface} reason {reason}"
        out, err, code = asterisk_helper.run_asterisk_cmd(cmd)
        if "paused" in out.lower() or "already" in out.lower() or code == 0:
            return jsonify({"success": True})
        return jsonify({"error": out}), 500
    elif action == "stop":
        cmd = f"queue unpause member {iface}"
        out, err, code = asterisk_helper.run_asterisk_cmd(cmd)
        return jsonify({"success": True})
    
    return jsonify({"error": "Invalid action"}), 400

@con_bp.route('/api/con/agent/call_control', methods=['POST'])
def api_con_agent_call_control():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
        
    ext = session.get('extension_ext')
    if not ext:
        return jsonify({"error": "Not an agent"}), 403
        
    action = request.json.get("action")
    target = request.json.get("target", "")
    
    iface = f"PJSIP/{ext}"
    
    out, err, code = asterisk_helper.run_asterisk_cmd("core show channels concise")
    lines = out.split("\n")
    agent_channel = None
    for line in lines:
        if line.startswith(iface + "-"):
            agent_channel = line.split("!")[0]
            break
            
    if not agent_channel:
        return jsonify({"error": "No active call found"}), 404
        
    if action == "hangup":
        asterisk_helper.run_asterisk_cmd(f"channel request hangup {agent_channel}")
        return jsonify({"success": True})
    elif action == "transfer" and target:
        asterisk_helper.run_asterisk_cmd(f"channel redirect {agent_channel} default,{target},1")
        return jsonify({"success": True})
    
    return jsonify({"error": "Action not fully supported"}), 400

@con_bp.route('/api/con/supervisor/status')
def api_con_supervisor_status():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
        
    user_id = str(session.get('user_id'))
    config_queues = db.get_queues()
    supervisor_queues = []
    
    for q in config_queues:
        supervisors = [str(x) for x in q.get('supervisors', [])]
        if user_id in supervisors or session.get('role') == 'admin':
            supervisor_queues.append(q.get("queue_number"))
            
    live_status = rcm_queue_db.get_live_dashboard_status()
    agents = []
    
    for qnum in supervisor_queues:
        qdata = live_status.get("queues", {}).get(qnum)
        if qdata:
            for member in qdata.get("roster", []):
                if not any(a["extension"] == member["extension"] for a in agents):
                    agents.append(member)
                    
    return jsonify({"agents": agents})

@con_bp.route('/api/con/supervisor/monitor', methods=['POST'])
def api_con_supervisor_monitor():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
        
    supervisor_ext = session.get('extension_ext')
    if not supervisor_ext:
        return jsonify({"error": "Supervisor must have an extension"}), 403
        
    action = request.json.get("action")
    target_ext = request.json.get("agent_ext")
    
    if action == "listen":
        mode = "q"
    elif action == "whisper":
        mode = "qw"
    elif action == "barge":
        mode = "qB"
    else:
        return jsonify({"error": "Invalid action"}), 400
        
    cmd = f"channel originate PJSIP/{supervisor_ext} extension *222{target_ext}{mode}@default"
    asterisk_helper.run_asterisk_cmd(cmd)
    
    return jsonify({"success": True})
