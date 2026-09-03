<?php
require_once __DIR__ . "/auth.php";
rcm_require_login();

$ext = trim($_GET["ext"] ?? "");
if (!preg_match('/^\d{2,6}$/', $ext)) {
    http_response_code(400);
    echo "Bad request: invalid extension";
    exit;
}

$AUTH_FILE = "/etc/asterisk/pjsip.gui.auth.conf";
$password = "—";

if (file_exists($AUTH_FILE)) {
    $lines = file($AUTH_FILE, FILE_IGNORE_NEW_LINES);
    $in = false;
    foreach ($lines as $ln) {
        $t = trim($ln);
        if ($t === "") continue;
        if (preg_match('/^\[(.+)\]$/', $t, $m)) {
            $in = ($m[1] === $ext);
            continue;
        }
        if ($in && preg_match('/^password\s*=\s*(.+)$/i', $t, $m)) {
            $password = trim($m[1]);
            break;
        }
    }
}

// Get contacts via asterisk CLI
$cmd = "asterisk -rx \"pjsip show contacts\"";
$output = shell_exec($cmd) ?? "";
$contacts = [];
foreach (explode("\n", $output) as $line) {
    $line = trim($line);
    // Contact:  <Aor>/<URI> <Status> <RTT>
    if (preg_match('/^Contact:\s+([^\s]+)\s+([^\s]+)/i', $line, $m)) {
        $contact_info = $m[1];
        $status = $m[2];
        $subparts = explode('/', $contact_info, 2);
        if (count($subparts) === 2 && $subparts[0] === $ext) {
            $uri = $subparts[1];
            $ip_port = $uri;
            if (preg_match('/sip:(.*)/', $uri, $ip_m)) {
                $ip_port = $ip_m[1];
            }
            $contacts[] = [
                'ipport' => $ip_port,
                'status' => $status
            ];
        }
    }
}
?>
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Extension Info - <?php echo htmlspecialchars($ext); ?></title>
  <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/assets/rcm.css">
  <style>
    .wrap { width: min(760px, 95vw); }
    .info-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px;
      margin-bottom: 24px;
    }
    .info-card {
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 12px;
      padding: 16px;
    }
    .info-card h4 {
      margin: 0 0 10px 0;
      color: #00adb5;
      font-family: 'Orbitron', sans-serif;
      font-size: 13px;
      letter-spacing: 1.5px;
      text-transform: uppercase;
    }
    .info-card .val {
      font-size: 18px;
      font-weight: bold;
      color: #fff;
    }
    .contacts-table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 10px;
    }
    .contacts-table th, .contacts-table td {
      padding: 10px;
      text-align: left;
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    }
    .contacts-table th {
      font-family: 'Orbitron', sans-serif;
      font-size: 11px;
      letter-spacing: 1px;
      color: rgba(255, 255, 255, 0.6);
      text-transform: uppercase;
    }
    .contacts-table td {
      color: #ccc;
    }
    .actions {
      display: flex;
      justify-content: flex-end;
      margin-top: 20px;
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="inner-box" style="margin-top: 0;">
      <h1 class="page-title">Extension Info</h1>
      <h2 style="text-align: center; color: #fff; font-family: 'Orbitron', sans-serif; margin-bottom: 24px;">
        Extension: <?php echo htmlspecialchars($ext); ?>
      </h2>

      <div class="info-grid">
        <div class="info-card">
          <h4>SIP Username</h4>
          <div class="val"><?php echo htmlspecialchars($ext); ?></div>
        </div>
        <div class="info-card">
          <h4>SIP Password</h4>
          <div class="val" style="font-family: monospace; letter-spacing: 1px;">
            <?php echo htmlspecialchars($password); ?>
          </div>
        </div>
      </div>

      <div class="panel-box" style="padding: 20px;">
        <h3 style="color: #fff; font-family: 'Orbitron', sans-serif; font-size: 15px; margin-bottom: 15px; text-transform: uppercase; letter-spacing: 1px;">
          Registered Contacts
        </h3>
        <?php if (empty($contacts)): ?>
          <div style="color: rgba(255,255,255,0.4); text-align: center; padding: 20px;">
            No registered devices found.
          </div>
        <?php else: ?>
          <table class="contacts-table">
            <thead>
              <tr>
                <th>IP Address & Port</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              <?php foreach ($contacts as $c): ?>
                <tr>
                  <td><code><?php echo htmlspecialchars($c['ipport']); ?></code></td>
                  <td>
                    <?php if (strtolower($c['status']) === 'avail'): ?>
                      <span class="badge b-green"><span class="dot d-green"></span>AVAILABLE</span>
                    <?php else: ?>
                      <span class="badge b-red"><span class="dot d-red"></span>UNAVAILABLE</span>
                    <?php endif; ?>
                  </td>
                </tr>
              <?php endforeach; ?>
            </tbody>
          </table>
        <?php endif; ?>
      </div>

      <div class="actions">
        <a class="btn" href="/extensions.php">BACK</a>
      </div>
    </div>
  </div>
</body>
</html>
