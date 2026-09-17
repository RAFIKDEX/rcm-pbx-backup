from app import app
with app.test_client() as client:
    response = client.get('/static/css/glass_theme.css?v=1.9')
    print("Status:", response.status_code)
    print("Content length:", len(response.data))
