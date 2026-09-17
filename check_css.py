def check_braces(filename):
    with open(filename, 'r') as f:
        content = f.read()
    
    open_count = content.count('{')
    close_count = content.count('}')
    print(f"Braces count: {{: {open_count}, }}: {close_count}")

check_braces('static/css/glass_theme.css')
