import re

files_to_patch = [
    '/root/RCM_7021/templates/cdr.html',
    '/root/RCM_7021/templates/queue_stats.html',
    '/root/RCM_7021/templates/queue_detail.html',
    '/root/RCM_7021/templates/call_records.html'
]

for file_path in files_to_patch:
    try:
        with open(file_path, 'r') as f:
            content = f.read()
            
        # For floatingAudio
        if 'const audioEl = $(\'floatingAudio\');' in content and 'audioEl.onerror' not in content:
            target = "const audioEl = $('floatingAudio');"
            replacement = """const audioEl = $('floatingAudio');
            audioEl.onerror = function() {
                alert("Cannot play recording. The external storage device (NAS/USB) is currently offline or disconnected.");
                stopPlaying();
            };"""
            content = content.replace(target, replacement)
            
        # For global-audio-player
        if 'const player = document.getElementById("global-audio-player");' in content and 'player.onerror' not in content:
            target = 'const player = document.getElementById("global-audio-player");'
            replacement = """const player = document.getElementById("global-audio-player");
        player.onerror = function() {
            alert("Cannot play recording. The external storage device (NAS/USB) is currently offline or disconnected.");
            document.getElementById("audio-player-container").style.display = "none";
        };"""
            content = content.replace(target, replacement)
            
        with open(file_path, 'w') as f:
            f.write(content)
    except Exception as e:
        print(f"Failed to patch {file_path}: {e}")
