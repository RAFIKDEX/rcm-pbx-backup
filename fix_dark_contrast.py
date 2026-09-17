with open("static/css/glass_theme.css", "r") as f:
    css = f.read()

# Enhance Dark mode glass contrast
css = css.replace("--glass-bg: rgba(255, 255, 255, 0.04);", "--glass-bg: rgba(255, 255, 255, 0.03);")
css = css.replace("--glass-border: rgba(255, 255, 255, 0.12);", "--glass-border: rgba(255, 255, 255, 0.15);")
css = css.replace("--glass-highlight: inset 0 1px 0 0 rgba(255, 255, 255, 0.15);", "--glass-highlight: inset 0 1px 0 0 rgba(255, 255, 255, 0.2);")

with open("static/css/glass_theme.css", "w") as f:
    f.write(css)

