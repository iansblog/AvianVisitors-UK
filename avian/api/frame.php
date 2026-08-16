<?php
// AvianVisitors - server-rendered collage PNG for any display size.
// GET /avian/api/frame.png?w=800&h=480&hours=24
// GET /avian/api/frame.png?w=800&h=480&today=1
// GET /avian/api/frame.png?w=800&h=480&window=today
//
// Generates the collage the frontend draws in the browser, but as a
// ready-made PNG, entirely on the server (see avian/scripts/render_collage.py,
// a Pillow port of apt.js's nesting algorithm). A display - e-ink panels in
// particular - just fetches this and refreshes. Renders are cached and only
// re-run when the birds.db changes (or after a staleness floor), so a
// polling display never pays for a fresh layout.
//
// Named `window` slots mirror the frontend picker and are what the short
// URLs map to (Caddy rewrites /1h /12h /24h /7d /today /all here):
//   1h/12h/24h   rolling hours windows
//   7d           rolling 7-day window
//   today        current local calendar day (00:00-23:59:59)
//   all          the whole life list
// `window` wins over the raw &hours=N / &today=1 parameters.
//
// Optional tunables, all validated + clamped:
//   orientation=portrait|landscape  default size when w/h omitted (480x800 / 800x480)
//   exp=0..2    count-to-size exponent (0.65 site default)
//   pad=0..6    gap between birds, in grid cells (default 1)
//   floor=0..0.5  floor rarest counts to this fraction of the max (0 = none)
//   fill=0..1   zoom the cluster so its bbox spans this fraction of the
//               viewport (default 0.9; the browser leaves a deliberately
//               airy plate that reads as wasted border on a large frame)
//   xbias=, ybias=  cluster ellipse bias (defaults follow the aspect)
//
// Served via the existing ${EXTRACTED}/avian symlink; no Caddy changes needed.
// Same default security posture as the rest of /avian/api: public on the LAN,
// gate with basic_auth in the Caddyfile if you forward it (avian/forwarding/).

declare(strict_types=1);

// PHP resolves __DIR__ through symlinks to the realpath (same note as
// birdnet-api.php). frame.php lives at $HOME/BirdNET-Pi/avian/api/.
$ROOT = dirname(__DIR__, 2);
// Cache lives beside the other PHP-FPM writable area (Extracted/cutouts):
// /avian/api/cache/* is inside the pi-owned repo, where the caddy user's
// group-write on the repo tree is not guaranteed on every install.
$CACHE_DIR = dirname(__DIR__, 3) . '/BirdSongs/Extracted/avian-frame';
$DB_PATH = "$ROOT/scripts/birds.db";
$RENDERER = "$ROOT/avian/scripts/render_collage.py";
$REGEN_SECONDS = 120;   // never regenerate more often than this...
$DB_FLOOR = 10;         // ...unless the DB changed and the cache is this old

// Locate a Python with Pillow + numpy (same fallback chain as cutout.php).
$PY = "$ROOT/avian/scripts/.venv/bin/python3";
if (!is_file($PY)) $PY = '/home/pi/avianvisitors-uk-assets/.venv/bin/python3';
if (!is_file($PY)) $PY = 'python3';
if (!is_file($RENDERER) || !is_file($PY) || !is_executable($PY)) {
    http_response_code(500);
    echo json_encode(['error' => 'renderer unavailable']);
    exit;
}

function clamp_int($v, $lo, $hi): int {
    return max($lo, min($hi, (int)$v));
}
function clamp_float($v, $lo, $hi): float {
    $f = (float)$v;
    if (is_nan($f)) return $lo;
    return max($lo, min($hi, $f));
}

// orientation=portrait|landscape picks the default size when w/h aren't given
// (the layout adapts to any aspect; explicit w/h always win). Landscape is the
// default, matching the bare short URLs.
$orient = strtolower(trim((string)($_GET['orientation'] ?? '')));
$defW = $orient === 'portrait' ? 480 : 800;
$defH = $orient === 'portrait' ? 800 : 480;
$w = clamp_int($_GET['w'] ?? $defW, 96, 1600);
$h = clamp_int($_GET['h'] ?? $defH, 96, 1600);
// Guard against a render-DoS via absurd pixel counts (e.g. 1600x1600xN).
if ($w * $h > 4096000) { $h = (int)floor(4096000 / $w); }

// Named time slots (mirror the frontend window picker). `window` wins over
// the raw &today=1 / &hours=N parameters; the default stays hours=24.
$today = false;
$hours = 24;
$window = strtolower(trim((string)($_GET['window'] ?? ''), '/'));
switch ($window) {
    case '1h':     $hours = 1;        break;
    case '12h':    $hours = 12;       break;
    case '24h':    $hours = 24;       break;
    case '7d':     $hours = 168;      break;
    case 'today':  $today = true;     break;
    case 'all':    $hours = 1000000;  break;
    default:
        $today = (int)($_GET['today'] ?? 0) === 1;
        $hours = clamp_int($_GET['hours'] ?? 24, 1, 1000000);
}

