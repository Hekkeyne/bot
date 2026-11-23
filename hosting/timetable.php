<?php
declare(strict_types=1);

const SITE = 'https://timetable.pallada.sibsau.ru';
const TIMEOUT = 20;
const TOKEN = '';
const CACHE_TTL = 3600;
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    . '(KHTML, like Gecko) Chrome/120.0 Safari/537.36';

const WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'];

function send(int $status, string $body, string $type, string $cache = 'no-store'): void
{
    http_response_code($status);
    header('Content-Type: ' . $type);
    header('Cache-Control: ' . $cache);
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

    foreach ($xpath->query(".//li[.//i[" . cls('fa-user') . "]]//a", $ul) as $link) {
        $name = clean_text($link->textContent);
        if ($name === '') {
            continue;
        }
        $teacherId = null;
        if (preg_match('#/timetable/professor/(\d+)#', $link->getAttribute('href'), $match)) {
            $teacherId = (int) $match[1];
        }
        $teachers[] = ['name' => $name, 'id' => $teacherId];
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

function parse_schedule(string $html): array
{
    $document = new DOMDocument();
    libxml_use_internal_errors(true);
    $document->loadHTML('<?xml encoding="utf-8" ?>' . $html);
    libxml_clear_errors();
    $xpath = new DOMXPath($document);

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

    $exams = [];
    $session = $xpath->query("//div[@id='session_tab']")->item(0);
    if ($session) {
        foreach ($xpath->query(".//div[" . cls('day') . "]", $session) as $day) {
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
                    $exams[] = [
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
    }

    return [
        'group' => ['name' => $groupName],
        'semester' => $semester,
        'ref' => ['date' => $refDate, 'week' => $refWeek],
        'weeks' => $weeks,
        'exams' => $exams,
        'updated' => date('c'),
    ];
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

$action = (string) ($_GET['action'] ?? '');

if (TOKEN !== '' && (string) ($_GET['token'] ?? '') !== TOKEN) {
    fail('неверный токен', 403);
}

try {
    if ($action === 'search') {
        $payload = file_get_contents('php://input');
        $cacheKey = null;
        if ($payload === false || $payload === '') {
            $query = (string) ($_GET['q'] ?? '');
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
        $query = trim((string) ($_GET['q'] ?? ''));
        if ($id <= 0) {
            if ($query === '') {
                fail('нужен параметр id или q', 400);
            }
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

        $cached = cache_get('schedule-' . $id);
        $teacherCache = teacher_cache();
        if ($cached !== null) {
            $cached = apply_teacher_names($cached, $teacherCache, false);
            $cached['cached'] = true;
            respond_json($cached, pending_teachers($cached, $teacherCache));
        }

        $lockFile = cache_file('schedule-' . $id) . '.lock';
        $lock = @fopen($lockFile, 'c');
        $locked = $lock ? flock($lock, LOCK_EX | LOCK_NB) : false;

        if (!$locked) {
            $shared = cache_get('schedule-' . $id, 604800);
            if ($shared !== null) {
                $shared = apply_teacher_names($shared, $teacherCache, false);
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
            $data = parse_schedule(site_page($id, 'group'));
            $data['group']['id'] = $id;
            cache_put('schedule-' . $id, $data);
            $data = apply_teacher_names($data, $teacherCache, false);

            if ($locked && $lock) {
                flock($lock, LOCK_UN);
                fclose($lock);
            }

            respond_json($data, pending_teachers($data, $teacherCache));
        } catch (Throwable $error) {
            if ($locked && $lock) {
                flock($lock, LOCK_UN);
                fclose($lock);
            }
            $stale = cache_get('schedule-' . $id, 604800);
            if ($stale === null) {
                throw $error;
            }
            $stale = apply_teacher_names($stale, $teacherCache, false);
            $stale['cached'] = true;
            $stale['stale'] = true;
            send(200, (string) json_encode($stale, JSON_UNESCAPED_UNICODE), 'application/json; charset=utf-8', 'public, max-age=60');
        }
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

    fail('неизвестное действие', 400);
} catch (Throwable $error) {
    fail($error->getMessage());
}