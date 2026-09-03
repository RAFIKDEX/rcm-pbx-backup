<?php
require_once __DIR__ . "/auth.php";
rcm_require_login();

header("Cache-Control: no-store, no-cache, must-revalidate, max-age=0");
header("Pragma: no-cache");
header("Expires: 0");

function clean($s){ return trim((string)$s); }

$ext = clean($_GET["ext"] ?? $_POST["ext"] ?? "");
if (!preg_match('/^\d{2,6}$/', $ext)) {
  http_response_code(400);
  echo "Bad request: invalid extension";
  exit;
}

$EP_FILE   = "/etc/asterisk/pjsip.gui.endpoint.conf";
$AUTH_FILE = "/etc/asterisk/pjsip.gui.auth.conf";
$AOR_FILE  = "/etc/asterisk/pjsip.gui.aor.conf";
$DP_FILE   = "/etc/asterisk/extensions_gui.conf";

function read_ini_block_extended($file, $section) {
  if (!file_exists($file)) return null;
  $lines = file($file, FILE_IGNORE_NEW_LINES);
  $in = false;
  $data = [];

  foreach ($lines as $ln) {
    $t = trim($ln);
    if ($t === "") continue;

    if (preg_match('/^\[(.+)\]$/', $t, $m)) {
      $in = ($m[1] === $section);
      continue;
    }

    if ($in) {
      if ($t[0] === ';') {
        if (preg_match('/^;\s*([A-Za-z0-9_\-]+)\s*=\s*(.+)$/', $t, $cm)) {
          $data[trim($cm[1])] = trim($cm[2]);
        }
        continue;
      }
      if (strpos($t, '=') !== false) {
        [$k,$v] = array_map('trim', explode('=', $t, 2));
        $data[$k] = $v;
      }
    }
  }

  return $data ?: null;
}

function read_dp_globals_extended($file, $ext) {
  $rec = "noo";
  $vm = "Off";
  $ring_time = "60";

  if (!file_exists($file)) return [$rec, $vm, $ring_time];

  $lines = file($file, FILE_IGNORE_NEW_LINES);
  foreach ($lines as $ln) {
    $t = trim($ln);
    if (preg_match('/^RECORD_'.$ext.'=(.+)$/', $t, $m)) $rec = trim($m[1]);
    if (preg_match('/^VM_'.$ext.'=(.+)$/', $t, $m)) $vm = trim($m[1]);
    if (preg_match('/^RING_'.$ext.'=(.+)$/', $t, $m)) $ring_time = trim($m[1]);
  }

  return [$rec, $vm, $ring_time];
}

function parse_callerid_parts(string $raw, string $fallbackExt): array {
  $raw = trim($raw);

  if ($raw !== '' && preg_match('/^"?(.*?)"?\s*<\s*([^>]+)\s*>$/', $raw, $m)) {
    return [trim($m[1]), trim($m[2])];
  }

  if ($raw !== '') {
    return [$raw, $fallbackExt];
  }

  return ['', $fallbackExt];
}

function read_voicemail_config($ext) {
  $file = "/etc/asterisk/voicemail.conf";
  if (!file_exists($file)) return ["enabled" => false, "password" => "1234"];
  
  $lines = file($file, FILE_IGNORE_NEW_LINES);
  $in_default = false;
  foreach ($lines as $ln) {
    $t = trim($ln);
    if ($t === "") continue;
    if (preg_match('/^\[(.+)\]$/', $t, $m)) {
      $in_default = ($m[1] === "default");
      continue;
    }
    if ($in_default) {
      if (preg_match('/^' . $ext . '\s*=>\s*([^,]+)/', $t, $m)) {
        return ["enabled" => true, "password" => trim($m[1])];
      }
    }
  }
  return ["enabled" => false, "password" => "1234"];
}

function read_followme_config($ext) {
  $file = "/etc/asterisk/followme.conf";
  $list = [];
  if (!file_exists($file)) return $list;
  
  $lines = file($file, FILE_IGNORE_NEW_LINES);
  $in_ext = false;
  foreach ($lines as $ln) {
    $t = trim($ln);
    if ($t === "") continue;
    if (preg_match('/^\[(.+)\]$/', $t, $m)) {
      $in_ext = ($m[1] === $ext);
      continue;
    }
    if ($in_ext) {
      if (preg_match('/^number\s*=>\s*([^,]+),(\d+)/i', $t, $m)) {
        $list[] = [
          "number" => trim($m[1]),
          "ring" => (int)$m[2]
        ];
      }
    }
  }
  return $list;
}

