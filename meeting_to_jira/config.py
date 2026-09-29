"""Settings loaded from environment variables (or a local .env file)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional
    pass


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class TeamMember:
    name: str
    email: str
    aliases: list[str] = field(default_factory=list)
    jira_account_id: str | None = None


@dataclass(frozen=True)
class Settings:
    jira_base_url: str
    jira_email: str
    jira_api_token: str
    jira_project_key: str
    jira_issue_type: str
    jira_ac_field: str | None
    team: list[TeamMember]
    drive_folder_id: str | None
    google_service_account_json: str | None
    process_since_days: int
    smtp_host: str | None
    smtp_port: int
    smtp_user: str | None
    smtp_password: str | None
    email_from: str | None
    slack_webhook_url: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        def required(name: str) -> str:
            value = os.environ.get(name, "").strip()
            if not value:
                raise ConfigError(f"Missing required setting {name} (see .env.example)")
            return value

        def optional(name: str) -> str | None:
            return os.environ.get(name, "").strip() or None

        return cls(
            jira_base_url=required("JIRA_BASE_URL").rstrip("/"),
            jira_email=required("JIRA_EMAIL"),
            jira_api_token=required("JIRA_API_TOKEN"),
            jira_project_key=required("JIRA_PROJECT_KEY"),
            jira_issue_type=optional("JIRA_ISSUE_TYPE") or "Task",
            jira_ac_field=optional("JIRA_ACCEPTANCE_CRITERIA_FIELD"),
            team=load_team(),
            drive_folder_id=optional("DRIVE_FOLDER_ID"),
            google_service_account_json=optional("GOOGLE_SERVICE_ACCOUNT_JSON"),
            process_since_days=int(optional("PROCESS_SINCE_DAYS") or 7),
            smtp_host=optional("SMTP_HOST"),
            smtp_port=int(optional("SMTP_PORT") or 587),
            smtp_user=optional("SMTP_USER"),
            smtp_password=optional("SMTP_PASSWORD"),
            email_from=optional("EMAIL_FROM") or optional("SMTP_USER"),
            slack_webhook_url=optional("SLACK_WEBHOOK_URL"),
        )


def load_team() -> list[TeamMember]:
    """Read the team roster from TEAM_JSON (inline JSON) or TEAM_FILE (default team.json)."""
    raw = os.environ.get("TEAM_JSON", "").strip()
    if not raw:
        path = Path(os.environ.get("TEAM_FILE", "team.json"))
        if not path.exists():
            raise ConfigError(
                f"No team roster found. Create {path} (copy team.example.json) or set TEAM_JSON."
            )
        raw = path.read_text()
    return parse_team(json.loads(raw))


def parse_team(data: list[dict]) -> list[TeamMember]:
    return [
        TeamMember(
            name=m["name"],
            email=m["email"],
            aliases=list(m.get("aliases", [])),
            jira_account_id=m.get("jira_account_id"),
        )
        for m in data
    ]
