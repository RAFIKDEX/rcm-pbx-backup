from app import app
with app.test_client() as client:
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = 'admin'
        sess['role'] = 'admin'
    
    response = client.get('/extensions')
    html = response.get_data(as_text=True)
    
    with open('debug_extensions.html', 'w') as f:
        f.write(html)
    print("Fetched extensions.html, length:", len(html))