$ep   = read_ini_block_extended($EP_FILE, $ext);
$auth = read_ini_block_extended($AUTH_FILE, $ext);
$aor  = read_ini_block_extended($AOR_FILE, $ext);

if (!$ep || !$auth || !$aor) {
  http_response_code(404);
  echo "Extension [$ext] not found in GUI files.";
  exit;
}

$allow = $ep["allow"] ?? "alaw,ulaw";
$context = $ep["context"] ?? "internal";

// Concurrent registration configured value stored in comment or max_contacts
$configured_max = $aor["rcm_max_contacts"] ?? $aor["max_contacts"] ?? "3";
$maxContacts = $configured_max;
$isEnabled = (int)($aor["max_contacts"] ?? 1) > 0;

$maxExpiration = $aor["maximum_expiration"] ?? "120";
$secret = $auth["password"] ?? "";

$directMedia = ($ep["direct_media"] ?? "no") === "yes";
$nat = (isset($ep["rtp_symmetric"]) && $ep["rtp_symmetric"] === "yes");

[$calleridName, $calleridNumber] = parse_callerid_parts((string)($ep['callerid'] ?? ''), $ext);
if ($calleridName === '') $calleridName = $ext;

[$recordMode, $vmMode, $ringTime] = read_dp_globals_extended($DP_FILE, $ext);

$vmData = read_voicemail_config($ext);
$vmEnabled = $vmData["enabled"];
$vmPassword = $vmData["password"];

$followmeList = read_followme_config($ext);

$errors = [];
$out = "";
$ok = false;

