with open("static/css/glass_theme.css", "r") as f:
    css = f.read()

bad_block = """@keyframes introFadeUp {
  0% {
    opacity: 0;
    transform: translateY(30px);
  }

/* Missing Dashboard & Form Classes */"""

good_block = """@keyframes introFadeUp {
  0% {
    opacity: 0;
    transform: translateY(30px);
  }
  100% {
    opacity: 1;
    transform: translateY(0);
  }
}

/* Missing Dashboard & Form Classes */"""

css = css.replace(bad_block, good_block)

with open("static/css/glass_theme.css", "w") as f:
    f.write(css)

print("Brace fixed!")
