import app
import db
from flask import Flask, session
import time

app.app = Flask(__name__)
app.app.secret_key = 'test'

with app.app.test_request_context('/cdr?q=foo'):
    session['legacy_role'] = 'admin'
    
    start = time.time()
    rows, stats, chart, total = app._query_cdr_records({'q': 'foo'}, page=1, limit=50)
    print(f"Total query time: {time.time() - start:.3f}s")
