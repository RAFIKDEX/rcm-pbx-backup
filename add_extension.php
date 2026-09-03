<?php
require_once __DIR__ . "/auth.php";
rcm_require_login();

$EP_FILE = "/etc/asterisk/pjsip.gui.endpoint.conf";

$nextExt = "1000";
$defaultSecret = "Abc@1234";

function rcm_read_file_safe(string $path): string {
    return file_exists($path) ? (file_get_contents($path) ?: "") : "";
}

function rcm_strip_trunk_blocks(string $txt): string {
    return preg_replace('/^\s*;\s*---\s*RCM-TRUNK:\s*.*?\s*BEGIN\s*---\s*$.*?^\s*;\s*---\s*RCM-TRUNK:\s*.*?\s*END\s*---\s*$/ms', '', $txt) ?? $txt;
}

$txt = rcm_read_file_safe($EP_FILE);
if ($txt !== "") {
    $txt = rcm_strip_trunk_blocks($txt);

    if (preg_match_all('/^\[(\d{2,6})\]$/m', $txt, $m)) {
        $nums = array_map('intval', $m[1] ?? []);
        if (!empty($nums)) {
            $nextExt = (string)(max($nums) + 1);
        }
    }
}

$defaultCallerIdNumber = $nextExt;
?>
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Add Extension</title>

  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/assets/rcm.css">

  <style>
    .wrap{ width:min(760px, 95vw); }

    .page-subtitle{
      margin:0 0 22px 0;
      text-align:center;
      font-family:'Orbitron', sans-serif;
      font-weight:900;
      letter-spacing:6px;
      text-transform:uppercase;
      font-size:34px;
      text-shadow: 0 0 18px rgba(255,255,255,.35);
    }

    .panel-box{
      margin-top:0;
    }

    form{
      width:100%;
    }

    .row{
      display:grid;
      grid-template-columns: 1fr 1fr;
      gap:16px;
    }

    .field{
      margin-bottom:16px;
    }

    label{
      display:block;
      margin:0 0 8px 0;
      font-weight:800;
      font-size:15px;
      color:#fff;
    }

    input,
    select{
      width:100%;
      box-sizing:border-box;
      min-height:46px;
      padding:10px 14px;
      border-radius:12px;
      border:1px solid rgba(255,255,255,.28);
      background:rgba(255,255,255,.10);
      color:#fff;
      font-size:16px;
      outline:none;
    }

    input::placeholder{
      color:rgba(255,255,255,.40);
    }

    select{
      cursor:pointer;
    }

    .actions{
      display:grid;
      grid-template-columns: 1fr 1fr;
      gap:16px;
      margin-top:22px;
    }

    /* Tabs Styling */
    .tabs {
      display: flex;
      border-bottom: 2px solid rgba(255, 255, 255, 0.1);
      margin-bottom: 20px;
      gap: 10px;
    }
    .tab-btn {
      padding: 10px 20px;
      cursor: pointer;
      color: rgba(255, 255, 255, 0.6);
      font-family: 'Orbitron', sans-serif;
      font-size: 13px;
      font-weight: 700;
      text-transform: uppercase;
      transition: all 0.2s;
      border-bottom: 2px solid transparent;
      margin-bottom: -2px;
    }
    .tab-btn:hover, .tab-btn.active {
      color: #fff;
      border-bottom-color: #00adb5;
    }
    .tab-content {
      animation: fadeIn 0.3s ease-in-out;
    }

    .switch-field {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .switch-field input[type="checkbox"] {
      width: 24px;
      height: 24px;
      min-height: 24px;
      cursor: pointer;
    }

    @keyframes fadeIn {
      from { opacity: 0; }
      to { opacity: 1; }
    }

    @media (max-width: 700px){
      .row,
      .actions{
        grid-template-columns: 1fr;
      }
      .wrap{
        width:min(94vw, 760px);
      }
    }
  </style>
</head>

<body>
  <div class="wrap">
    <div class="inner-box" style="margin-top:0;">
      <h1 class="page-subtitle">ADD EXTENSION</h1>

      <div class="tabs">
        <div class="tab-btn active" onclick="switchTab('basic')">Basic</div>
        <div class="tab-btn" onclick="switchTab('media')">Media</div>
        <div class="tab-btn" onclick="switchTab('followme')">Follow Me</div>
      </div>

      <div class="panel-box">
        <form method="post" action="/save_extension.php" autocomplete="off">

          <!-- BASIC TAB -->
          <div id="tab-basic" class="tab-content">
            <div class="field switch-field">
              <input type="checkbox" name="enabled" checked id="enabled">
              <label for="enabled" style="margin: 0; cursor: pointer;">Enable This Extension</label>
            </div>

            <div class="row">
              <div class="field">
                <label>Extension Number</label>
                <input
                  name="ext"
                  required
                  pattern="[0-9]{2,6}"
                  placeholder="e.g. 3001"
                  value="<?= htmlspecialchars($nextExt) ?>"
                >
              </div>

              <div class="field">
                <label>SIP Password</label>
                <input
                  name="secret"
                  required
                  placeholder="e.g. Abc@1234"
                  value="<?= htmlspecialchars($defaultSecret) ?>"
                >
              </div>
            </div>

            <div class="row">
              <div class="field">
                <label>Caller ID Number</label>
                <input
                  name="callerid_number"
                  required
                  pattern="[0-9+*#]{2,20}"
                  placeholder="e.g. 3001"
                  value="<?= htmlspecialchars($defaultCallerIdNumber) ?>"
                >
              </div>

              <div class="field">
                <label>Caller ID Name</label>
                <input
                  name="callerid_name"
                  maxlength="80"
                  placeholder="e.g. Rafik"
                >
              </div>
            </div>

            <div class="row">
              <div class="field">
                <label>Concurrent Registrations (1-10)</label>
                <select name="max_contacts">
                  <?php for($i=1; $i<=10; $i++): ?>
                    <option value="<?= $i ?>" <?= $i === 3 ? 'selected' : '' ?>><?= $i ?></option>
                  <?php endfor; ?>
                </select>
              </div>

              <div class="field">
                <label>Max Expiration</label>
                <input
                  type="number"
                  name="max_expiration"
                  required
                  value="120"
                  min="30"
                  max="86400"
                >
              </div>
            </div>

            <div class="field" style="width: 50%;">
              <label>Extension Ring Time (seconds)</label>
              <input
                type="number"
                name="ring_time"
                required
                value="60"
                min="5"
                max="300"
              >
            </div>
          </div>

          <!-- MEDIA TAB -->
          <div id="tab-media" class="tab-content" style="display:none;">
            <div class="row">
              <div class="field">
                <label>Extension Recording</label>
                <select name="record_mode">
                  <option value="noo" selected>Off</option>
                  <option value="in">Incoming</option>
                  <option value="out">Outgoing</option>
                  <option value="all">All</option>
                </select>
              </div>

              <div class="field">
                <label>Direct Media</label>
                <select name="direct_media">
                  <option value="no" selected>Off</option>
                  <option value="yes">On</option>
                </select>
              </div>
            </div>

            <div class="row">
              <div class="field">
                <label>Enable Voicemail</label>
                <select name="vm_enabled" onchange="toggleVmFields(this.value)">
                  <option value="no" selected>Off</option>
                  <option value="yes">On</option>
                </select>
              </div>

              <div class="field" id="vm-password-field" style="display:none;">
                <label>Voicemail Password (digits only)</label>
                <input
                  type="text"
                  name="vm_password"
                  value="1234"
                  pattern="\d+"
                  placeholder="Voicemail PIN"
                >
              </div>
            </div>

            <div class="field" style="width: 50%;">
              <label>NAT</label>
              <select name="nat">
                <option value="no" selected>Off</option>
                <option value="yes">On</option>
              </select>
            </div>
          </div>

          <!-- FOLLOW ME TAB -->
          <div id="tab-followme" class="tab-content" style="display:none;">
            <label>Follow Me List</label>
            <div id="followme-container">
              <!-- Dynamically populated rows -->
            </div>
            <button type="button" class="btn" onclick="addFollowmeRow()" style="background: rgba(0, 173, 181, 0.15); border: 1px solid rgba(0, 173, 181, 0.3); color: #00adb5; margin-top: 10px; width: auto; padding: 10px 20px;">+ Add Destination</button>
          </div>

          <div class="actions">
            <a class="btn" href="/extensions.php">CANCEL</a>
            <button class="btn" type="submit">SAVE</button>
          </div>

        </form>
      </div>
    </div>
  </div>

  <script>
    function switchTab(tabId) {
      document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(content => content.style.display = 'none');
      
      const activeBtn = Array.from(document.querySelectorAll('.tab-btn')).find(btn => btn.textContent.toLowerCase() === (tabId === 'followme' ? 'follow me' : tabId));
      if (activeBtn) activeBtn.classList.add('active');
      
      document.getElementById('tab-' + tabId).style.display = 'block';
    }

    function toggleVmFields(val) {
      document.getElementById('vm-password-field').style.display = (val === 'yes') ? 'block' : 'none';
    }

    function addFollowmeRow(num = "", ring = "15") {
      const container = document.getElementById('followme-container');
      const div = document.createElement('div');
      div.className = 'followme-row';
      div.style = 'display: flex; gap: 10px; margin-bottom: 10px; align-items: center;';
      div.innerHTML = `
        <input type="text" name="followme_num[]" value="${num}" placeholder="Phone Number" required style="flex: 1;">
        <input type="number" name="followme_ring[]" value="${ring}" placeholder="Seconds" required style="width: 120px;">
        <button type="button" class="btn" onclick="this.parentElement.remove()" style="background: rgba(239,68,68,0.15); border: 1px solid rgba(239,68,68,0.3); color: #ff4a4a; padding: 10px 15px; border-radius: 12px; min-height: 46px; cursor: pointer;">Remove</button>
      `;
      container.appendChild(div);
    }

    const extInput = document.querySelector('input[name="ext"]');
    const cidNumInput = document.querySelector('input[name="callerid_number"]');

    if (extInput && cidNumInput) {
      extInput.addEventListener('input', () => {
        if (!cidNumInput.dataset.userEdited) {
          cidNumInput.value = extInput.value;
        }
      });

      cidNumInput.addEventListener('input', () => {
        cidNumInput.dataset.userEdited = '1';
      });
    }
  </script>
</body>
</html>
