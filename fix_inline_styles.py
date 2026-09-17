with open("static/css/glass_theme.css", "r") as f:
    css = f.read()

css = css.replace(".studio-card", ".studio-card, .media-hero")

with open("static/css/glass_theme.css", "w") as f:
    f.write(css)
