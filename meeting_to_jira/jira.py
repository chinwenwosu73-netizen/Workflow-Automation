"""Minimal Jira Cloud REST v3 client."""

from __future__ import annotations

from dataclasses import dataclass

import requests

from .extract import Ticket


class JiraError(RuntimeError):
    pass


# --- Atlassian Document Format helpers (Jira Cloud v3 rich-text fields) ---

def _text(value: str) -> dict:
    return {"type": "text", "text": value}


def paragraph(value: str) -> dict:
    return {"type": "paragraph", "content": [_text(value)] if value else []}


def heading(value: str, level: int = 3) -> dict:
    return {"type": "heading", "attrs": {"level": level}, "content": [_text(value)]}


def bullet_list(items: list[str]) -> dict:
    return {
        "type": "bulletList",
        "content": [{"type": "listItem", "content": [paragraph(i)]} for i in items],
    }


def doc(*blocks: dict) -> dict:
    return {"type": "doc", "version": 1, "content": list(blocks)}


@dataclass
class OpenIssue:
    key: str
    summary: str
    status: str
    url: str


class JiraClient:
    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        project_key: str,
        issue_type: str = "Task",
        ac_field: str | None = None,
        session: requests.Session | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.project_key = project_key
        self.issue_type = issue_type
        self.ac_field = ac_field
        self.session = session or requests.Session()
        self.session.auth = (email, api_token)
        self.session.headers.update({"Accept": "application/json"})

    def _request(self, method: str, path: str, **kwargs) -> dict:
        resp = self.session.request(method, f"{self.base_url}{path}", timeout=30, **kwargs)
        if not resp.ok:
            raise JiraError(f"Jira {method} {path} failed ({resp.status_code}): {resp.text[:500]}")
        return resp.json() if resp.content else {}

    def issue_url(self, key: str) -> str:
        return f"{self.base_url}/browse/{key}"

    def find_account_id(self, email: str) -> str | None:
        users = self._request("GET", "/rest/api/3/user/search", params={"query": email})
        return users[0]["accountId"] if users else None

    def build_fields(
        self, ticket: Ticket, account_id: str | None, labels: list[str], source: str
    ) -> dict:
        blocks = [heading("User story"), paragraph(ticket.user_story),
                  heading("Details"), paragraph(ticket.description)]
        if not self.ac_field:
            blocks += [heading("Acceptance criteria"), bullet_list(ticket.acceptance_criteria)]
        blocks.append(paragraph(f"Created automatically from meeting notes: {source}"))

        fields: dict = {
            "project": {"key": self.project_key},
            "issuetype": {"name": ticket.issue_type},
            "summary": ticket.summary,
            "description": doc(*blocks),
            "labels": labels,
            "priority": {"name": ticket.priority},
        }
        if self.ac_field:
            fields[self.ac_field] = doc(bullet_list(ticket.acceptance_criteria))
        if account_id:
            fields["assignee"] = {"accountId": account_id}
        return fields

    def create_issue(self, fields: dict) -> str:
        try:
            return self._request("POST", "/rest/api/3/issue", json={"fields": fields})["key"]
        except JiraError as err:
            # Many projects don't have every issue type or priority; retry with safe defaults.
            if "issuetype" not in str(err) and "priority" not in str(err):
                raise
            fallback = dict(fields, issuetype={"name": self.issue_type})
            fallback.pop("priority", None)
            return self._request("POST", "/rest/api/3/issue", json={"fields": fallback})["key"]

    def open_issues_for(self, account_id: str, stale_hours: int) -> list[OpenIssue]:
        jql = (
            f'project = "{self.project_key}" AND assignee = "{account_id}" '
            f"AND statusCategory != Done AND updated <= -{stale_hours}h ORDER BY updated ASC"
        )
        data = self._request(
            "GET",
            "/rest/api/3/search/jql",
            params={"jql": jql, "fields": "summary,status", "maxResults": 50},
        )
        return [
            OpenIssue(
                key=i["key"],
                summary=i["fields"]["summary"],
                status=i["fields"]["status"]["name"],
                url=self.issue_url(i["key"]),
            )
            for i in data.get("issues", [])
        ]
