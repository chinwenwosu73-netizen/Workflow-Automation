"""Turn a meeting transcript into structured Jira tickets using Claude."""

from __future__ import annotations

import logging
from typing import Literal

import anthropic
from pydantic import BaseModel

from .config import TeamMember

log = logging.getLogger(__name__)

MODEL = "claude-opus-5"

SYSTEM_PROMPT = """\
You are a product manager's assistant. You read transcripts of a software team's \
stand-up and planning meetings and turn the concrete work items into Jira tickets.

Guidelines:
- Create a ticket only for actionable work someone committed to or was asked to do. \
Skip status chatter, work already finished, and vague ideas nobody owns.
- Merge duplicate mentions of the same work into one ticket.
- summary: a short imperative title (under 80 characters), e.g. "Add retry to payment webhook".
- user_story: one sentence in the form "As a <type of user>, I want <goal>, so that <benefit>." \
Pick the user who benefits (a customer, an admin, a developer, the support team, ...).
- description: 2-4 sentences of context from the meeting: what, why, and any constraints, \
links, or dependencies mentioned. Do not invent details that were not said.
- acceptance_criteria: 2-6 testable statements, written in Given/When/Then form where it \
fits. Base them on what was discussed; where the meeting left something implicit, write \
the criterion a reasonable PM would expect and keep it conservative.
- assignee: the team member's canonical name from the roster, matched by name or alias. \
Use null if nobody clearly owns the work or the person is not on the roster.
- issue_type: Bug for defects, Story for user-facing features, Task otherwise.
- priority: Medium unless urgency or blocking was discussed.
- Transcripts come from speech recognition, so names and technical terms may be misspelled; \
use context to interpret them.
"""


class Ticket(BaseModel):
    summary: str
    user_story: str
    description: str
    acceptance_criteria: list[str]
    assignee: str | None
    issue_type: Literal["Task", "Bug", "Story"]
    priority: Literal["Highest", "High", "Medium", "Low", "Lowest"]


class MeetingNotes(BaseModel):
    meeting_summary: str
    decisions: list[str]
    blockers: list[str]
    tickets: list[Ticket]


class ExtractionError(RuntimeError):
    pass


def _roster_text(team: list[TeamMember]) -> str:
    lines = []
    for member in team:
        aliases = f" (also called: {', '.join(member.aliases)})" if member.aliases else ""
        lines.append(f"- {member.name}{aliases}")
    return "\n".join(lines)


def extract_meeting_notes(
    transcript: str,
    team: list[TeamMember],
    meeting_title: str = "Team meeting",
    client: anthropic.Anthropic | None = None,
) -> MeetingNotes:
    client = client or anthropic.Anthropic()
    user_content = (
        f"Meeting: {meeting_title}\n\n"
        f"<team_roster>\n{_roster_text(team)}\n</team_roster>\n\n"
        f"<transcript>\n{transcript}\n</transcript>"
    )
    response = client.beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        # If the request is declined, the API retries on Anthropic's recommended fallback model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
        output_format=MeetingNotes,
    )
    if response.stop_reason == "refusal":
        raise ExtractionError("Claude declined to process this transcript.")
    if response.stop_reason == "max_tokens":
        raise ExtractionError("Response was cut off; the transcript may be too long.")
    notes = response.parsed_output
    if notes is None:
        raise ExtractionError("Claude returned no structured output.")
    return normalize_assignees(notes, team)


def normalize_assignees(notes: MeetingNotes, team: list[TeamMember]) -> MeetingNotes:
    """Map assignee names to canonical roster names; drop names that are not on the roster."""
    lookup: dict[str, str] = {}
    for member in team:
        for name in [member.name, *member.aliases]:
            lookup[name.strip().lower()] = member.name
    for ticket in notes.tickets:
        if ticket.assignee is None:
            continue
        canonical = lookup.get(ticket.assignee.strip().lower())
        if canonical is None:
            log.warning("Assignee %r is not on the team roster; leaving unassigned", ticket.assignee)
        ticket.assignee = canonical
    return notes
