import socket, time
import pytest
from solution import ChatServer

class C:
    def __init__(self, port, name=None):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.f = self.s.makefile("r", encoding="utf-8", newline="\n")
        if name:
            self.send(f"NAME {name}")
            assert self.line() == "OK"
    def send(self, text):
        self.s.sendall((text + "\n").encode())
    def line(self):
        return self.f.readline().rstrip("\n")
    def nothing(self, wait=0.4):
        self.s.settimeout(wait)
        try:
            return self.f.readline() == ""
        except (socket.timeout, TimeoutError):
            return True
        finally:
            self.s.settimeout(5)
    def close(self):
        self.f.close()
        self.s.close()

@pytest.fixture
def port():
    srv = ChatServer(); p = srv.start()
    yield p
    srv.stop()

def test_join_broadcast_and_no_self_echo(port):
    a = C(port, "alice")
    b = C(port, "bob")
    assert a.line() == "* bob joined"
    c = C(port, "carol")
    assert a.line() == "* carol joined" and b.line() == "* carol joined"
    a.send("hi all")
    assert b.line() == "alice: hi all"
    assert c.line() == "alice: hi all"
    assert a.nothing()
    for x in (a, b, c): x.close()

def test_duplicate_name_rejected(port):
    a = C(port, "dave")
    d = C(port)
    d.send("NAME dave")
    assert d.line() == "ERROR name taken"
    assert d.f.readline() == ""
    a.close()

def test_leave_frees_name(port):
    a = C(port, "erin")
    b = C(port, "frank")
    assert a.line() == "* frank joined"
    b.close()
    assert a.line() == "* frank left"
    time.sleep(0.2)
    b2 = C(port, "frank")
    assert a.line() == "* frank joined"
    a.close(); b2.close()
