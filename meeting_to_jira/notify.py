"""Developer reminders by email (free with a Gmail app password) and/or Slack."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

import requests

log = logging.getLogger(__name__)


class Notifier:
    def __init__(
        self,
        smtp_host: str | None = None,
        smtp_port: int = 587,
        smtp_user: str | None = None,
        smtp_password: str | None = None,
        email_from: str | None = None,
        slack_webhook_url: str | None = None,
        dry_run: bool = False,
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.email_from = email_from
        self.slack_webhook_url = slack_webhook_url
        self.dry_run = dry_run

    def email(self, to: str, subject: str, body: str) -> None:
        if self.dry_run or not self.smtp_host:
            log.info("[email not sent] to=%s subject=%s\n%s", to, subject, body)
            return
        msg = EmailMessage()
        msg["From"] = self.email_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as smtp:
            smtp.starttls()
            if self.smtp_user:
                smtp.login(self.smtp_user, self.smtp_password or "")
            smtp.send_message(msg)

    def slack(self, text: str) -> None:
        if self.dry_run or not self.slack_webhook_url:
            if self.slack_webhook_url:
                log.info("[slack not sent]\n%s", text)
            return
        requests.post(self.slack_webhook_url, json={"text": text}, timeout=30).raise_for_status()


def new_tickets_body(name: str, meeting: str, tickets: list[tuple[str, str, str]]) -> str:
    lines = [
        f"Hi {name},",
        "",
        f"These tickets were created for you from \"{meeting}\":",
        "",
        *[f"  - {key}: {summary}\n    {url}" for key, summary, url in tickets],
        "",
        "Please review the acceptance criteria and move each ticket to the right status "
        "on the board (e.g. In Progress) when you start on it.",
    ]
    return "\n".join(lines)


def stale_tickets_body(name: str, stale_hours: int, issues: list) -> str:
    lines = [
        f"Hi {name},",
        "",
        f"These tickets assigned to you haven't been updated in the last {stale_hours} hours:",
        "",
        *[f"  - {i.key} [{i.status}]: {i.summary}\n    {i.url}" for i in issues],
        "",
        "Please update their status before the next stand-up "
        "(or leave a comment if you're blocked).",
    ]
    return "\n".join(lines)
