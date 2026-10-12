from solution import is_valid_ipv4

def test_valid():
    for s in ["0.0.0.0", "255.255.255.255", "192.168.1.1", "10.0.0.10"]:
        assert is_valid_ipv4(s), s

def test_invalid():
    for s in ["256.1.1.1", "1.1.1", "1.1.1.1.1", "01.1.1.1", "1.1.1.-1", "a.b.c.d", "", " 1.1.1.1",
              "1..1.1", "1.1.1.1 ", "+1.1.1.1", "1.1.1.1.", "١.1.1.1"]:
        assert not is_valid_ipv4(s), s
