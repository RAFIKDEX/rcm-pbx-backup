import app
import time

old_query = app._query_cdr_records
def profiled_query(*args, **kwargs):
    t0 = time.time()
    res = old_query(*args, **kwargs)
    t1 = time.time()
    print(f"PROFILE: _query_cdr_records took {t1-t0:.3f}s")
    return res

app._query_cdr_records = profiled_query
