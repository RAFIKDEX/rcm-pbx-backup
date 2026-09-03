import re

with open("app.py", "r", encoding="utf-8") as f:
    content = f.read()

# Fix normal string content
content = re.sub(
    r'csv_content\s*=\s*"\\n"\.join\(csv_lines\)',
    r'csv_content = "\\ufeff" + "\\n".join(csv_lines)',
    content
)

# Fix dest.getvalue() content
content = re.sub(
    r'Response\(\s*dest\.getvalue\(\)\s*,\s*mimetype="text/csv"',
    r'Response("\\ufeff" + dest.getvalue().lstrip("\\ufeff"), mimetype="text/csv; charset=utf-8"',
    content
)

# Also fix the general mimetype to include charset just in case
content = re.sub(
    r'mimetype="text/csv"(?!;)',
    r'mimetype="text/csv; charset=utf-8"',
    content
)

with open("app.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Fixed app.py")
