<?php
declare(strict_types=1);

const SITE = 'https://timetable.pallada.sibsau.ru';
const TIMEOUT = 20;
const TOKEN = '';
const CACHE_TTL = 3600;
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    . '(KHTML, like Gecko) Chrome/120.0 Safari/537.36';

const WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'];

date_default_timezone_set('Asia/Krasnoyarsk');

const ADMIN_SESSION_TTL = 86400;
const ADMIN_MAX_FAILS = 5;
const ADMIN_LOCK_SECONDS = 600;
const BOT_NOTIFY_URL = '';
const BOT_NOTIFY_TOKEN = '';

function request_is_https(): bool
{
    if (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') {
        return true;
    }
    if (($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https') {
        return true;
    }
    return ($_SERVER['SERVER_PORT'] ?? '') === '443';
}

function send(int $status, string $body, string $type, string $cache = 'no-store'): void
{
    http_response_code($status);
    header('Content-Type: ' . $type);
    header('Cache-Control: ' . $cache);
    header('X-Content-Type-Options: nosniff');
    header('Referrer-Policy: strict-origin-when-cross-origin');
    header('X-Frame-Options: SAMEORIGIN');
    header('Permissions-Policy: geolocation=(), microphone=(), camera=()');
    if (request_is_https()) {
        header('Strict-Transport-Security: max-age=31536000');
    }
    if (stripos($type, 'application/json') !== false) {
        header("Content-Security-Policy: default-src 'none'; frame-ancestors 'self'");
    }
    echo $body;
    exit;
}

function fail(string $message, int $status = 502): void
{
    $body = json_encode(['error' => $message], JSON_UNESCAPED_UNICODE);
    send($status, $body === false ? '{"error":"encode"}' : $body, 'application/json; charset=utf-8');
}

function request(string $url, array $options = []): array
{
    $defaults = [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_HEADER => true,
        CURLOPT_FOLLOWLOCATION => false,
        CURLOPT_CONNECTTIMEOUT => TIMEOUT,
        CURLOPT_TIMEOUT => TIMEOUT,
        CURLOPT_USERAGENT => UA,
        CURLOPT_SSL_VERIFYPEER => true,
        CURLOPT_HTTPHEADER => ['Accept-Language: ru-RU,ru;q=0.9'],
    ];

    $handle = curl_init($url);
    curl_setopt_array($handle, array_replace($defaults, $options));
    $raw = curl_exec($handle);
    if ($raw === false) {
        $message = curl_error($handle);
        curl_close($handle);
        throw new RuntimeException($message);
    }
    $info = curl_getinfo($handle);
    curl_close($handle);

    $headerSize = (int) $info['header_size'];
    return [
        'status' => (int) $info['http_code'],
        'headers' => substr($raw, 0, $headerSize),
        'body' => substr($raw, $headerSize),
    ];
}

function header_value(string $headers, string $name): string
{
    if (preg_match('/^' . preg_quote($name, '/') . ':\s*(.+)$/mi', $headers, $match)) {
        return trim($match[1]);
    }
    return '';
}

function site_search(string $query): array
{
    $payload = json_encode([
        'jsonrpc' => '2.0',
        'method' => 'call',
        'params' => ['query' => $query],
        'id' => 1,
    ]);
    $result = request(SITE . '/ajax/search_schedule', [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => $payload,
        CURLOPT_HTTPHEADER => [
            'Content-Type: application/json',
            'Accept-Language: ru-RU,ru;q=0.9',
        ],
    ]);
    $decoded = json_decode($result['body'], true);
    $raw = $decoded['result'] ?? null;
    if (!is_string($raw)) {
        return [];
    }
    $items = json_decode($raw, true);
    if (!is_array($items)) {
        return [];
    }
    $out = [];
    foreach ($items as $item) {
        if (!isset($item['id'], $item['name'])) {
            continue;
        }
        $out[] = ['id' => (int) $item['id'], 'name' => clean_text((string) $item['name'])];
    }
    return $out;
}

function site_page_id(int $searchId, string $query, string $kind = 'group'): int
{
    $cookies = tempnam(sys_get_temp_dir(), 'tt');
    try {
        $page = request(SITE . '/timetable/', [
            CURLOPT_COOKIEJAR => $cookies,
            CURLOPT_COOKIEFILE => $cookies,
            CURLOPT_FOLLOWLOCATION => true,
        ]);
        if (!preg_match('/name="csrf_token"[^>]*value="([^"]+)"/', $page['body'], $match)) {
            fail('не удалось получить csrf_token');
        }
        $posted = request(SITE . '/timetable', [
            CURLOPT_POST => true,
            CURLOPT_POSTFIELDS => http_build_query([
                'query' => $query,
                'id' => $searchId,
                'csrf_token' => $match[1],
            ]),
            CURLOPT_COOKIEJAR => $cookies,
            CURLOPT_COOKIEFILE => $cookies,
        ]);
    } finally {
        if (is_string($cookies)) {
            @unlink($cookies);
        }
    }

    $location = header_value($posted['headers'], 'Location');
    if (!preg_match('#/timetable/' . $kind . '/(\d+)#', $location, $found)) {
        if ($kind === 'group' && strpos($location, '/professor/') !== false) {
            fail('это преподаватель, а не группа', 400);
        }
        if ($kind === 'professor' && strpos($location, '/group/') !== false) {
            fail('это группа, а не преподаватель', 400);
        }
        fail('сайт не сообщил страницу');
    }
    return (int) $found[1];
}

function site_page(int $pageId, string $kind = 'group'): string
{
    $result = request(SITE . '/timetable/' . $kind . '/' . $pageId);
    if ($result['status'] !== 200) {
        fail('сайт вернул код ' . $result['status']);
    }
    return $result['body'];
}

function clean_text(string $value): string
{
    $value = str_replace("\xC2\xA0", ' ', $value);
    $collapsed = preg_replace('/\s+/u', ' ', $value);
    return trim($collapsed === null ? $value : $collapsed);
}

function normalize_query(string $query): string
{
    $compact = preg_replace('/\s+/u', '', trim($query));
    if ($compact === null || $compact === '' || !preg_match('/\d/', $compact)) {
        return $query;
    }
    if (!preg_match('/^[\dA-Za-zА-Яа-яЁё-]+$/u', $compact)) {
        return $query;
    }
    if (preg_match('/^([A-Za-zА-Яа-яЁё]+)(\d{2})(\d{2})$/', $compact, $match)) {
        return $match[1] . $match[2] . '-' . $match[3];
    }
    return $compact;
}

function cls(string $name): string
{
    return "contains(concat(' ', normalize-space(@class), ' '), ' " . $name . " ')";
}

function parse_lesson(DOMElement $ul): array
{
    $subject = '';
    $type = '';
    $room = '';
    $subgroup = 'все';
    $teachers = [];
    $xpath = new DOMXPath($ul->ownerDocument);

    $nameNode = $xpath->query(".//span[" . cls('name') . "]", $ul)->item(0);
    if ($nameNode) {
        $subject = clean_text($nameNode->textContent);
        if (preg_match('/\(([^)]*)\)/u', clean_text($ul->textContent), $match)) {
            $type = clean_text($match[1]);
        }
    }

    foreach ($xpath->query(".//li[.//i[" . cls('fa-user') . " or " . cls('fa-group') . "]]//a", $ul) as $link) {
        $name = clean_text($link->textContent);
        if ($name === '') {
            continue;
        }
        $linkId = null;
        if (preg_match('#/timetable/(?:professor|group)/(\d+)#', $link->getAttribute('href'), $match)) {
            $linkId = (int) $match[1];
        }
        $teachers[] = ['name' => $name, 'id' => $linkId];
    }

    $roomNode = $xpath->query(".//li[.//i[" . cls('fa-compass') . "]]//a", $ul)->item(0);
    if ($roomNode) {
        $room = clean_text($roomNode->textContent);
    }

    $subgroupNode = $xpath->query(".//li[" . cls('num_pdgrp') . "]", $ul)->item(0);
    if ($subgroupNode) {
        $subgroup = clean_text($subgroupNode->textContent);
    } else {
        $clipNode = $xpath->query(".//li[.//i[" . cls('fa-paperclip') . "]]", $ul)->item(0);
        if ($clipNode) {
            $subgroup = clean_text($clipNode->textContent);
        }
    }

    $names = array_map(static fn (array $item): string => $item['name'], $teachers);

    return [
        'time' => '',
        'subject' => $subject,
        'type' => $type,
        'teacher' => implode(', ', $names),
        'teachers' => $teachers,
        'room' => $room,
        'subgroup' => $subgroup,
    ];
}

function parse_dated(DOMXPath $xpath, string $tabId): array
{
    $items = [];
    $panel = $xpath->query("//div[@id='" . $tabId . "']")->item(0);
    if (!$panel) {
        return $items;
    }
    foreach ($xpath->query(".//div[" . cls('day') . "]", $panel) as $day) {
        $header = $xpath->query(".//div[contains(@class,'header')]", $day)->item(0);
        $headerText = $header ? clean_text($header->textContent) : '';
        if (!preg_match('/(\d{2}\.\d{2}\.\d{4})/u', $headerText, $match)) {
            continue;
        }
        $date = $match[1];

        foreach ($xpath->query(".//div[" . cls('body') . "]//div[" . cls('line') . "]", $day) as $line) {
            $timeNode = $xpath->query(".//div[" . cls('time') . "]", $line)->item(0);
            $timeText = $timeNode ? clean_text($timeNode->textContent) : '';
            $time = '';
            if (preg_match('/\d{1,2}:\d{2}/u', $timeText, $match)) {
                $time = $match[0];
            }
            foreach ($xpath->query(".//ul[" . cls('list-unstyled') . "]", $line) as $ul) {
                $lesson = parse_lesson($ul);
                if ($lesson['subject'] === '') {
                    continue;
                }
                $items[] = [
                    'date' => $date,
                    'time' => $time,
                    'subject' => $lesson['subject'],
                    'type' => $lesson['type'],
                    'teacher' => $lesson['teacher'],
                    'teachers' => $lesson['teachers'],
                    'room' => $lesson['room'],
                ];
            }
        }
    }
    return $items;
}

function parse_document(string $html): DOMXPath
{
    $document = new DOMDocument();
    libxml_use_internal_errors(true);
    $document->loadHTML('<?xml encoding="utf-8" ?>' . $html);
    libxml_clear_errors();
    return new DOMXPath($document);
}

function parse_consultation_weeks(DOMXPath $xpath, ?string $refDate, ?int $refWeek): array
{
    $items = [];
    $panel = $xpath->query("//div[@id='consultation_tab']")->item(0);
    if (!$panel) {
        return $items;
    }

    $monday = null;
    if ($refDate) {
        $parsed = DateTime::createFromFormat('Y-m-d', $refDate);
        if ($parsed) {
            $parsed->modify('-' . ((int) $parsed->format('N') - 1) . ' days');
            $monday = $parsed;
        }
    }

    foreach ($xpath->query(".//div[starts-with(@id,'cs_week_') and contains(@id,'_tab')]", $panel) as $weekPanel) {
        if (!preg_match('/^cs_week_(\d+)_tab$/', $weekPanel->getAttribute('id'), $match)) {
            continue;
        }
        $weekNo = (int) $match[1];

        foreach ($xpath->query(".//div[" . cls('day') . "]", $weekPanel) as $day) {
            $classes = preg_split('/\s+/', $day->getAttribute('class'), -1, PREG_SPLIT_NO_EMPTY);
            $weekdayIndex = null;
            foreach (WEEKDAYS as $index => $candidate) {
                if (in_array($candidate, $classes, true)) {
                    $weekdayIndex = $index;
                    break;
                }
            }
            if ($weekdayIndex === null) {
                continue;
            }

            $date = '';
            if ($monday !== null && $refWeek !== null) {
                $moment = clone $monday;
                $moment->modify((($weekNo - $refWeek) * 7 + $weekdayIndex) . ' days');
                $date = $moment->format('d.m.Y');
            }

            foreach ($xpath->query(".//div[" . cls('body') . "]//div[" . cls('line') . "]", $day) as $line) {
                $timeNode = $xpath->query(".//div[" . cls('time') . "]", $line)->item(0);
                $timeText = $timeNode ? clean_text($timeNode->textContent) : '';
                $time = '';
                if (preg_match('/\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}/u', $timeText, $match)) {
                    $time = str_replace(' ', '', $match[0]);
                } elseif (preg_match('/\d{1,2}:\d{2}/u', $timeText, $match)) {
                    $time = $match[0];
                }

                $subject = '';
                $nameNode = $xpath->query(".//span[" . cls('name') . "]", $line)->item(0);
                if ($nameNode) {
                    $subject = clean_text($nameNode->textContent);
                }

                $roomNode = $xpath->query(".//li[.//i[" . cls('fa-compass') . "]]//a", $line)->item(0);
                $room = $roomNode ? clean_text($roomNode->textContent) : '';

                $names = [];
                foreach ($xpath->query(".//li[.//i[" . cls('fa-user') . " or " . cls('fa-group') . "]]//a", $line) as $link) {
                    $label = clean_text($link->textContent);
                    if ($label !== '') {
                        $names[] = $label;
                    }
                }

                if ($time === '' && $room === '' && $subject === '') {
                    continue;
                }

                $items[] = [
                    'date' => $date,
                    'time' => $time,
                    'subject' => $subject === '' ? 'Консультация' : $subject,
                    'type' => $subject === '' ? '' : 'Консультация',
                    'teacher' => implode(', ', $names),
                    'teachers' => [],
                    'room' => $room,
                    'weekday' => WEEKDAYS[$weekdayIndex],
                    'week' => $weekNo,
                ];
            }
        }
    }

    return $items;
}

function parse_consultations(string $html): array
{
    $xpath = parse_document($html);

    $refDate = null;
    $refWeek = null;
    $subtitle = $xpath->query("//h4[" . cls('bold') . "]")->item(0);
    if ($subtitle) {
        $raw = clean_text($subtitle->textContent);
        if (preg_match('/(\d{2}\.\d{2}\.\d{4})\s*-\s*(\d+)\s*недел/u', $raw, $match)) {
            $parsed = DateTime::createFromFormat('d.m.Y', $match[1]);
            $refDate = $parsed ? $parsed->format('Y-m-d') : null;
            $refWeek = (int) $match[2];
        }
    }

    return parse_consultation_weeks($xpath, $refDate, $refWeek);
}

function request_many(array $urls, int $limit = 8, int $timeout = 20): array
{
    $results = [];
    $keys = array_keys($urls);
    $total = count($keys);

    for ($offset = 0; $offset < $total; $offset += $limit) {
        $batch = array_slice($keys, $offset, $limit);
        $multi = curl_multi_init();
        $handles = [];
        foreach ($batch as $key) {
            $handle = curl_init($urls[$key]);
            curl_setopt_array($handle, [
                CURLOPT_RETURNTRANSFER => true,
                CURLOPT_FOLLOWLOCATION => true,
                CURLOPT_CONNECTTIMEOUT => $timeout,
                CURLOPT_TIMEOUT => $timeout,
                CURLOPT_USERAGENT => UA,
                CURLOPT_SSL_VERIFYPEER => true,
            ]);
            curl_multi_add_handle($multi, $handle);
            $handles[$key] = $handle;
        }

        $running = null;
        do {
            curl_multi_exec($multi, $running);
            if ($running > 0) {
                curl_multi_select($multi, 1.0);
            }
        } while ($running > 0);

        foreach ($handles as $key => $handle) {
            $body = curl_multi_getcontent($handle);
            $results[$key] = is_string($body) ? $body : '';
            curl_multi_remove_handle($multi, $handle);
            curl_close($handle);
        }
        curl_multi_close($multi);
    }

    return $results;
}

function parse_schedule(string $html, string $kind = 'group'): array
{
    $xpath = parse_document($html);

    $groupName = '';
    $semester = '';
    $refDate = null;
    $refWeek = null;

    $title = $xpath->query("//h3[" . cls('bold') . "]")->item(0);
    if ($title) {
        $raw = clean_text($title->textContent);
        if (preg_match('/["«“]\s*([^"»”]+?)\s*["»”]/u', $raw, $match)) {
            $groupName = clean_text($match[1]);
        }
        if (preg_match('/(\d+\s*семестр[^(]*)/u', $raw, $match)) {
            $semester = clean_text($match[1]);
        }
        if ($kind === 'professor') {
            $groupName = clean_text(preg_replace('/\s*-\s*\d{4}\s*\/\s*\d{4}.*$/u', '', $raw));
        }
    }

    $subtitle = $xpath->query("//h4[" . cls('bold') . "]")->item(0);
    if ($subtitle) {
        $raw = clean_text($subtitle->textContent);
        if (preg_match('/(\d{2}\.\d{2}\.\d{4})\s*-\s*(\d+)\s*недел/u', $raw, $match)) {
            $parsed = DateTime::createFromFormat('d.m.Y', $match[1]);
            $refDate = $parsed ? $parsed->format('Y-m-d') : null;
            $refWeek = (int) $match[2];
        }
    }

    $weeks = [];
    foreach ($xpath->query("//div[starts-with(@id,'week_') and contains(@id,'_tab')]") as $panel) {
        if (!preg_match('/^week_(\d+)_tab$/', $panel->getAttribute('id'), $weekMatch)) {
            continue;
        }
        $weekNo = $weekMatch[1];
        $days = array_fill_keys(WEEKDAYS, []);

        foreach ($xpath->query(".//div[" . cls('day') . "]", $panel) as $day) {
            $classes = preg_split('/\s+/', $day->getAttribute('class'), -1, PREG_SPLIT_NO_EMPTY);
            $weekday = null;
            foreach (WEEKDAYS as $candidate) {
                if (in_array($candidate, $classes, true)) {
                    $weekday = $candidate;
                    break;
                }
            }
            if ($weekday === null) {
                continue;
            }

            foreach ($xpath->query(".//div[" . cls('body') . "]//div[" . cls('line') . "]", $day) as $line) {
                $timeNode = $xpath->query(".//div[" . cls('time') . "]", $line)->item(0);
                $timeText = $timeNode ? clean_text($timeNode->textContent) : '';
                $time = '';
                if (preg_match('/\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}/u', $timeText, $match)) {
                    $time = str_replace(' ', '', $match[0]);
                }
                foreach ($xpath->query(".//ul[" . cls('list-unstyled') . "]", $line) as $ul) {
                    $lesson = parse_lesson($ul);
                    if ($lesson['subject'] === '') {
                        continue;
                    }
                    $lesson['time'] = $time;
                    $days[$weekday][] = $lesson;
                }
            }
        }
        $weeks[$weekNo] = $days;
    }

    $exams = parse_dated($xpath, 'session_tab');
    $consultations = parse_consultation_weeks($xpath, $refDate, $refWeek);

    return [
        'kind' => $kind,
        'group' => ['name' => $groupName],
        'semester' => $semester,
        'ref' => ['date' => $refDate, 'week' => $refWeek],
        'weeks' => $weeks,
        'exams' => $exams,
        'consultations' => $consultations,
        'updated' => date('c'),
    ];
}

function visit_stats(string $kind = '', string $name = ''): array
{
    $path = cache_file('visits');
    $dir = dirname($path);
    if (!is_dir($dir)) {
        @mkdir($dir, 0755, true);
    }

    $empty = ['total' => 0, 'today' => 0, 'days' => [], 'kinds' => [], 'targets' => []];
    $handle = @fopen($path, 'c+');
    if ($handle === false) {
        return $empty;
    }

    flock($handle, LOCK_EX);
    $raw = stream_get_contents($handle);
    $data = json_decode((string) $raw, true);
    if (!is_array($data)) {
        $data = [];
    }
    $data['total'] = (int) ($data['total'] ?? 0);
    $data['days'] = is_array($data['days'] ?? null) ? $data['days'] : [];
    $data['kinds'] = is_array($data['kinds'] ?? null) ? $data['kinds'] : [];
    $data['targets'] = is_array($data['targets'] ?? null) ? $data['targets'] : [];

    if ($kind !== '') {
        $day = date('Y-m-d');
        $data['total']++;
        $data['days'][$day] = (int) ($data['days'][$day] ?? 0) + 1;
        $data['kinds'][$kind] = (int) ($data['kinds'][$kind] ?? 0) + 1;
        if ($name !== '') {
            $key = $kind . '|' . $name;
            $data['targets'][$key] = (int) ($data['targets'][$key] ?? 0) + 1;
        }
        rewind($handle);
        ftruncate($handle, 0);
        fwrite($handle, (string) json_encode($data, JSON_UNESCAPED_UNICODE));
        fflush($handle);
    }

    flock($handle, LOCK_UN);
    fclose($handle);

    $data['today'] = (int) ($data['days'][date('Y-m-d')] ?? 0);
    return $data;
}

function cache_file(string $key): string
{
    $safe = preg_replace('/[^a-z0-9\-]/i', '', $key);
    return __DIR__ . '/cache/' . ($safe === null ? 'item' : $safe) . '.json';
}

function cache_get(string $key, int $ttl = CACHE_TTL): ?array
{
    $file = cache_file($key);
    if (!is_file($file) || time() - filemtime($file) > $ttl) {
        return null;
    }
    $raw = file_get_contents($file);
    if ($raw === false) {
        return null;
    }
    $data = json_decode($raw, true);
    return is_array($data) ? $data : null;
}

function cache_put(string $key, array $data): void
{
    $dir = __DIR__ . '/cache';
    if (!is_dir($dir)) {
        @mkdir($dir, 0755, true);
    }
    @file_put_contents(cache_file($key), json_encode($data, JSON_UNESCAPED_UNICODE));
}

function teacher_cache_path(): string
{
    return __DIR__ . '/cache/teachers.json';
}

function teacher_cache(): array
{
    $file = teacher_cache_path();
    if (!is_file($file)) {
        return [];
    }
    $raw = file_get_contents($file);
    if ($raw === false) {
        return [];
    }
    $data = json_decode($raw, true);
    return is_array($data) ? $data : [];
}

function teacher_cache_save(array $data): void
{
    $dir = __DIR__ . '/cache';
    if (!is_dir($dir)) {
        @mkdir($dir, 0755, true);
    }
    @file_put_contents(teacher_cache_path(), json_encode($data, JSON_UNESCAPED_UNICODE));
}

function teacher_key(string $short, $id): string
{
    return $short . '|' . ($id === null ? 0 : (int) $id);
}

function resolve_teacher_name(array &$cache, string $short, $id): string
{
    $key = teacher_key($short, $id);
    if (array_key_exists($key, $cache)) {
        return $cache[$key] === '' ? $short : $cache[$key];
    }

    $parts = preg_split('/\s+/u', trim(str_replace('.', ' ', $short)), -1, PREG_SPLIT_NO_EMPTY);
    if (!$parts) {
        $cache[$key] = '';
        return $short;
    }

    $surname = $parts[0];
    $initials = [];
    for ($index = 1; $index < count($parts); $index++) {
        $initials[] = mb_substr($parts[$index], 0, 1);
    }

    $query = $surname . (count($initials) ? ' ' . $initials[0] : '');
    $candidates = [];
    try {
        foreach (site_search($query) as $item) {
            $words = preg_split('/\s+/u', $item['name'], -1, PREG_SPLIT_NO_EMPTY);
            if (count($words) < 1 + count($initials)) {
                continue;
            }
            if (mb_strtolower($words[0]) !== mb_strtolower($surname)) {
                continue;
            }
            $matches = true;
            for ($index = 0; $index < count($initials); $index++) {
                if (mb_strtoupper(mb_substr($words[$index + 1], 0, 1)) !== mb_strtoupper($initials[$index])) {
                    $matches = false;
                    break;
                }
            }
            if ($matches) {
                $candidates[] = $item;
            }
        }
    } catch (Throwable $error) {
        return $short;
    }

    $full = '';
    if (count($candidates) === 1) {
        $full = $candidates[0]['name'];
    } elseif (count($candidates) > 1 && $id !== null) {
        foreach ($candidates as $candidate) {
            try {
                $page = site_page_id((int) $candidate['id'], $candidate['name'], 'professor');
            } catch (Throwable $error) {
                $page = null;
            }
            if ($page !== null && $page === (int) $id) {
                $full = $candidate['name'];
                break;
            }
        }
    }

    $cache[$key] = $full;
    return $full === '' ? $short : $full;
}

function apply_teacher_names(array $data, array &$cache, bool $resolve): array
{
    $apply = static function (array $items) use (&$cache, $resolve): array {
        foreach ($items as $index => $item) {
            if (!isset($item['teachers']) || !is_array($item['teachers'])) {
                continue;
            }
            foreach ($item['teachers'] as $position => $teacher) {
                $short = (string) $teacher['name'];
                $id = $teacher['id'] ?? null;
                if ($resolve) {
                    $full = resolve_teacher_name($cache, $short, $id);
                } else {
                    $key = teacher_key($short, $id);
                    $full = isset($cache[$key]) && $cache[$key] !== '' ? $cache[$key] : $short;
                }
                $items[$index]['teachers'][$position]['short'] = $short;
                $items[$index]['teachers'][$position]['name'] = $full;
            }
        }
        return $items;
    };

    foreach ($data['weeks'] as $weekNo => $days) {
        foreach ($days as $day => $lessons) {
            $data['weeks'][$weekNo][$day] = $apply($lessons);
        }
    }
    $data['exams'] = $apply($data['exams'] ?? []);
    return $data;
}

function pending_teachers(array $data, array $cache): array
{
    $pending = [];
    $walk = static function (array $items) use (&$pending, $cache): void {
        foreach ($items as $item) {
            foreach ($item['teachers'] ?? [] as $teacher) {
                $key = teacher_key((string) $teacher['name'], $teacher['id'] ?? null);
                if (!array_key_exists($key, $cache)) {
                    $pending[$key] = [(string) $teacher['name'], $teacher['id'] ?? null];
                }
            }
        }
    };
    foreach ($data['weeks'] as $days) {
        foreach ($days as $lessons) {
            $walk($lessons);
        }
    }
    $walk($data['exams'] ?? []);
    return array_values($pending);
}

function respond_json(array $data, array $pending = []): void
{
    $body = (string) json_encode($data, JSON_UNESCAPED_UNICODE);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: public, max-age=600');
    header('Content-Length: ' . strlen($body));
    echo $body;
    warm_teachers($pending);
    exit;
}

function warm_teachers(array $pending): void
{
    if (!$pending) {
        return;
    }

    ignore_user_abort(true);
    @set_time_limit(30);
    if (function_exists('fastcgi_finish_request')) {
        fastcgi_finish_request();
    } else {
        while (ob_get_level() > 0) {
            @ob_end_flush();
        }
        @flush();
    }

    $cache = teacher_cache();
    $done = 0;
    foreach ($pending as $entry) {
        if ($done >= 3) {
            break;
        }
        try {
            resolve_teacher_name($cache, (string) $entry[0], $entry[1]);
        } catch (Throwable $error) {
        }
        $done++;
    }
    if ($done > 0) {
        teacher_cache_save($cache);
    }
}

function state_token(): string
{
    $file = __DIR__ . '/cache/state.key';
    if (!is_file($file)) {
        return '';
    }
    return trim((string) file_get_contents($file));
}

function data_path(string $name): string
{
    $safe = preg_replace('/[^a-z0-9\-]/i', '', $name);
    return __DIR__ . '/cache/' . ($safe === null ? 'item' : $safe) . '.json';
}

function json_read(string $path): array
{
    if (!is_file($path)) {
        return [];
    }
    $handle = @fopen($path, 'r');
    if ($handle === false) {
        return [];
    }
    flock($handle, LOCK_SH);
    $raw = stream_get_contents($handle);
    flock($handle, LOCK_UN);
    fclose($handle);
    $data = json_decode((string) $raw, true);
    return is_array($data) ? $data : [];
}

function json_write(string $path, array $data): void
{
    $dir = dirname($path);
    if (!is_dir($dir)) {
        @mkdir($dir, 0755, true);
    }
    $handle = @fopen($path, 'c+');
    if ($handle === false) {
        fail('хранилище недоступно', 500);
    }
    flock($handle, LOCK_EX);
    ftruncate($handle, 0);
    rewind($handle);
    fwrite($handle, (string) json_encode($data, JSON_UNESCAPED_UNICODE));
    fflush($handle);
    flock($handle, LOCK_UN);
    fclose($handle);
}

function admin_accounts(): array
{
    $admins = json_read(data_path('admins'));
    if ($admins === []) {
        fail('админ не настроен', 503);
    }
    return $admins;
}

function admin_header_token(): string
{
    $header = trim((string) ($_SERVER['HTTP_X_ADMIN_TOKEN'] ?? ''));
    if ($header !== '') {
        return $header;
    }
    $auth = trim((string) ($_SERVER['HTTP_AUTHORIZATION'] ?? ''));
    if (preg_match('/^Bearer\s+(.+)$/i', $auth, $match)) {
        return trim($match[1]);
    }
    return '';
}

function current_admin(): ?array
{
    $token = admin_header_token();
    if ($token === '') {
        return null;
    }
    $sessions = json_read(data_path('sessions'));
    $key = hash('sha256', $token);
    $entry = $sessions[$key] ?? null;
    if (!is_array($entry)) {
        return null;
    }
    if ((int) ($entry['expires'] ?? 0) < time()) {
        unset($sessions[$key]);
        json_write(data_path('sessions'), $sessions);
        return null;
    }
    return $entry;
}

function require_admin(): array
{
    $admin = current_admin();
    if ($admin === null) {
        fail('нужен вход', 401);
    }
    return $admin;
}

function body_json(): array
{
    $raw = (string) file_get_contents('php://input');
    $data = json_decode($raw, true);
    if (!is_array($data)) {
        fail('нужен JSON-объект', 400);
    }
    return $data;
}

function admin_log(array $admin, string $action, string $key = '', string $note = '', $before = null, $after = null): void
{
    $path = data_path('history');
    $items = json_read($path);
    $items[] = [
        'id' => bin2hex(random_bytes(8)),
        'time' => date('c'),
        'login' => (string) ($admin['login'] ?? ''),
        'action' => $action,
        'key' => $key,
        'note' => $note,
        'before' => $before,
        'after' => $after,
    ];
    $extra = count($items) - 200;
    if ($extra > 0) {
        $items = array_slice($items, $extra);
    }
    json_write($path, $items);
}

function change_key(array $change): string
{
    $scope = (($change['scope'] ?? '') === 'professor') ? 'professor' : 'group';
    $target = (int) ($change['target_id'] ?? 0);
    $date = (string) ($change['date'] ?? '');
    return $scope . '|' . $target . '|' . $date;
}

function normalize_lesson(array $lesson): array
{
    $teachers = [];
    foreach (($lesson['teachers'] ?? []) as $teacher) {
        if (!is_array($teacher)) {
            continue;
        }
        $name = clean_text((string) ($teacher['name'] ?? ''));
        if ($name === '') {
            continue;
        }
        $teachers[] = ['name' => $name, 'id' => isset($teacher['id']) ? (int) $teacher['id'] : null];
    }
    if ($teachers === [] && clean_text((string) ($lesson['teacher'] ?? '')) !== '') {
        $teachers[] = ['name' => clean_text((string) $lesson['teacher']), 'id' => null];
    }
    return [
        'time' => clean_text((string) ($lesson['time'] ?? '')),
        'subject' => clean_text((string) ($lesson['subject'] ?? '')),
        'type' => clean_text((string) ($lesson['type'] ?? '')),
        'teacher' => implode(', ', array_map(static fn (array $item): string => $item['name'], $teachers)),
        'teachers' => $teachers,
        'room' => clean_text((string) ($lesson['room'] ?? '')),
        'subgroup' => clean_text((string) ($lesson['subgroup'] ?? 'все')),
    ];
}

function normalize_change(array $change, array $admin): array
{
    $scope = (($change['scope'] ?? '') === 'professor') ? 'professor' : 'group';
    $targetId = (int) ($change['target_id'] ?? 0);
    $date = clean_text((string) ($change['date'] ?? ''));
    if ($targetId <= 0 || !preg_match('/^\d{4}-\d{2}-\d{2}$/', $date)) {
        fail('нужны target_id и дата', 400);
    }

    $itemKey = clean_text((string) ($change['item_key'] ?? ''));
    if ($itemKey !== '' && !preg_match('/^[a-z0-9_:.-]{1,80}$/i', $itemKey)) {
        fail('неверный item_key', 400);
    }

    $original = [];
    foreach (($change['original'] ?? []) as $lesson) {
        if (is_array($lesson)) {
            $original[] = normalize_lesson($lesson);
        }
    }

    $patches = [];
    foreach (($change['patches'] ?? []) as $patch) {
        if (!is_array($patch)) {
            continue;
        }
        $op = (string) ($patch['op'] ?? 'replace');
        if (!in_array($op, ['replace', 'add', 'remove'], true)) {
            continue;
        }
        $fields = [];
        foreach (($patch['fields'] ?? []) as $field) {
            if (in_array($field, ['time', 'room', 'teacher', 'subgroup'], true)) {
                $fields[] = $field;
            }
        }
        $pid = clean_text((string) ($patch['pid'] ?? ''));
        if ($pid !== '' && !preg_match('/^[a-z0-9-]{1,40}$/i', $pid)) {
            $pid = '';
        }
        $patches[] = [
            'pid' => $pid,
            'op' => $op,
            'index' => (int) ($patch['index'] ?? -1),
            'old' => is_array($patch['old'] ?? null) ? normalize_lesson($patch['old']) : null,
            'new' => is_array($patch['new'] ?? null) ? normalize_lesson($patch['new']) : null,
            'comment' => clean_text((string) ($patch['comment'] ?? '')),
            'partial' => !empty($patch['partial']),
            'fields' => $fields,
        ];
    }

    return [
        'key' => $scope . '|' . $targetId . '|' . $date . ($itemKey !== '' ? '|' . $itemKey : ''),
        'item_key' => $itemKey,
        'scope' => $scope,
        'target_id' => $targetId,
        'target_name' => clean_text((string) ($change['target_name'] ?? '')),
        'date' => $date,
        'removed' => !empty($change['removed']),
        'comment' => clean_text((string) ($change['comment'] ?? '')),
        'original' => $original,
        'patches' => $patches,
        'updated' => time(),
        'updated_by' => (string) ($admin['name'] ?? $admin['login'] ?? ''),
    ];
}

function notify_bot(array $change): void
{
    if (BOT_NOTIFY_URL === '') {
        return;
    }
    $body = json_encode(['token' => BOT_NOTIFY_TOKEN, 'change' => $change], JSON_UNESCAPED_UNICODE);
    $handle = curl_init(BOT_NOTIFY_URL);
    curl_setopt_array($handle, [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => $body,
        CURLOPT_HTTPHEADER => ['Content-Type: application/json'],
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CONNECTTIMEOUT => 4,
        CURLOPT_TIMEOUT => 6,
    ]);
    @curl_exec($handle);
    curl_close($handle);
}

function visible_changes(): array
{
    $changes = json_read(data_path('changes'));
    $today = new DateTime('today');
    $monday = (clone $today)->modify('monday this week');
    if ($monday > $today) {
        $monday->modify('-7 days');
    }
    $last = (clone $monday)->modify('+13 days');
    $from = $monday->format('Y-m-d');
    $to = $last->format('Y-m-d');
    $result = [];
    foreach ($changes as $key => $change) {
        if (!is_array($change)) {
            continue;
        }
        $date = (string) ($change['date'] ?? '');
        $itemKey = (string) ($change['item_key'] ?? '');
        if ($itemKey === '' && ($date < $from || $date > $to)) {
            continue;
        }
        unset($change['updated_by']);
        $result[] = $change;
    }
    usort($result, static fn (array $a, array $b): int => strcmp((string) $a['date'], (string) $b['date']));
    return $result;
}

$action = (string) ($_GET['action'] ?? '');

if (!request_is_https()) {
    $uri = (string) ($_SERVER['REQUEST_URI'] ?? '');
    $host = (string) ($_SERVER['HTTP_HOST'] ?? '');
    if ($uri !== '' && stripos($host, 'localhost') === false && strpos($host, '127.0.0.1') === false) {
        header('Location: https://hekkeyne.ru' . $uri, true, 301);
        exit;
    }
}

if (TOKEN !== '' && (string) ($_GET['token'] ?? '') !== TOKEN) {
    fail('неверный токен', 403);
}

try {
    if ($action === 'search') {
        $payload = file_get_contents('php://input');
        $cacheKey = null;
        if ($payload === false || $payload === '') {
            $query = normalize_query((string) ($_GET['q'] ?? ''));
            $payload = json_encode([
                'jsonrpc' => '2.0',
                'method' => 'call',
                'params' => ['query' => $query],
                'id' => 1,
            ]);
            $cacheKey = 'search-' . md5($query);
            $cached = cache_get($cacheKey);
            if ($cached !== null && isset($cached['body'])) {
                send(200, (string) $cached['body'], 'application/json; charset=utf-8', 'public, max-age=600');
            }
        } else {
            $decoded = json_decode($payload, true);
            if (is_array($decoded) && isset($decoded['params']['query'])) {
                $decoded['params']['query'] = normalize_query((string) $decoded['params']['query']);
                $payload = (string) json_encode($decoded, JSON_UNESCAPED_UNICODE);
            }
        }
        $result = request(SITE . '/ajax/search_schedule', [
            CURLOPT_POST => true,
            CURLOPT_POSTFIELDS => $payload,
            CURLOPT_HTTPHEADER => [
                'Content-Type: application/json',
                'Accept-Language: ru-RU,ru;q=0.9',
            ],
        ]);
        if ($cacheKey !== null) {
            cache_put($cacheKey, ['body' => $result['body']]);
        }
        send(200, $result['body'], 'application/json; charset=utf-8', $cacheKey !== null ? 'public, max-age=600' : 'no-store');
    }

    if ($action === 'resolve') {
        $id = (int) ($_GET['id'] ?? 0);
        $query = (string) ($_GET['q'] ?? '');
        $kind = (string) ($_GET['kind'] ?? 'group');
        $kind = $kind === 'professor' ? 'professor' : 'group';
        if ($id <= 0 || $query === '') {
            fail('нужны параметры id и q', 400);
        }
        $pageId = site_page_id($id, $query, $kind);
        $body = json_encode(['page_id' => $pageId], JSON_UNESCAPED_UNICODE);
        send(200, $body === false ? '{"page_id":0}' : $body, 'application/json; charset=utf-8');
    }

    if ($action === 'page') {
        $id = (int) ($_GET['id'] ?? 0);
        $kind = (string) ($_GET['kind'] ?? 'group');
        $kind = $kind === 'professor' ? 'professor' : 'group';
        if ($id <= 0) {
            fail('нужен параметр id', 400);
        }
        send(200, site_page($id, $kind), 'text/html; charset=utf-8');
    }

    if ($action === 'json') {
        $id = (int) ($_GET['id'] ?? 0);
        $query = normalize_query(trim((string) ($_GET['q'] ?? '')));
        $kind = ((string) ($_GET['kind'] ?? 'group')) === 'professor' ? 'professor' : 'group';

        if ($id <= 0) {
            if ($query === '') {
                fail('нужен параметр id или q', 400);
            }
            $exact = null;
            $candidates = [];
            foreach (site_search($query) as $item) {
                if (mb_strtoupper($item['name']) === mb_strtoupper($query)) {
                    $exact = $item;
                    break;
                }
                $words = preg_split('/\s+/u', $item['name'], -1, PREG_SPLIT_NO_EMPTY);
                if ($words && mb_strtoupper($words[0]) === mb_strtoupper($query)) {
                    $candidates[] = $item;
                }
            }
            if ($exact === null && count($candidates) === 1) {
                $exact = $candidates[0];
            }
            if ($exact === null) {
                if (count($candidates) > 1) {
                    $body = json_encode(['error' => 'несколько преподавателей с такой фамилией', 'candidates' => $candidates], JSON_UNESCAPED_UNICODE);
                    send(409, $body === false ? '{"error":"encode"}' : $body, 'application/json; charset=utf-8');
                }
                fail('не найдено: ' . $query, 404);
            }
            $id = site_page_id((int) $exact['id'], $exact['name'], $kind);
        }

        $cacheKey = 'schedule-' . $kind . '-' . $id;
        $teacherCache = $kind === 'group' ? teacher_cache() : [];

        $cached = cache_get($cacheKey);
        if ($cached !== null) {
            if ($kind === 'group') {
                $cached = apply_teacher_names($cached, $teacherCache, false);
            }
            $cached['cached'] = true;
            respond_json($cached, $kind === 'group' ? pending_teachers($cached, $teacherCache) : []);
        }

        $lockFile = cache_file($cacheKey) . '.lock';
        $lock = @fopen($lockFile, 'c');
        $locked = $lock ? flock($lock, LOCK_EX | LOCK_NB) : false;

        if (!$locked) {
            $shared = cache_get($cacheKey, 604800);
            if ($shared !== null) {
                if ($kind === 'group') {
                    $shared = apply_teacher_names($shared, $teacherCache, false);
                }
                $shared['cached'] = true;
                $shared['stale'] = true;
                send(200, (string) json_encode($shared, JSON_UNESCAPED_UNICODE), 'application/json; charset=utf-8', 'public, max-age=30');
            }
            if ($lock) {
                flock($lock, LOCK_EX);
                $locked = true;
            }
        }

        try {
            $data = parse_schedule(site_page($id, $kind), $kind);
            $data['group']['id'] = $id;
            cache_put($cacheKey, $data);
            if ($kind === 'group') {
                $data = apply_teacher_names($data, $teacherCache, false);
            }

            if ($locked && $lock) {
                flock($lock, LOCK_UN);
                fclose($lock);
            }

            respond_json($data, $kind === 'group' ? pending_teachers($data, $teacherCache) : []);
        } catch (Throwable $error) {
            if ($locked && $lock) {
                flock($lock, LOCK_UN);
                fclose($lock);
            }
            $stale = cache_get($cacheKey, 604800);
            if ($stale === null) {
                throw $error;
            }
            if ($kind === 'group') {
                $stale = apply_teacher_names($stale, $teacherCache, false);
            }
            $stale['cached'] = true;
            $stale['stale'] = true;
            send(200, (string) json_encode($stale, JSON_UNESCAPED_UNICODE), 'application/json; charset=utf-8', 'public, max-age=60');
        }
    }

    if ($action === 'consultations') {
        $id = (int) ($_GET['id'] ?? 0);
        $query = normalize_query(trim((string) ($_GET['q'] ?? '')));
        if ($id <= 0 && $query === '') {
            fail('нужен параметр id или q', 400);
        }

        if ($id <= 0) {
            $exact = null;
            foreach (site_search($query) as $item) {
                if (mb_strtoupper($item['name']) === mb_strtoupper($query)) {
                    $exact = $item;
                    break;
                }
            }
            if ($exact === null) {
                fail('группа не найдена: ' . $query, 404);
            }
            $id = site_page_id((int) $exact['id'], $exact['name'], 'group');
        }

        $cacheKey = 'consult-group-' . $id;
        $cached = cache_get($cacheKey, 1800);
        if ($cached !== null) {
            send(200, (string) json_encode($cached, JSON_UNESCAPED_UNICODE), 'application/json; charset=utf-8', 'public, max-age=1800');
        }

        $schedule = cache_get('schedule-group-' . $id);
        if ($schedule === null) {
            $schedule = parse_schedule(site_page($id, 'group'), 'group');
            $schedule['group']['id'] = $id;
            cache_put('schedule-group-' . $id, $schedule);
        }
        $schedule = apply_teacher_names($schedule, teacher_cache(), false);

        $teacherIds = [];
        $teacherNames = [];
        foreach ($schedule['weeks'] as $days) {
            foreach ($days as $lessons) {
                foreach ($lessons as $lesson) {
                    foreach (($lesson['teachers'] ?? []) as $teacher) {
                        if (!empty($teacher['id'])) {
                            $teacherIds[(int) $teacher['id']] = true;
                            $teacherNames[(int) $teacher['id']] = $teacher['name'];
                        }
                    }
                }
            }
        }

        $consultations = [];
        $collect = static function (array $items, int $teacherId) use (&$consultations, $teacherNames): void {
            $host = $teacherNames[$teacherId] ?? '';
            foreach ($items as $item) {
                $item['teachers'] = [['name' => $host, 'id' => $teacherId]];
                $item['teacher'] = $host;
                $consultations[] = $item;
            }
        };

        $missing = [];
        foreach (array_keys($teacherIds) as $teacherId) {
            $one = cache_get('consult-' . $teacherId, 21600);
            if ($one === null) {
                $missing[] = $teacherId;
                continue;
            }
            $collect($one, $teacherId);
        }

        $failed = 0;
        if ($missing) {
            $urls = [];
            foreach ($missing as $teacherId) {
                $urls[$teacherId] = SITE . '/timetable/professor/' . $teacherId;
            }
            foreach (request_many($urls, 8, 20) as $teacherId => $body) {
                if (!is_string($body) || strlen($body) < 2000) {
                    $failed++;
                    continue;
                }
                $items = parse_consultations($body);
                cache_put('consult-' . $teacherId, $items);
                $collect($items, (int) $teacherId);
            }
        }

        $seen = [];
        $unique = [];
        foreach ($consultations as $item) {
            $key = $item['date'] . '|' . $item['time'] . '|' . $item['subject'] . '|' . $item['room'];
            if (isset($seen[$key])) {
                continue;
            }
            $seen[$key] = true;
            $unique[] = $item;
        }
        usort($unique, static function (array $a, array $b): int {
            $left = DateTime::createFromFormat('d.m.Y', $a['date']);
            $right = DateTime::createFromFormat('d.m.Y', $b['date']);
            if (!$left || !$right) {
                return strcmp($a['date'], $b['date']);
            }
            return $left <=> $right;
        });

        $payload = [
            'group' => ['id' => $id, 'name' => $schedule['group']['name'] ?? ''],
            'consultations' => $unique,
            'teachers' => count($teacherIds),
            'partial' => $failed > 0,
        ];
        cache_put($cacheKey, $payload);
        send(200, (string) json_encode($payload, JSON_UNESCAPED_UNICODE), 'application/json; charset=utf-8', 'public, max-age=1800');
    }

    if ($action === 'hit') {
        $kind = ((string) ($_GET['kind'] ?? 'group')) === 'professor' ? 'professor' : 'group';
        $name = mb_substr(trim((string) ($_GET['name'] ?? '')), 0, 120);
        $stats = visit_stats($kind, $name);
        $body = json_encode(['total' => $stats['total'], 'today' => $stats['today']], JSON_UNESCAPED_UNICODE);
        send(200, $body === false ? '{}' : $body, 'application/json; charset=utf-8');
    }

    if ($action === 'stats') {
        require_admin();
        $stats = visit_stats();
        $targets = $stats['targets'];
        arsort($targets);
        $stats['top'] = array_slice($targets, 0, 25, true);
        $stats['days'] = array_slice($stats['days'], -30, null, true);
        unset($stats['targets']);
        $body = json_encode($stats, JSON_UNESCAPED_UNICODE);
        send(200, $body === false ? '{}' : $body, 'application/json; charset=utf-8');
    }

    if ($action === 'warm') {
        $id = (int) ($_GET['id'] ?? 0);
        $limit = (int) ($_GET['limit'] ?? 4);
        $limit = max(1, min(8, $limit));
        if ($id <= 0) {
            fail('нужен параметр id', 400);
        }

        $data = cache_get('schedule-' . $id);
        if ($data === null) {
            $data = parse_schedule(site_page($id, 'group'));
            $data['group']['id'] = $id;
            cache_put('schedule-' . $id, $data);
        }

        $cache = teacher_cache();
        $pending = pending_teachers($data, $cache);
        $done = 0;
        foreach ($pending as $entry) {
            if ($done >= $limit) {
                break;
            }
            resolve_teacher_name($cache, $entry[0], $entry[1]);
            $done++;
        }
        teacher_cache_save($cache);

        $body = json_encode([
            'resolved' => $done,
            'remaining' => max(0, count($pending) - $done),
            'total' => count($pending),
        ], JSON_UNESCAPED_UNICODE);
        send(200, $body === false ? '{}' : $body, 'application/json; charset=utf-8');
    }

    if ($action === 'groups') {
        $items = site_search((string) ($_GET['q'] ?? ''));
        $body = json_encode($items, JSON_UNESCAPED_UNICODE);
        send(200, $body === false ? '[]' : $body, 'application/json; charset=utf-8');
    }

    if ($action === 'state') {
        $expected = state_token();
        $given = (string) ($_SERVER['HTTP_X_STATE_TOKEN'] ?? '');
        if ($expected === '' || !hash_equals($expected, $given)) {
            fail('неверный токен', 403);
        }

        $path = __DIR__ . '/cache/state.json';
        $dir = dirname($path);
        if (!is_dir($dir)) {
            @mkdir($dir, 0755, true);
        }

        if ((string) ($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST') {
            $raw = file_get_contents('php://input');
            $data = json_decode((string) $raw, true);
            if (!is_array($data)) {
                fail('нужен JSON-объект', 400);
            }
            $handle = @fopen($path, 'c+');
            if ($handle === false) {
                fail('хранилище недоступно', 500);
            }
            flock($handle, LOCK_EX);
            ftruncate($handle, 0);
            rewind($handle);
            fwrite($handle, (string) json_encode($data, JSON_UNESCAPED_UNICODE));
            fflush($handle);
            flock($handle, LOCK_UN);
            fclose($handle);
            send(200, '{"ok":true}', 'application/json; charset=utf-8');
        }

        $handle = @fopen($path, 'c+');
        if ($handle === false) {
            send(200, '{}', 'application/json; charset=utf-8');
        }
        flock($handle, LOCK_SH);
        $raw = stream_get_contents($handle);
        flock($handle, LOCK_UN);
        fclose($handle);
        $raw = trim((string) $raw);
        send(200, $raw === '' ? '{}' : $raw, 'application/json; charset=utf-8');
    }

    if ($action === 'image') {
        $url = trim((string) ($_GET['url'] ?? ''));
        if (!preg_match('#^https?://#i', $url)) {
            fail('неверная ссылка', 400);
        }
        $host = (string) parse_url($url, PHP_URL_HOST);
        if ($host === '') {
            fail('неверная ссылка', 400);
        }
        $addresses = gethostbynamel($host);
        if (!$addresses) {
            fail('не удалось найти хост', 502);
        }
        foreach ($addresses as $address) {
            if (!filter_var($address, FILTER_VALIDATE_IP, FILTER_FLAG_NO_PRIV_RANGE | FILTER_FLAG_NO_RES_RANGE)) {
                fail('запрещённый адрес', 403);
            }
        }
        $result = request($url, [
            CURLOPT_FOLLOWLOCATION => true,
            CURLOPT_MAXREDIRS => 3,
        ]);
        if ($result['status'] !== 200) {
            fail('не удалось загрузить', 502);
        }
        $type = header_value($result['headers'], 'Content-Type');
        if (stripos($type, 'image/') !== 0) {
            fail('не картинка', 400);
        }
        if (strlen($result['body']) > 8 * 1024 * 1024) {
            fail('слишком большая', 400);
        }
        send(200, $result['body'], $type, 'public, max-age=86400');
    }

    if ($action === 'changes') {
        $changes = visible_changes();
        $updated = 0;
        foreach ($changes as $change) {
            $updated = max($updated, (int) ($change['updated'] ?? 0));
        }
        $body = json_encode(['changes' => $changes, 'updated' => $updated], JSON_UNESCAPED_UNICODE);
        send(200, $body === false ? '{"changes":[]}' : $body, 'application/json; charset=utf-8');
    }

    if ($action === 'admin_login') {
        $payload = body_json();
        $login = trim((string) ($payload['login'] ?? ''));
        $password = (string) ($payload['password'] ?? '');
        if ($login === '' || $password === '') {
            fail('введите логин и пароль', 400);
        }

        $ip = (string) ($_SERVER['REMOTE_ADDR'] ?? '');
        $throttlePath = data_path('admin_throttle');
        $throttleLock = @fopen($throttlePath . '.lock', 'c');
        if ($throttleLock !== false) {
            flock($throttleLock, LOCK_EX);
        }
        $throttle = json_read($throttlePath);
        $throttleKey = md5($ip . '|' . mb_strtolower($login));
        $attempt = $throttle[$throttleKey] ?? ['fails' => 0, 'until' => 0];
        if ((int) $attempt['until'] > time()) {
            if ($throttleLock !== false) {
                flock($throttleLock, LOCK_UN);
                fclose($throttleLock);
            }
            fail('слишком много попыток, подождите', 429);
        }

        $match = null;
        foreach (admin_accounts() as $account) {
            if (mb_strtolower((string) $account['login']) === mb_strtolower($login)) {
                $match = $account;
                break;
            }
        }

        if ($match === null || !password_verify($password, (string) $match['hash'])) {
            $attempt['fails'] = (int) $attempt['fails'] + 1;
            if ($attempt['fails'] >= ADMIN_MAX_FAILS) {
                $attempt['fails'] = 0;
                $attempt['until'] = time() + ADMIN_LOCK_SECONDS;
            }
            $throttle[$throttleKey] = $attempt;
            json_write($throttlePath, $throttle);
            if ($throttleLock !== false) {
                flock($throttleLock, LOCK_UN);
                fclose($throttleLock);
            }
            admin_log(['login' => $login, 'name' => $login], 'login_fail');
            fail('неверный логин или пароль', 403);
        }

        unset($throttle[$throttleKey]);
        json_write($throttlePath, $throttle);
        if ($throttleLock !== false) {
            flock($throttleLock, LOCK_UN);
            fclose($throttleLock);
        }

        $token = bin2hex(random_bytes(32));
        $sessionKey = hash('sha256', $token);
        $sessions = json_read(data_path('sessions'));
        foreach ($sessions as $key => $entry) {
            if ((int) ($entry['expires'] ?? 0) < time()) {
                unset($sessions[$key]);
            }
        }
        $expires = time() + ADMIN_SESSION_TTL;
        $sessions[$sessionKey] = [
            'login' => (string) $match['login'],
            'name' => (string) $match['name'],
            'expires' => $expires,
        ];
        json_write(data_path('sessions'), $sessions);
        admin_log($match, 'login');

        $body = json_encode([
            'ok' => true,
            'token' => $token,
            'login' => $match['login'],
            'name' => $match['name'],
            'expires' => $expires,
        ], JSON_UNESCAPED_UNICODE);
        send(200, $body === false ? '{"ok":true}' : $body, 'application/json; charset=utf-8');
    }

    if ($action === 'admin_me') {
        $admin = require_admin();
        $body = json_encode(['login' => $admin['login'], 'name' => $admin['name'], 'expires' => $admin['expires']], JSON_UNESCAPED_UNICODE);
        send(200, $body === false ? '{}' : $body, 'application/json; charset=utf-8');
    }

    if ($action === 'admin_logout') {
        $token = admin_header_token();
        if ($token !== '') {
            $sessions = json_read(data_path('sessions'));
            unset($sessions[hash('sha256', $token)]);
            json_write(data_path('sessions'), $sessions);
        }
        send(200, '{"ok":true}', 'application/json; charset=utf-8');
    }

    if ($action === 'admin_password') {
        $admin = require_admin();
        $payload = body_json();
        $old = (string) ($payload['old'] ?? '');
        $new = (string) ($payload['new'] ?? '');
        if (mb_strlen($new) < 12) {
            fail('пароль слишком короткий', 400);
        }
        if ($new === 'danigold4' || mb_strtolower($new) === 'hekkeyne') {
            fail('этот пароль нельзя использовать', 400);
        }

        $admins = admin_accounts();
        $found = false;
        foreach ($admins as $index => $account) {
            if (mb_strtolower((string) $account['login']) !== mb_strtolower((string) $admin['login'])) {
                continue;
            }
            if (!password_verify($old, (string) $account['hash'])) {
                fail('старый пароль неверный', 403);
            }
            $admins[$index]['hash'] = password_hash($new, PASSWORD_DEFAULT);
            $found = true;
            break;
        }
        if (!$found) {
            fail('админ не найден', 404);
        }
        json_write(data_path('admins'), $admins);
        $currentToken = admin_header_token();
        $sessions = [];
        if ($currentToken !== '') {
            $sessions[hash('sha256', $currentToken)] = $admin;
        }
        json_write(data_path('sessions'), $sessions);
        admin_log($admin, 'password');
        send(200, '{"ok":true}', 'application/json; charset=utf-8');
    }

    if ($action === 'admin_list') {
        require_admin();
        $changes = json_read(data_path('changes'));
        $items = [];
        foreach ($changes as $change) {
            if (is_array($change)) {
                $items[] = $change;
            }
        }
        usort($items, static fn (array $a, array $b): int => strcmp((string) $a['date'], (string) $b['date']));
        $body = json_encode(['changes' => $items], JSON_UNESCAPED_UNICODE);
        send(200, $body === false ? '{"changes":[]}' : $body, 'application/json; charset=utf-8');
    }

    if ($action === 'admin_save') {
        $admin = require_admin();
        $payload = body_json();
        $change = normalize_change((array) ($payload['change'] ?? []), $admin);
        $changes = json_read(data_path('changes'));
        $previous = $changes[$change['key']] ?? null;
        $changes[$change['key']] = $change;
        json_write(data_path('changes'), $changes);
        admin_log($admin, 'save', $change['key'], '', $previous, $change);
        notify_bot($change);
        $body = json_encode(['ok' => true, 'change' => $change], JSON_UNESCAPED_UNICODE);
        send(200, $body === false ? '{"ok":true}' : $body, 'application/json; charset=utf-8');
    }

    if ($action === 'admin_delete') {
        $admin = require_admin();
        $payload = body_json();
        $key = (string) ($payload['key'] ?? '');
        if ($key === '') {
            fail('нужен ключ', 400);
        }
        $changes = json_read(data_path('changes'));
        $removed = isset($changes[$key]);
        $previous = $changes[$key] ?? null;
        unset($changes[$key]);
        json_write(data_path('changes'), $changes);
        admin_log($admin, 'delete', $key, '', $previous, null);
        if ($removed) {
            notify_bot(['key' => $key, 'deleted' => true]);
        }
        send(200, '{"ok":true}', 'application/json; charset=utf-8');
    }

    if ($action === 'admin_history') {
        require_admin();
        $items = json_read(data_path('history'));
        $out = [];
        foreach (array_slice($items, -200) as $item) {
            if (!is_array($item)) {
                continue;
            }
            $actionName = (string) ($item['action'] ?? '');
            $out[] = [
                'id' => (string) ($item['id'] ?? ''),
                'time' => (string) ($item['time'] ?? ''),
                'login' => (string) ($item['login'] ?? ''),
                'action' => $actionName,
                'key' => (string) ($item['key'] ?? ''),
                'note' => (string) ($item['note'] ?? ''),
                'can_rollback' => in_array($actionName, ['save', 'delete', 'rollback'], true)
                    && (array_key_exists('before', $item) || array_key_exists('after', $item)),
            ];
        }
        $out = array_reverse($out);
        $body = json_encode(['entries' => $out], JSON_UNESCAPED_UNICODE);
        send(200, $body === false ? '{"entries":[]}' : $body, 'application/json; charset=utf-8');
    }

    if ($action === 'admin_rollback') {
        $admin = require_admin();
        $payload = body_json();
        $id = (string) ($payload['id'] ?? '');
        if ($id === '') {
            fail('нужен id', 400);
        }
        $items = json_read(data_path('history'));
        $entry = null;
        foreach ($items as $item) {
            if (is_array($item) && (string) ($item['id'] ?? '') === $id) {
                $entry = $item;
                break;
            }
        }
        if ($entry === null) {
            fail('запись не найдена', 404);
        }
        $key = (string) ($entry['key'] ?? '');
        if ($key === '') {
            fail('нечего откатывать', 400);
        }
        $changes = json_read(data_path('changes'));
        $current = $changes[$key] ?? null;
        $before = $entry['before'] ?? null;
        if (is_array($before)) {
            $changes[$key] = $before;
        } else {
            unset($changes[$key]);
        }
        json_write(data_path('changes'), $changes);
        admin_log($admin, 'rollback', $key, '', $current, $before);
        if (is_array($before)) {
            notify_bot($before);
        } else {
            notify_bot(['key' => $key, 'deleted' => true]);
        }
        send(200, '{"ok":true}', 'application/json; charset=utf-8');
    }

    fail('неизвестное действие', 400);
} catch (Throwable $error) {
    error_log('timetable: ' . $error->getMessage());
    fail('внутренняя ошибка', 500);
}