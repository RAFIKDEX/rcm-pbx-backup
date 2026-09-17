with open("static/css/glass_theme.css", "r") as f:
    content = f.read()

# Update Dark Mode Variables
content = content.replace("--glass-bg: rgba(21, 29, 48, 0.45);", "--glass-bg: rgba(11, 15, 25, 0.55);")
content = content.replace("--glass-blur: blur(12px);", "--glass-blur: blur(20px);")
content = content.replace("--glass-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);", "--glass-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);")
content = content.replace("--glass-border: rgba(255, 255, 255, 0.08);", "--glass-border: rgba(255, 255, 255, 0.12);")
content = content.replace("--sidebar-bg: rgba(12, 15, 29, 0.6);", "--sidebar-bg: rgba(6, 8, 15, 0.65);")

# Update Light Mode Variables
content = content.replace("--glass-bg: rgba(255, 255, 255, 0.55);", "--glass-bg: rgba(255, 255, 255, 0.75);")
content = content.replace("--glass-blur: blur(16px);", "--glass-blur: blur(24px);")
content = content.replace("--glass-border: rgba(255, 255, 255, 0.4);", "--glass-border: rgba(255, 255, 255, 0.6);")

# Enhance Star Parallax
content = content.replace("animation: animStar 50s linear infinite;", "animation: animStar 120s linear infinite;")
content = content.replace("animation: animStar 100s linear infinite;", "animation: animStar 80s linear infinite;")
content = content.replace("animation: animStar 150s linear infinite;", "animation: animStar 45s linear infinite;")

with open("static/css/glass_theme.css", "w") as f:
    f.write(content)
print("Glass feel enhanced")
