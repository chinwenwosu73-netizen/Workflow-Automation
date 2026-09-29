"""Command line entry point.

    python -m meeting_to_jira process [--file transcript.txt] [--dry-run]
    python -m meeting_to_jira remind [--stale-hours 6] [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import defaultdict
from datetime import date

from .config import Settings, TeamMember, load_team
from .extract import MeetingNotes, extract_meeting_notes
from .jira import JiraClient
from .notify import Notifier, new_tickets_body, stale_tickets_body
from .transcripts import DriveTranscriptSource, Transcript, read_local

log = logging.getLogger("meeting_to_jira")


def jira_from(settings: Settings) -> JiraClient:
    return JiraClient(
        settings.jira_base_url,
        settings.jira_email,
        settings.jira_api_token,
        settings.jira_project_key,
        settings.jira_issue_type,
        settings.jira_ac_field,
    )


def notifier_from(settings: Settings, dry_run: bool) -> Notifier:
    return Notifier(
        settings.smtp_host,
        settings.smtp_port,
        settings.smtp_user,
        settings.smtp_password,
        settings.email_from,
        settings.slack_webhook_url,
        dry_run=dry_run,
    )


def account_ids(jira: JiraClient, team: list[TeamMember]) -> dict[str, str | None]:
    ids = {}
    for member in team:
        ids[member.name] = member.jira_account_id or jira.find_account_id(member.email)
        if ids[member.name] is None:
            log.warning("No Jira user found for %s <%s>", member.name, member.email)
    return ids


def print_notes(title: str, notes: MeetingNotes) -> None:
    print(f"\n=== {title} ===\n\nSummary: {notes.meeting_summary}\n")
    for label, items in (("Decisions", notes.decisions), ("Blockers", notes.blockers)):
        if items:
            print(f"{label}:\n" + "\n".join(f"  - {i}" for i in items) + "\n")
    for n, t in enumerate(notes.tickets, 1):
        print(f"[{n}] {t.issue_type} | {t.priority} | {t.assignee or 'unassigned'}")
        print(f"    {t.summary}\n    Story: {t.user_story}\n    {t.description}")
        print("    Acceptance criteria:\n" + "\n".join(f"      - {c}" for c in t.acceptance_criteria))
        print()


def process_transcript(
    transcript: Transcript,
    team: list[TeamMember],
    jira: JiraClient,
    ids: dict[str, str | None],
    notifier: Notifier,
) -> list[str]:
    notes = extract_meeting_notes(transcript.text, team, transcript.title)
    print_notes(transcript.title, notes)

    labels = ["from-meeting", f"meeting-{date.today().isoformat()}"]
    per_person: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    created = []
    for ticket in notes.tickets:
        account_id = ids.get(ticket.assignee) if ticket.assignee else None
        key = jira.create_issue(jira.build_fields(ticket, account_id, labels, transcript.title))
        created.append(key)
        log.info("Created %s: %s", key, ticket.summary)
        if ticket.assignee:
            per_person[ticket.assignee].append((key, ticket.summary, jira.issue_url(key)))

    by_name = {m.name: m for m in team}
    for name, tickets in per_person.items():
        notifier.email(
            by_name[name].email,
            f"[{jira.project_key}] {len(tickets)} new ticket(s) from {transcript.title}",
            new_tickets_body(name, transcript.title, tickets),
        )
    if created:
        lines = [f"*{transcript.title}* — {len(created)} ticket(s) created", notes.meeting_summary]
        lines += [f"• <{jira.issue_url(k)}|{k}>" for k in created]
        notifier.slack("\n".join(lines))
    return created


def cmd_process(args: argparse.Namespace) -> int:
    if args.dry_run:
        # Only needs ANTHROPIC_API_KEY and the team roster: nothing is written anywhere.
        if not args.file:
            log.error("--dry-run needs --file")
            return 2
        transcript = read_local(args.file)
        print_notes(transcript.title, extract_meeting_notes(transcript.text, load_team(), transcript.title))
        return 0

    settings = Settings.from_env()
    jira = jira_from(settings)
    notifier = notifier_from(settings, dry_run=False)
    ids = account_ids(jira, settings.team)

    if args.file:
        process_transcript(read_local(args.file), settings.team, jira, ids, notifier)
        return 0

    if not (settings.drive_folder_id and settings.google_service_account_json):
        log.error("Set DRIVE_FOLDER_ID and GOOGLE_SERVICE_ACCOUNT_JSON, or pass --file")
        return 2
    source = DriveTranscriptSource(
        settings.drive_folder_id, settings.google_service_account_json, settings.process_since_days
    )
    pending = source.pending()
    log.info("%d new transcript(s) found", len(pending))
    failures = 0
    for transcript in pending:
        try:
            process_transcript(transcript, settings.team, jira, ids, notifier)
        except Exception:
            failures += 1
            log.exception("Failed to process %s", transcript.title)
            continue
        source.mark_processed(transcript)
    return 1 if failures else 0


def cmd_remind(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    jira = jira_from(settings)
    notifier = notifier_from(settings, dry_run=args.dry_run)
    summary = []
    for member in settings.team:
        account_id = member.jira_account_id or jira.find_account_id(member.email)
        if not account_id:
            log.warning("No Jira user found for %s <%s>", member.name, member.email)
            continue
        issues = jira.open_issues_for(account_id, args.stale_hours)
        if not issues:
            continue
        notifier.email(
            member.email,
            f"[{jira.project_key}] Reminder: {len(issues)} ticket(s) need a status update",
            stale_tickets_body(member.name, args.stale_hours, issues),
        )
        summary.append(f"• {member.name}: " + ", ".join(f"<{i.url}|{i.key}>" for i in issues))
    if summary:
        notifier.slack("Tickets that haven't moved recently — please update before stand-up:\n" + "\n".join(summary))
    log.info("Reminders sent to %d team member(s)", len(summary))
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(prog="meeting_to_jira", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("process", help="Turn new meeting transcripts into Jira tickets")
    p.add_argument("--file", help="Process a local transcript file instead of Google Drive")
    p.add_argument("--dry-run", action="store_true", help="Show extracted tickets without creating them")
    p.set_defaults(func=cmd_process)

    r = sub.add_parser("remind", help="Remind developers about tickets that haven't moved")
    r.add_argument(
        "--stale-hours", type=int, default=int(os.environ.get("REMINDER_STALE_HOURS") or 6),
        help="Remind about open tickets not updated for this many hours (default 6)",
    )
    r.add_argument("--dry-run", action="store_true", help="Log reminders instead of sending them")
    r.set_defaults(func=cmd_remind)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
