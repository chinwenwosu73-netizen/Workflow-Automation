from types import SimpleNamespace

import pytest

from meeting_to_jira import cli
from meeting_to_jira.config import parse_team
from meeting_to_jira.extract import MeetingNotes, Ticket, extract_meeting_notes, normalize_assignees
from meeting_to_jira.jira import JiraClient, JiraError
from meeting_to_jira.notify import Notifier
from meeting_to_jira.transcripts import Transcript

TEAM = parse_team([
    {"name": "Ada Obi", "email": "ada@example.com", "aliases": ["Ada"]},
    {"name": "Tunde Bello", "email": "tunde@example.com", "aliases": ["Tunde"]},
])


def make_ticket(**overrides) -> Ticket:
    values = dict(
        summary="Add retry to payment webhook",
        user_story="As a customer, I want my payment confirmed, so that my order ships.",
        description="Webhook timeouts leave orders pending.",
        acceptance_criteria=["Given a timeout, when the webhook fails, then it retries 3 times"],
        assignee="Tunde",
        issue_type="Bug",
        priority="High",
    )
    values.update(overrides)
    return Ticket(**values)


def make_notes(*tickets: Ticket) -> MeetingNotes:
    return MeetingNotes(meeting_summary="Stand-up", decisions=[], blockers=[], tickets=list(tickets))


def test_normalize_assignees_maps_aliases_and_drops_unknown():
    notes = make_notes(make_ticket(assignee="tunde"), make_ticket(assignee="Zed"), make_ticket(assignee=None))
    normalize_assignees(notes, TEAM)
    assert [t.assignee for t in notes.tickets] == ["Tunde Bello", None, None]


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def fake_client(response):
    messages = FakeMessages(response)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def test_extract_sends_roster_and_transcript():
    client, messages = fake_client(
        SimpleNamespace(stop_reason="end_turn", parsed_output=make_notes(make_ticket(assignee="Ada")))
    )
    notes = extract_meeting_notes("Ada: I'll fix it", TEAM, "Stand-up", client=client)
    assert notes.tickets[0].assignee == "Ada Obi"
    content = messages.kwargs["messages"][0]["content"]
    assert "Ada Obi (also called: Ada)" in content
    assert "<transcript>\nAda: I'll fix it\n</transcript>" in content
    assert messages.kwargs["output_format"] is MeetingNotes


def test_extract_raises_on_refusal():
    client, _ = fake_client(SimpleNamespace(stop_reason="refusal", parsed_output=None))
    with pytest.raises(Exception, match="declined"):
        extract_meeting_notes("text", TEAM, client=client)


def jira(ac_field=None) -> JiraClient:
    return JiraClient("https://x.atlassian.net/", "me@x.com", "token", "PROJ", ac_field=ac_field)


def test_build_fields_puts_acceptance_criteria_in_description():
    fields = jira().build_fields(make_ticket(), "acc-1", ["from-meeting"], "Stand-up")
    assert fields["assignee"] == {"accountId": "acc-1"}
    assert fields["issuetype"] == {"name": "Bug"}
    kinds = [b["type"] for b in fields["description"]["content"]]
    assert kinds == ["heading", "paragraph", "heading", "paragraph", "heading", "bulletList", "paragraph"]
    assert fields["description"]["content"][1]["content"][0]["text"].startswith("As a customer")


def test_build_fields_uses_custom_acceptance_criteria_field():
    fields = jira("customfield_1").build_fields(make_ticket(), None, [], "Stand-up")
    assert "assignee" not in fields
    assert fields["customfield_1"]["content"][0]["type"] == "bulletList"
    headings = [b for b in fields["description"]["content"] if b["type"] == "heading"]
    assert [h["content"][0]["text"] for h in headings] == ["User story", "Details"]


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self.ok = status < 400
        self.payload = payload
        self.text = str(payload)
        self.content = b"x"

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}
        self.auth = None

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def test_create_issue_retries_without_unsupported_issue_type():
    session = FakeSession([
        FakeResponse(400, {"errors": {"issuetype": "invalid"}}),
        FakeResponse(201, {"key": "PROJ-7"}),
    ])
    client = JiraClient("https://x.atlassian.net", "e", "t", "PROJ", "Task", session=session)
    key = client.create_issue(client.build_fields(make_ticket(issue_type="Story"), None, [], "m"))
    assert key == "PROJ-7"
    retry_fields = session.calls[1][2]["json"]["fields"]
    assert retry_fields["issuetype"] == {"name": "Task"}
    assert "priority" not in retry_fields


def test_create_issue_raises_other_errors():
    session = FakeSession([FakeResponse(403, {"errorMessages": ["no permission"]})])
    client = JiraClient("https://x.atlassian.net", "e", "t", "PROJ", session=session)
    with pytest.raises(JiraError):
        client.create_issue({"summary": "x"})


def test_process_transcript_creates_tickets_and_emails_assignees(monkeypatch):
    notes = make_notes(make_ticket(assignee="Tunde Bello"), make_ticket(summary="Unowned", assignee=None))
    monkeypatch.setattr(cli, "extract_meeting_notes", lambda *a, **k: notes)

    created_fields = []

    class FakeJira(JiraClient):
        def create_issue(self, fields):
            created_fields.append(fields)
            return f"PROJ-{len(created_fields)}"

    emails = []
    notifier = Notifier(dry_run=True)
    notifier.email = lambda to, subject, body: emails.append((to, subject, body))

    keys = cli.process_transcript(
        Transcript("id", "Stand-up", "..."), TEAM,
        FakeJira("https://x.atlassian.net", "e", "t", "PROJ"),
        {"Ada Obi": "a", "Tunde Bello": "t"}, notifier,
    )
    assert keys == ["PROJ-1", "PROJ-2"]
    assert created_fields[0]["assignee"] == {"accountId": "t"}
    assert "assignee" not in created_fields[1]
    assert len(emails) == 1 and emails[0][0] == "tunde@example.com"
    assert "PROJ-1" in emails[0][2]
