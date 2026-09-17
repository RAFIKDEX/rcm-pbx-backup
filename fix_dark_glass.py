with open("static/css/glass_theme.css", "r") as f:
    css = f.read()

# Make Dark Mode Glass more transparent and slightly "glassy" white/blue
css = css.replace("--glass-bg: rgba(11, 15, 25, 0.55);", "--glass-bg: rgba(255, 255, 255, 0.04);")
css = css.replace("--sidebar-bg: rgba(6, 8, 15, 0.65);", "--sidebar-bg: rgba(255, 255, 255, 0.02);")

# Also, wait... maybe the user meant that in dark mode the cards are NOT transparent, 
# while in light mode they ARE transparent.
# Let's ensure `--glass-bg` in dark mode is indeed `rgba(255, 255, 255, 0.05)` or similar.
# Let's check if the replacement worked.

with open("static/css/glass_theme.css", "w") as f:
    f.write(css)

