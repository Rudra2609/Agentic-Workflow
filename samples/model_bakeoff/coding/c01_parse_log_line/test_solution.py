from solution import parse_log_line

def test_basic():
    r = parse_log_line('127.0.0.1 - - [10/Oct/2025:13:55:36 +0000] "GET /index.html HTTP/1.1" 200 2326')
    assert r == {"ip": "127.0.0.1", "timestamp": "10/Oct/2025:13:55:36 +0000", "method": "GET",
                 "path": "/index.html", "protocol": "HTTP/1.1", "status": 200, "size": 2326}

def test_dash_size():
    r = parse_log_line('10.0.0.5 - bob [01/Jan/2026:00:00:01 +0530] "POST /api/login HTTP/1.0" 302 -')
    assert r["size"] == 0 and r["status"] == 302 and r["method"] == "POST" and r["ip"] == "10.0.0.5"

def test_query_string_kept():
    r = parse_log_line('192.168.1.9 - - [02/Feb/2026:10:10:10 +0000] "GET /search?q=a+b&x=1 HTTP/1.1" 404 12')
    assert r["path"] == "/search?q=a+b&x=1" and r["status"] == 404

def test_invalid_returns_none():
    assert parse_log_line("") is None
    assert parse_log_line("not a log line") is None
    assert parse_log_line('127.0.0.1 - - [10/Oct/2025:13:55:36 +0000] "GET /x HTTP/1.1" abc 1') is None
