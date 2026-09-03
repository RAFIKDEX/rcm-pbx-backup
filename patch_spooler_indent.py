with open('/root/RCM_7021/storage_spooler.py', 'r') as f:
    content = f.read()

target = """                    except Exception as e:
                    print(f"[SPOOLER] Error deleting local file: {e}")"""
replacement = """                    except Exception as e:
                        print(f"[SPOOLER] Error deleting local file: {e}")"""

content = content.replace(target, replacement)

with open('/root/RCM_7021/storage_spooler.py', 'w') as f:
    f.write(content)
