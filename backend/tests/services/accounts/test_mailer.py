"""The development mailbox writes one private .eml per message (used when no SMTP server is configured)."""

import stat
from email import message_from_bytes

from hmap.api.app import build_mailer
from hmap.core.config import Settings
from hmap.services.accounts.mailer import FileMailer, SmtpMailer


async def test_file_mailer_writes_a_private_eml(tmp_path) -> None:
    mailer = FileMailer(tmp_path / "box")
    await mailer.send("ada@example.test", "Reset your HMAP password", "link: http://x/reset-password#token=abc")
    [path] = list((tmp_path / "box").glob("*.eml"))
    assert path.name.endswith("ada@example.test.eml")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    msg = message_from_bytes(path.read_bytes())
    assert msg["To"] == "ada@example.test" and "#token=abc" in msg.get_payload()


def test_smtp_is_used_only_when_configured() -> None:
    assert isinstance(build_mailer(Settings.from_env({})), FileMailer)
    smtp = build_mailer(Settings.from_env({"HMAP_SMTP_HOST": "smtp.example.test", "HMAP_SMTP_PORT": "2525"}))
    assert isinstance(smtp, SmtpMailer) and smtp.port == 2525
