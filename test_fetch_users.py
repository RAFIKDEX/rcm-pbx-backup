from app import app
with app.test_client() as client:
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = 'admin'
        sess['role'] = 'admin'
    
    response = client.get('/users')
    html = response.get_data(as_text=True)
    
    with open('debug_users.html', 'w') as f:
        f.write(html)
    print("Fetched users.html, length:", len(html))
