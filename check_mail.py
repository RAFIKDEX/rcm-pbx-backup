import sqlite3
conn = sqlite3.connect('/root/RCM_7021/rcm_7021.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute("SELECT * FROM mail_settings")
row = c.fetchone()
print(dict(row) if row else "No mail settings")
conn.close()
