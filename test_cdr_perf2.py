import app
from flask import Flask
app.app = Flask(__name__)
import time

start = time.time()
with app.app.test_request_context('/cdr'):
    rows, stats, chart, total = app._query_cdr_records({'date_from': '', 'date_to': ''}, page=1, limit=10)
    print(f"Total time: {time.time() - start:.3f}s, Rows: {total}")