if ($_SERVER["REQUEST_METHOD"] === "POST") {
  $secret = clean($_POST["secret"] ?? "");
  $calleridName = clean($_POST["callerid_name"] ?? "");
  if ($calleridName === "") {
    $calleridName = $ext;
  }
  $calleridNumber = clean($_POST["callerid_number"] ?? "");
  if ($calleridNumber === "") {
    $calleridNumber = $ext;
  }
  $allow = clean($_POST["allow"] ?? "alaw,ulaw");
  $maxContacts = clean($_POST["max_contacts"] ?? "3");
  $maxExpiration = clean($_POST["max_expiration"] ?? "120");
  $ringTime = clean($_POST["ring_time"] ?? "60");
  $recordMode = clean($_POST["record_mode"] ?? "noo");
  $directMediaVal = clean($_POST["direct_media"] ?? "no");
  $vmEnabledVal = clean($_POST["vm_enabled"] ?? "no");
  $vmPassword = clean($_POST["vm_password"] ?? "1234");
  $natVal = clean($_POST["nat"] ?? "no");

  if ($secret === "") $errors[] = "Secret is required";
  if (!preg_match('/^[0-9+*#]{2,20}$/', $calleridNumber)) $errors[] = "Invalid Caller ID number";
  if (!preg_match('/^\d+$/', $maxContacts) || (int)$maxContacts < 1 || (int)$maxContacts > 10) $errors[] = "Invalid concurrent registrations";
  if (!preg_match('/^\d+$/', $maxExpiration)) $errors[] = "Invalid max expiration";
  if (!preg_match('/^\d+$/', $ringTime)) $errors[] = "Invalid ring time";
  if (!in_array($recordMode, ["in","out","noo","all"], true)) $errors[] = "Invalid record mode";
  if ($vmEnabledVal === "yes" && !preg_match('/^\d+$/', $vmPassword)) $errors[] = "Voicemail password must be digits only";

  $followmeRows = [];
  if (isset($_POST['followme_num']) && is_array($_POST['followme_num'])) {
    foreach ($_POST['followme_num'] as $index => $num) {
      $num = clean($num);
      if ($num !== "") {
        $ring = isset($_POST['followme_ring'][$index]) ? (int)$_POST['followme_ring'][$index] : 15;
        $followmeRows[] = [
          "number" => $num,
          "ring" => $ring
        ];
      }
    }
  }

  if (!$errors) {
    $payload = json_encode([
      "ext" => $ext,
      "enabled" => isset($_POST['enabled']),
      "secret" => $secret,
      "name" => $calleridName,
      "callerid_number" => $calleridNumber,
      "max_contacts" => (int)$maxContacts,
      "max_expiration" => (int)$maxExpiration,
      "ring_time" => (int)$ringTime,
      "record_mode" => $recordMode,
      "vm_enabled" => $vmEnabledVal === "yes",
      "vm_password" => $vmPassword,
      "direct_media" => $directMediaVal === "yes",
      "nat" => $natVal === "yes",
      "followme" => $followmeRows
    ]);

    $cmd = "sudo /usr/local/bin/rcm_edit_ext.sh";
    $descriptorspec = [
      0 => ["pipe", "r"],
      1 => ["pipe", "w"],
      2 => ["pipe", "w"]
    ];
    
    $process = proc_open($cmd, $descriptorspec, $pipes);
    if (is_resource($process)) {
      fwrite($pipes[0], $payload);
      fclose($pipes[0]);
      $out = stream_get_contents($pipes[1]);
      fclose($pipes[1]);
      $err = stream_get_contents($pipes[2]);
      fclose($pipes[2]);
      proc_close($process);
      
      $out = trim($out);
      $ok = (strpos($out, "OK:") === 0);
      
      // Update local variables for form display if save was successful
      if ($ok) {
        $isEnabled = isset($_POST['enabled']);
        $secret = $_POST["secret"];
        $calleridName = $_POST["callerid_name"];
        $calleridNumber = $_POST["callerid_number"];
        $allow = $_POST["allow"];
        $maxExpiration = $_POST["max_expiration"];
        $ringTime = $_POST["ring_time"];
        $recordMode = $_POST["record_mode"];
        $directMedia = $directMediaVal === "yes";
        $vmEnabled = $vmEnabledVal === "yes";
        $vmPassword = $_POST["vm_password"];
        $nat = $natVal === "yes";
        $followmeList = $followmeRows;
      }
    } else {
      $errors[] = "Failed to run edit extension script";
    }
  }
}
?>
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Edit Extension</title>

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

    .box{
      background:rgba(255,255,255,0.10);
      border:1px solid rgba(255,255,255,0.18);
      border-radius:18px;
      padding:14px;
      margin-bottom:20px;
      white-space:pre-wrap;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      font-size:13px;
      opacity:.95;
    }
    .ok{color:#b8ffcc;font-weight:900;text-align:center;margin-bottom:20px}
    .bad{color:#ffd0d0;font-weight:900;text-align:center;margin-bottom:20px}

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
      <h1 class="page-subtitle">EDIT EXTENSION</h1>
      <h2 style="text-align: center; color: #fff; font-family: 'Orbitron', sans-serif; margin-bottom: 20px;">
        Extension: <?= htmlspecialchars($ext) ?>
      </h2>

      <?php if ($_SERVER["REQUEST_METHOD"] === "POST"): ?>
        <?php if ($errors): ?>
          <div class="bad">FAILED</div>
          <ul>
            <?php foreach($errors as $e): ?><li><?= htmlspecialchars($e) ?></li><?php endforeach; ?>
          </ul>
        <?php else: ?>
          <?php if ($ok): ?><div class="ok">SUCCESSFULLY SAVED</div><?php else: ?><div class="bad">SAVE FAILED</div><?php endif; ?>
          <div class="box"><?= htmlspecialchars($out ?: "No output") ?></div>
        <?php endif; ?>
      <?php endif; ?>

      <div class="tabs">
        <div class="tab-btn active" onclick="switchTab('basic')">Basic</div>
        <div class="tab-btn" onclick="switchTab('media')">Media</div>
        <div class="tab-btn" onclick="switchTab('followme')">Follow Me</div>
      </div>

      <div class="panel-box">
        <form method="post" autocomplete="off">
          <input type="hidden" name="ext" value="<?= htmlspecialchars($ext) ?>">

          <!-- BASIC TAB -->
          <div id="tab-basic" class="tab-content">
            <div class="field switch-field">
              <input type="checkbox" name="enabled" id="enabled" <?= $isEnabled ? 'checked' : '' ?>>
              <label for="enabled" style="margin: 0; cursor: pointer;">Enable This Extension</label>
            </div>

            <div class="row">
              <div class="field">
                <label>Extension Number</label>
                <div style="min-height:46px; padding:10px 14px; background:rgba(255,255,255,.05); border-radius:12px; border:1px solid rgba(255,255,255,.1); font-size:16px; color:#aaa;">
                  <?= htmlspecialchars($ext) ?> (Read Only)
                </div>
              </div>

              <div class="field">
                <label>SIP Password</label>
                <input
                  name="secret"
                  required
                  placeholder="e.g. Abc@1234"
                  value="<?= htmlspecialchars($secret) ?>"
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
                  value="<?= htmlspecialchars($calleridNumber) ?>"
                >
              </div>

              <div class="field">
                <label>Caller ID Name</label>
                <input
                  name="callerid_name"
                  maxlength="80"
                  placeholder="e.g. Rafik"
                  value="<?= htmlspecialchars($calleridName) ?>"
                >
              </div>
            </div>

            <div class="row">
              <div class="field">
                <label>Concurrent Registrations (1-10)</label>
                <select name="max_contacts">
                  <?php for($i=1; $i<=10; $i++): ?>
                    <option value="<?= $i ?>" <?= (int)$maxContacts === $i ? 'selected' : '' ?>><?= $i ?></option>
                  <?php endfor; ?>
                </select>
              </div>

              <div class="field">
                <label>Max Expiration</label>
                <input
                  type="number"
                  name="max_expiration"
                  required
                  value="<?= htmlspecialchars($maxExpiration) ?>"
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
                value="<?= htmlspecialchars($ringTime) ?>"
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
                  <option value="noo" <?= $recordMode === 'noo' ? 'selected' : '' ?>>Off</option>
                  <option value="in" <?= $recordMode === 'in' ? 'selected' : '' ?>>Incoming</option>
                  <option value="out" <?= $recordMode === 'out' ? 'selected' : '' ?>>Outgoing</option>
                  <option value="all" <?= $recordMode === 'all' ? 'selected' : '' ?>>All</option>
                </select>
              </div>

              <div class="field">
                <label>Direct Media</label>
                <select name="direct_media">
                  <option value="no" <?= !$directMedia ? 'selected' : '' ?>>Off</option>
                  <option value="yes" <?= $directMedia ? 'selected' : '' ?>>On</option>
                </select>
              </div>
            </div>

            <div class="row">
              <div class="field">
                <label>Enable Voicemail</label>
                <select name="vm_enabled" onchange="toggleVmFields(this.value)">
                  <option value="no" <?= !$vmEnabled ? 'selected' : '' ?>>Off</option>
                  <option value="yes" <?= $vmEnabled ? 'selected' : '' ?>>On</option>
                </select>
              </div>

              <div class="field" id="vm-password-field" style="<?= $vmEnabled ? 'display:block;' : 'display:none;' ?>">
                <label>Voicemail Password (digits only)</label>
                <input
                  type="text"
                  name="vm_password"
                  value="<?= htmlspecialchars($vmPassword) ?>"
                  pattern="\d+"
                  placeholder="Voicemail PIN"
                >
              </div>
            </div>

            <div class="field" style="width: 50%;">
              <label>NAT</label>
              <select name="nat">
                <option value="no" <?= !$nat ? 'selected' : '' ?>>Off</option>
                <option value="yes" <?= $nat ? 'selected' : '' ?>>On</option>
              </select>
            </div>
          </div>

          <!-- FOLLOW ME TAB -->
          <div id="tab-followme" class="tab-content" style="display:none;">
            <label>Follow Me List</label>
            <div id="followme-container">
              <!-- Populate existing rows -->
            </div>
            <button type="button" class="btn" onclick="addFollowmeRow()" style="background: rgba(0, 173, 181, 0.15); border: 1px solid rgba(0, 173, 181, 0.3); color: #00adb5; margin-top: 10px; width: auto; padding: 10px 20px;">+ Add Destination</button>
          </div>

          <div class="actions">
            <a class="btn" href="/extensions.php">BACK</a>
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

    // Populate existing Follow Me rows
    <?php foreach ($followmeList as $fm): ?>
      addFollowmeRow(<?= json_encode($fm["number"]) ?>, <?= json_encode((string)$fm["ring"]) ?>);
    <?php endforeach; ?>
  </script>
</body>
</html>
