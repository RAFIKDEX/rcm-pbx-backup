<?php
require_once __DIR__ . "/auth.php";
rcm_require_login();

function clean($s){ return trim((string)$s); }

$ext            = clean($_POST["ext"] ?? "");
$secret         = clean($_POST["secret"] ?? "");
$calleridName   = clean($_POST["callerid_name"] ?? "");
if ($calleridName === "") {
    $calleridName = $ext;
}
$calleridNumber = clean($_POST["callerid_number"] ?? "");
if ($calleridNumber === "") {
    $calleridNumber = $ext;
}
$maxContacts    = clean($_POST["max_contacts"] ?? "3");
$maxExpiration  = clean($_POST["max_expiration"] ?? "120");
$ringTime       = clean($_POST["ring_time"] ?? "60");
$recordMode     = clean($_POST["record_mode"] ?? "noo");
$directMedia    = clean($_POST["direct_media"] ?? "no");
$vmEnabled      = clean($_POST["vm_enabled"] ?? "no");
$vmPassword     = clean($_POST["vm_password"] ?? "1234");
$nat            = clean($_POST["nat"] ?? "no");

$errors = [];
if (!preg_match('/^\d{2,6}$/', $ext)) $errors[] = "Invalid extension";
if ($secret === "") $errors[] = "Secret is required";
if (!preg_match('/^[0-9+*#]{2,20}$/', $calleridNumber)) $errors[] = "Invalid Caller ID number";
if (!preg_match('/^\d+$/', $maxContacts) || (int)$maxContacts < 1 || (int)$maxContacts > 10) $errors[] = "Invalid concurrent registrations (must be 1-10)";
if (!preg_match('/^\d+$/', $maxExpiration)) $errors[] = "Invalid max expiration";
if (!preg_match('/^\d+$/', $ringTime)) $errors[] = "Invalid ring time";
if (!in_array($recordMode, ["in","out","noo","all"], true)) $errors[] = "Invalid record mode";
if ($vmEnabled === "yes" && !preg_match('/^\d+$/', $vmPassword)) $errors[] = "Voicemail password must be digits only";

// Follow Me
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

$out = "";
$ok = false;

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
        "vm_enabled" => $vmEnabled === "yes",
        "vm_password" => $vmPassword,
        "direct_media" => $directMedia === "yes",
        "nat" => $nat === "yes",
        "followme" => $followmeRows
    ]);

    $cmd = "sudo /usr/local/bin/rcm_add_ext.sh";
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
    } else {
        $errors[] = "Failed to run add extension script";
    }
}
?>
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Save Extension</title>
  <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/assets/rcm.css">
  <style>
    .wrap{ width:min(760px, 94vw); }
    .box{
      background:rgba(255,255,255,0.10);
      border:1px solid rgba(255,255,255,0.18);
      border-radius:18px;
      padding:14px;
      margin-top:14px;
      white-space:pre-wrap;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      font-size:13px;
      opacity:.95;
    }
    .actions{
      display:flex;
      gap:12px;
      justify-content:center;
      margin-top:18px;
      flex-wrap:wrap;
    }
    .ok{color:#b8ffcc;font-weight:900;text-align:center}
    .bad{color:#ffd0d0;font-weight:900;text-align:center}
    ul{margin:10px 0 0 18px}
    .summary{
      display:grid;
      grid-template-columns:1fr 1fr;
      gap:12px;
      margin-top:14px;
    }
    .summary .pill{display:block;text-align:center}
    @media (max-width: 640px){ .summary{ grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="inner-box" style="margin-top:0;">
      <h1 class="page-title">RESULT</h1>

      <?php if ($errors): ?>
        <div class="bad">FAILED</div>
        <ul>
          <?php foreach($errors as $e): ?>
            <li><?php echo htmlspecialchars($e); ?></li>
          <?php endforeach; ?>
        </ul>
      <?php else: ?>
        <?php if ($ok): ?>
          <div class="ok">SUCCESS</div>
        <?php else: ?>
          <div class="bad">FAILED</div>
        <?php endif; ?>

        <div class="summary">
          <div class="pill">Extension: <?php echo htmlspecialchars($ext); ?></div>
          <div class="pill">Caller ID: <?php echo htmlspecialchars($calleridName . ' <' . $calleridNumber . '>'); ?></div>
        </div>

        <div class="box"><?php echo htmlspecialchars($out ?: "No output"); ?></div>
      <?php endif; ?>

      <div class="actions">
        <a class="btn" href="/add_extension.php">ADD ANOTHER</a>
        <a class="btn" href="/extensions.php">EXTENSIONS</a>
        <a class="btn" href="/dashboard.php">DASHBOARD</a>
      </div>
    </div>
  </div>
</body>
</html>
