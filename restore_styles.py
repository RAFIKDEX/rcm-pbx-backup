import re

with open('/tmp/queue_stats_styles.css', 'r') as f:
    old_styles = f.read()

with open('templates/queue_stats.html', 'r') as f:
    content = f.read()

content = re.sub(r'<style>.*?</style>', old_styles, content, flags=re.DOTALL)

with open('templates/queue_stats.html', 'w') as f:
    f.write(content)
print("Styles restored.")
