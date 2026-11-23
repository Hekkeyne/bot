<?php
declare(strict_types=1);

const SITE = 'https://timetable.pallada.sibsau.ru';
const TIMEOUT = 20;
const TOKEN = '';
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    . '(KHTML, like Gecko) Chrome/120.0 Safari/537.36';

function send(int $status, string $body, string $type): void
{
    http_response_code($status);
    header('Content-Type: ' . $type);
    header('Cache-Control: no-store');
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

$action = (string) ($_GET['action'] ?? '');

if (TOKEN !== '' && (string) ($_GET['token'] ?? '') !== TOKEN) {
    fail('неверный токен', 403);
}

try {
    if ($action === 'search') {
        $payload = file_get_contents('php://input');
        if ($payload === false || $payload === '') {
            $payload = json_encode([
                'jsonrpc' => '2.0',
                'method' => 'call',
                'params' => ['query' => (string) ($_GET['q'] ?? '')],
                'id' => 1,
            ]);
        }
        $result = request(SITE . '/ajax/search_schedule', [
            CURLOPT_POST => true,
            CURLOPT_POSTFIELDS => $payload,
            CURLOPT_HTTPHEADER => [
                'Content-Type: application/json',
                'Accept-Language: ru-RU,ru;q=0.9',
            ],
        ]);
        send(200, $result['body'], 'application/json; charset=utf-8');
    }

    if ($action === 'resolve') {
        $id = (int) ($_GET['id'] ?? 0);
        $query = (string) ($_GET['q'] ?? '');
        if ($id <= 0 || $query === '') {
            fail('нужны параметры id и q', 400);
        }

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
                    'id' => $id,
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
        if (!preg_match('#/timetable/group/(\d+)#', $location, $found)) {
            fail('сайт не сообщил страницу группы');
        }
        $body = json_encode(['page_id' => (int) $found[1]], JSON_UNESCAPED_UNICODE);
        send(200, $body === false ? '{"page_id":0}' : $body, 'application/json; charset=utf-8');
    }

    if ($action === 'page') {
        $id = (int) ($_GET['id'] ?? 0);
        if ($id <= 0) {
            fail('нужен параметр id', 400);
        }
        $result = request(SITE . '/timetable/group/' . $id);
        if ($result['status'] !== 200) {
            fail('сайт вернул код ' . $result['status']);
        }
        send(200, $result['body'], 'text/html; charset=utf-8');
    }

    fail('неизвестное действие', 400);
} catch (Throwable $error) {
    fail($error->getMessage());
}