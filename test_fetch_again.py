from app import app
with app.test_client() as client:
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = 'admin'
        sess['role'] = 'admin'
    
    response = client.get('/users')
    with open('debug_users_final.html', 'w') as f:
        f.write(response.get_data(as_text=True))
        
    response = client.get('/dex/config')
    with open('debug_dex_config.html', 'w') as f:
        f.write(response.get_data(as_text=True))
