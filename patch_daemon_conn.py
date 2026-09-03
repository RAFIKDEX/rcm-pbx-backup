with open('/root/RCM_7021/auto_cleaner_daemon.py', 'r') as f:
    content = f.read()

# Remove early conn.close()
content = content.replace("            else:\n                conn.close()", "")
content = content.replace("        else:\n            conn.close()", "")
content = content.replace("        if not config_row:\n            conn.close()\n            return", "        if not config_row:\n            conn.close()\n            return") # Keep this one

# We must close conn at the very end of the function if it wasn't closed inside the execution blocks.
# Let's just rewrite the whole check_and_run_auto_cleanup function to be absolutely safe.
