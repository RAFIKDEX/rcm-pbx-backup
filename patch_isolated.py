import re

files_to_patch = [
    "templates/login.html",
    "templates/forgot_password.html",
    "templates/forgot_password_reset.html",
    "templates/forgot_password_verify.html",
    "templates/extension_portal/base.html"
]

css_link = """
    <!-- Glass Theme -->
    <link rel="stylesheet" href="{{ url_for('static', filename='css/glass_theme.css') }}?v=1.7">
</head>
"""

bg_div = """<body>
    <div class="uiverse-bg-container">
        <div id="stars"></div>
        <div id="stars2"></div>
        <div id="stars3"></div>
    </div>
"""

for filepath in files_to_patch:
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if "glass_theme.css" not in content:
        # Replace </head>
        content = re.sub(r'</head>', css_link, content, count=1, flags=re.IGNORECASE)
        # Replace <body>
        content = re.sub(r'<body[^>]*>', bg_div, content, count=1, flags=re.IGNORECASE)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Patched {filepath}")

