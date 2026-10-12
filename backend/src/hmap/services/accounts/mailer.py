"""Outgoing account email (password reset).

With ``HMAP_SMTP_HOST`` set, mail goes out over SMTP (STARTTLS by default). Without it — the laptop demo — each
message is written to ``<repo>/data/dev_mailbox/<time>-<to>.eml`` so the flow can be tested end to end without an
email provider. The log line names the file, never the link or token inside it.
"""

import asyncio
import smtplib
import ssl
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Protocol

from hmap.core.tracing import get_logger

log = get_logger("hmap.accounts.mail")


class Mailer(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...


class FileMailer:
    """Development mailbox: one ``.eml`` file per message."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    async def send(self, to: str, subject: str, body: str) -> None:
        msg = _message("hmap@localhost", to, subject, body)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        safe_to = "".join(c if c.isalnum() or c in "@._-" else "_" for c in to)
        path = self.folder / f"{stamp}-{safe_to}.eml"

        def write() -> None:
            self.folder.mkdir(parents=True, exist_ok=True)
            path.write_bytes(bytes(msg))
            path.chmod(0o600)

        await asyncio.to_thread(write)
        log.info("account email written to the dev mailbox", file=str(path))


class SmtpMailer:
    def __init__(self, host: str, port: int, sender: str, *, username: str | None = None,
                 password: str | None = None, starttls: bool = True) -> None:
        self.host, self.port, self.sender = host, port, sender
        self.username, self.password, self.starttls = username, password, starttls

    async def send(self, to: str, subject: str, body: str) -> None:
        msg = _message(self.sender, to, subject, body)

        def deliver() -> None:
            with smtplib.SMTP(self.host, self.port, timeout=20) as smtp:
                if self.starttls:
                    smtp.starttls(context=ssl.create_default_context())
                if self.username and self.password:
                    smtp.login(self.username, self.password)
                smtp.send_message(msg)

        await asyncio.to_thread(deliver)
        log.info("account email sent", host=self.host)


def _message(sender: str, to: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, to, subject
    msg.set_content(body)
    return msg
