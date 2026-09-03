from app import app
from flask import session
with app.test_request_context('/api/con/agent/status'):
    session['logged_in'] = True
    session['extension_ext'] = "6003"
    import con_routes
    res = con_routes.api_con_agent_status()
    print(res.get_data(as_text=True))
