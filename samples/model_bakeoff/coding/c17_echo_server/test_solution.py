import socket, time
from solution import EchoServer

def _conn(port):
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    return s, s.makefile("r", encoding="utf-8", newline="\n")

def test_echo_upper():
    srv = EchoServer(); port = srv.start()
    try:
        s, f = _conn(port)
        s.sendall(b"hello\nWorld 1\n")
        assert f.readline() == "HELLO\n"
        assert f.readline() == "WORLD 1\n"
        s.close()
    finally:
        srv.stop()

def test_concurrent_clients():
    srv = EchoServer(); port = srv.start()
    try:
        idle, _ = _conn(port)
        s2, f2 = _conn(port)
        s2.sendall(b"second\n")
        assert f2.readline() == "SECOND\n"
        idle.close(); s2.close()
    finally:
        srv.stop()

def test_start_returns_quickly():
    srv = EchoServer()
    t = time.time(); port = srv.start()
    try:
        assert time.time() - t < 2 and isinstance(port, int) and port > 0
    finally:
        srv.stop()
