"""Tests for chatproto.py: run against the good version (all pass) and against each variant (each must fail in its
labelled way)."""

import threading

import pytest
from chatproto import NicknameRegistry, ProtocolError, frame, parse_command, unframe


def test_plain_text_is_said() -> None:
    assert parse_command("hello all") == ("say", ["hello all"])


def test_commands_are_parsed_case_insensitively() -> None:
    assert parse_command("/NICK Ada") == ("nick", ["Ada"])
    assert parse_command("/msg Bob hi there") == ("msg", ["Bob", "hi there"])
    assert parse_command("/quit") == ("quit", [])


def test_bad_commands_are_rejected() -> None:
    with pytest.raises(ProtocolError):
        parse_command("/msg Bob")
    with pytest.raises(ProtocolError):
        parse_command("/dance")


def test_nicknames_are_unique_case_insensitively() -> None:
    reg = NicknameRegistry()
    assert reg.register("c1", "Ada")
    assert not reg.register("c2", "ada")
    reg.unregister("ADA")
    assert reg.register("c2", "ada") and len(reg) == 1


def test_invalid_nicknames_are_refused() -> None:
    reg = NicknameRegistry()
    for bad in ["", "a" * 17, "no spaces"]:
        with pytest.raises(ProtocolError):
            reg.register("c1", bad)


def test_only_one_thread_gets_a_contested_nickname() -> None:
    reg = NicknameRegistry()
    wins = []
    start = threading.Barrier(20)

    def grab(i: int) -> None:
        start.wait()
        if reg.register(f"c{i}", "popular"):
            wins.append(i)

    threads = [threading.Thread(target=grab, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(wins) == 1


def test_frames_round_trip_split_and_joined() -> None:
    data = frame("hi") + frame("héllo wörld") + frame("x")
    msgs, rest = unframe(data)
    assert msgs == ["hi", "héllo wörld", "x"] and rest == b""
    first, rest = unframe(data[:5])
    assert first == [] and rest == data[:5]                       # an incomplete frame waits for more bytes
    msgs, rest = unframe(rest + data[5:])
    assert msgs == ["hi", "héllo wörld", "x"]


def test_frame_header_is_the_byte_length() -> None:
    assert frame("é")[:4] == (2).to_bytes(4, "big")
