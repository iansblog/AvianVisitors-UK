<?php
// AvianVisitors - bird image resolver.
//
// Lookup chain for /avian/api/cutout.php?sci=Calypte+anna:
//   1. ../assets/illustrations/<slug>.png   (bundled kachō-e renders)
//   2. ../assets/cutouts/<slug>.png         (background-removed photo)
//   3. cached rembg of a Wikipedia photo at $HOME/BirdSongs/Extracted/cutouts/
//   4. fresh Wikipedia -> rembg -> cache (skipped if rembg-cli missing)
// 5. AI-generated illustration via free.ai (with retry + rate-limit backoff)
//
// The frontend's <img src> points here for every species - bundled
// hits return instantly; cold misses fall through to the dynamic path.
//
// On-demand steps 4-5 (Wikipedia + rembg, and AI generation) are gated by
// GENERATE_ILLUSTRATIONS in birdnet.conf. The installer sets it to 0 on
// low-RAM boards (Pi 3, Zero 2W) where rembg could OOM the system.
//
// Default LAN deploy ships without auth. To expose publicly, gate
// /avian/api/* with basic_auth in your Caddyfile - see avian/forwarding/.

declare(strict_types=1);

$sci = trim((string)($_GET['sci'] ?? ''));
if ($sci === '') {
    http_response_code(400);
    echo 'sci required';
    exit;
}
// Binomial / trinomial pattern. Rejects path-traversal payloads and
// junk before any filesystem or upstream lookup.
if (!preg_match('/^[A-Za-z]{2,40}(?:[ ][a-z]{2,40}){1,3}$/', $sci)) {
    http_response_code(400);
    echo 'invalid sci';
    exit;
}

// Slugify scientific name for filename + cache key.
$slug = preg_replace('/[^a-z0-9]+/', '-', strtolower($sci));
$slug = trim((string)$slug, '-');

// pose=1 (default) is perched. pose=2 is flight. Clamp to a two-digit
// positive integer so a malformed ?pose= can't break the path.
$pose = (int)($_GET['pose'] ?? 1);
if ($pose < 1 || $pose > 99) $pose = 1;
$poseSuffix = $pose === 1 ? '' : "-$pose";

function serve_png(string $path): void {
    header('Content-Type: image/png');
    header('Cache-Control: public, max-age=86400');
    header('Content-Length: ' . (string)filesize($path));
    readfile($path);
    exit;
}

// 1. Bundled illustration with pose suffix (the kachō-e PNG the repo
//    ships with). Species cover both perched + flight.
$bundled = dirname(__DIR__) . "/assets/illustrations/{$slug}{$poseSuffix}.png";
if (is_file($bundled) && filesize($bundled) > 1024) {
    serve_png($bundled);
}
// Pose-2 missing? Fall back to pose-1 so the flight tab still shows
// the perched render instead of breaking to the photo fallback.
if ($pose !== 1) {
    $fallback = dirname(__DIR__) . "/assets/illustrations/$slug.png";
    if (is_file($fallback) && filesize($fallback) > 1024) {
        serve_png($fallback);
    }
}
// 2. Bundled cutout (background-removed photo, fallback for species
//    without an illustration).
$cutout = dirname(__DIR__) . "/assets/cutouts/$slug.png";
if (is_file($cutout) && filesize($cutout) > 1024) {
    serve_png($cutout);
}

// 3. Dynamic cache from a previous Wikipedia + rembg run.
$cacheDir = dirname(__DIR__, 3) . '/BirdSongs/Extracted/cutouts';
$cachePath = "$cacheDir/$slug.png";
if (is_file($cachePath) && filesize($cachePath) > 1024) {
    serve_png($cachePath);
}

// On-demand fallback steps (4 + 5) can be disabled from birdnet.conf via
// GENERATE_ILLUSTRATIONS (the installer turns it off on low-RAM boards).
$genEnabled = true;
$confPath = dirname(__DIR__, 2) . '/birdnet.conf';
if (is_readable($confPath)) {
    foreach (file($confPath, FILE_IGNORE_NEW_LINES) as $line) {
        if (str_starts_with($line, 'GENERATE_ILLUSTRATIONS=')) {
            $genEnabled = (int)trim(substr($line, strlen('GENERATE_ILLUSTRATIONS='))) === 1;
            break;
        }
    }
}