$key = $today ? "frame_{$w}x{$h}_today" : "frame_{$w}x{$h}_h{$hours}";
foreach (['exp' => [0.05, 2.0, '--count-exp'], 'floor' => [0.0, 0.5, '--floor'],
          'xbias' => [0.1, 5.0, '--xbias'], 'ybias' => [0.1, 5.0, '--ybias'],
          'fill' => [0.0, 1.0, '--fill']] as $p => $cfg) {
    if (isset($_GET[$p])) {
        $v = clamp_float($_GET[$p], $cfg[0], $cfg[1]);
        $key .= '_' . $p . (string)$v;
    }
}
if (isset($_GET['pad'])) {
    $key .= '_pad' . clamp_int($_GET['pad'], 0, 6);
}
// fill defaults to 0.9 (not the renderer's 0.9-for-CLI default confusion:
// frame.php always passes it explicitly so the cache key and the render are
// in lockstep even when the client omits the parameter).
if (!isset($_GET['fill'])) {
    $key .= '_fill0.9';
}
$cache = "$CACHE_DIR/$key.png";

$argv = $today
    ? ["--out", $cache, "--width", $w, "--height", $h, "--today"]
    : ["--out", $cache, "--width", $w, "--height", $h, "--hours", $hours];
foreach (['exp' => [0.05, 2.0, '--count-exp'], 'floor' => [0.0, 0.5, '--floor'],
          'xbias' => [0.1, 5.0, '--xbias'], 'ybias' => [0.1, 5.0, '--ybias'],
          'fill' => [0.0, 1.0, '--fill']] as $p => $cfg) {
    if (isset($_GET[$p])) {
        $v = clamp_float($_GET[$p], $cfg[0], $cfg[1]);
        $argv[] = $cfg[2];
        $argv[] = (string)$v;
    }
}
// Always pass fill so a bare URL renders the same as one with fill=0.9
// (and so the render matches the cache key above).
if (!isset($_GET['fill'])) {
    $argv[] = '--fill';
    $argv[] = '0.9';
}
if (isset($_GET['pad'])) {
    $argv[] = '--pad';
    $argv[] = (string)clamp_int($_GET['pad'], 0, 6);
}

if (!is_dir($CACHE_DIR)) {
    @mkdir($CACHE_DIR, 0775, true);
}
if (!is_dir($CACHE_DIR)) {
    http_response_code(500);
    echo json_encode(['error' => 'cache dir not writable']);
    exit;
}

$now = time();
$db_mtime = @filemtime($DB_PATH) ?: 0;
$need = true;
if (is_file($cache)) {
    $mtime = (int)filemtime($cache);
    $age = $now - $mtime;
    $need = $age > $REGEN_SECONDS || ($db_mtime > $mtime && $age > $DB_FLOOR);
}

if ($need) {
    // Serialize concurrent renders of the same key (flock), then re-check
    // staleness inside the lock so a burst of requests renders once.
    $lock = fopen("$cache.lock", 'c');
    if ($lock) {
        flock($lock, LOCK_EX);
        if (is_file($cache)) {
            $mtime = (int)filemtime($cache);
            $age = $now - $mtime;
            if (!($age > $REGEN_SECONDS || ($db_mtime > $mtime && $age > $DB_FLOOR))) {
                $need = false;
            }
        }
        if ($need) {
            $cmd = 'timeout 60 ' . escapeshellarg($PY) . ' ' . escapeshellarg($RENDERER)
                 . ' --out ' . escapeshellarg($cache);
            // argv[0..1] are --out + path (already on $cmd); emit the rest,
            // keeping the validated numeric tunables unquoted as before.
            foreach ($argv as $i => $a) {
                if ($i < 2) continue;
                if (in_array($a, ['--floor', '--exp', '--xbias', '--ybias', '--pad'], true)) {
                    $cmd .= ' ' . $a;
                } else {
                    $cmd .= ' ' . escapeshellarg((string)$a);
                }
            }
            $cmd .= ' 2>&1';
            exec($cmd, $out, $code);
            if ($code !== 0 || !is_file($cache) || filesize($cache) < 1024) {
                error_log('frame.php render failed: ' . implode("\n", $out));
                if (!is_file($cache)) {
                    http_response_code(500);
                    echo json_encode(['error' => 'render failed']);
                    flock($lock, LOCK_UN);
                    exit;
                }
                // Serve the stale cache rather than nothing.
            }
        }
        flock($lock, LOCK_UN);
        fclose($lock);
    }
}

if (!is_file($cache)) {
    http_response_code(500);
    echo json_encode(['error' => 'no image available']);
    exit;
}

header('Content-Type: image/png');
header('Content-Length: ' . (string)filesize($cache));
header('Cache-Control: public, max-age=300');
header('Last-Modified: ' . gmdate('D, d M Y H:i:s', (int)filemtime($cache)) . ' GMT');
readfile($cache);
