import re

with open("app.py", "r", encoding="utf-8") as f:
    content = f.read()

content = re.sub(
    r"Response\(\s*output\.getvalue\(\)\s*,\s*mimetype=['\"]text/csv['\"]",
    r'Response("\\ufeff" + output.getvalue().lstrip("\\ufeff"), mimetype="text/csv; charset=utf-8"',
    content
)

with open("app.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Fixed app.py second pass")