// 4. Fresh Wikipedia fetch + rembg. Only if rembg-cli is available and
//    on-demand generation is enabled.
$rembg = '/usr/local/bin/rembg-cli';
if ($genEnabled && is_executable($rembg)) {
    if (!is_dir($cacheDir)) @mkdir($cacheDir, 0755, true);

    $ua = getenv('AV_USER_AGENT') ?: 'AvianVisitors/1.0 (+https://github.com/Twarner491/AvianVisitors)';
    $ctx = stream_context_create([
        'http' => ['header' => "User-Agent: $ua\r\n", 'timeout' => 12],
    ]);
    $wpUrl = 'https://en.wikipedia.org/api/rest_v1/page/summary/' . rawurlencode($sci);
    $wpJson = @file_get_contents($wpUrl, false, $ctx);
    $srcUrl = null;
    if ($wpJson !== false) {
        $j = json_decode($wpJson, true);
        $srcUrl = $j['originalimage']['source'] ?? $j['thumbnail']['source'] ?? null;
    }
    // Defensive: only follow URLs on Wikimedia / Wikipedia hosts so a
    // poisoned summary endpoint can't redirect us to arbitrary servers.
    if ($srcUrl !== null) {
        $host = parse_url((string)$srcUrl, PHP_URL_HOST) ?: '';
        if (!preg_match('/(?:^|\.)(?:wikimedia\.org|wikipedia\.org)$/i', $host)) {
            $srcUrl = null;
        }
    }
    if ($srcUrl) {
        $imgBytes = @file_get_contents($srcUrl, false, $ctx);
        if ($imgBytes && strlen($imgBytes) >= 1024) {
            // rembg via the wrapper. u2netp = lightweight model (~50MB peak RAM).
            $tmpInBase  = tempnam(sys_get_temp_dir(), 'rembg-in-');
            $tmpOutBase = tempnam(sys_get_temp_dir(), 'rembg-out-');
            @unlink($tmpInBase); @unlink($tmpOutBase);
            $tmpIn  = $tmpInBase  . '.jpg';
            $tmpOut = $tmpOutBase . '.png';
            file_put_contents($tmpIn, $imgBytes);

            $cmd = sprintf(
                '%s i -m u2netp -ppm %s %s 2>&1',
                escapeshellarg($rembg),
                escapeshellarg($tmpIn),
                escapeshellarg($tmpOut)
            );
            $out = shell_exec($cmd);
            @unlink($tmpIn);

            if (is_file($tmpOut) && filesize($tmpOut) > 1024) {
                // Tight-crop + downscale to 800px max edge.
                $im = @imagecreatefrompng($tmpOut);
                if ($im !== false) {
                    $cropped = @imagecropauto($im, IMG_CROP_TRANSPARENT);
                    if ($cropped !== false) {
                        imagedestroy($im);
                        $im = $cropped;
                    }
                    $w = imagesx($im); $h = imagesy($im);
                    $max = 800;
                    if ($w > $max || $h > $max) {
                        $scale = $max / max($w, $h);
                        $nw = (int)($w * $scale); $nh = (int)($h * $scale);
                        $resized = imagecreatetruecolor($nw, $nh);
                        imagealphablending($resized, false);
                        imagesavealpha($resized, true);
                        imagecopyresampled($resized, $im, 0, 0, 0, 0, $nw, $nh, $w, $h);
                        imagedestroy($im);
                        $im = $resized;
                    }
                    imagealphablending($im, false);
                    imagesavealpha($im, true);
                    imagepng($im, $tmpOut, 6);
                    imagedestroy($im);
                }
                @rename($tmpOut, $cachePath);
                serve_png($cachePath);
            }
            @unlink($tmpOut);
        }
    }
}

// 5. AI-generated illustration via free.ai. Generates a kachō-e style
//    bird on cream background, removes background with rembg, caches.
//    Long timeout (120s) because generation is slow; generous retry
//    backoff respects free.ai rate limits.
$genScript = dirname(__DIR__) . "/scripts/generate_bird.py";
// Locate a Python with rembg installed. The installer creates
// avian/scripts/.venv; fall back to python3 on PATH (no rembg = degrade).
$python = dirname(__DIR__) . '/scripts/.venv/bin/python3';
if (!is_file($python)) $python = '/home/pi/avianvisitors-uk-assets/.venv/bin/python3';
if (!is_file($python)) $python = 'python3';
if ($genEnabled && is_file($genScript) && is_executable($genScript)) {
    if (!is_dir($cacheDir)) @mkdir($cacheDir, 0755, true);

    $com = str_replace('_', ' ', $sci);  // fallback common name = latinised
    // Try to get common name from the frontend's labels or request param
    $comParam = trim((string)($_GET['com'] ?? ''));
    if ($comParam !== '') {
        $com = $comParam;
    }

    $cmd = sprintf(
        '%s %s %s %s %s 2>&1',
        escapeshellarg($python),
        escapeshellarg($genScript),
        escapeshellarg($sci),
        escapeshellarg($com),
        escapeshellarg($cachePath)
    );
    $out = shell_exec($cmd);

    if (is_file($cachePath) && filesize($cachePath) > 1024) {
        serve_png($cachePath);
    }
    error_log("generate_bird.py failed for $sci: " . ($out ?? '(no output)'));
}

http_response_code(404);
echo 'no illustration for ' . htmlspecialchars($sci);
