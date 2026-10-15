from protocol import frame, parse_command, unframe


def test_round_trip():
    assert unframe(frame("hi") + frame("there")) == (["hi", "there"], b"")


def test_commands():
    assert parse_command("/msg bob hello") == ("msg", ["bob", "hello"])
    assert parse_command("hello") == ("say", ["hello"])
