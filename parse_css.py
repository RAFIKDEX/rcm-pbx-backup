import tinycss2

with open("static/css/glass_theme.css", "r") as f:
    css = f.read()

rules = tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True)
for rule in rules:
    if rule.type == 'error':
        print("CSS Error:", rule.message, "at line", rule.source_line)
