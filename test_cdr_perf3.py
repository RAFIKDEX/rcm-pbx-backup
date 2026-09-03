import app
from flask import Flask, session
app.app = Flask(__name__)
app.app.secret_key = 'test'
import time

with app.app.test_request_context('/cdr'):
    session['role'] = 'admin'
    start = time.time()
    rows, stats, chart, total = app._query_cdr_records({'date_from': '', 'date_to': ''}, page=1, limit=10)
    print(f"Total time: {time.time() - start:.3f}s, Rows: {total}")
