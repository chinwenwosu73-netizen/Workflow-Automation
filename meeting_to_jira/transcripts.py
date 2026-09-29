"""Where transcripts come from: a Google Drive folder, or a local file."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

GOOGLE_DOC = "application/vnd.google-apps.document"
PROCESSED_KEY = "jiraProcessed"


@dataclass
class Transcript:
    id: str
    title: str
    text: str


def read_local(path: str) -> Transcript:
    p = Path(path)
    return Transcript(id=str(p), title=p.stem, text=p.read_text(encoding="utf-8"))


class DriveTranscriptSource:
    """Reads new transcripts from a Drive folder, e.g. Google Meet's "Meet Recordings".

    Share the folder with the service account's email (as Editor) so it can read the
    transcripts and tag each one as processed.
    """

    def __init__(self, folder_id: str, service_account_json: str, since_days: int = 7):
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        info = json.loads(service_account_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive"]
        )
        self.drive = build("drive", "v3", credentials=creds, cache_discovery=False)
        self.folder_id = folder_id
        self.since_days = since_days

    def pending(self) -> list[Transcript]:
        since = (datetime.now(timezone.utc) - timedelta(days=self.since_days)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        query = (
            f"'{self.folder_id}' in parents and trashed = false "
            f"and (mimeType = '{GOOGLE_DOC}' or mimeType = 'text/plain') "
            f"and createdTime > '{since}' "
            f"and not appProperties has {{ key='{PROCESSED_KEY}' and value='true' }}"
        )
        files = (
            self.drive.files()
            .list(q=query, fields="files(id,name,mimeType)", orderBy="createdTime",
                  supportsAllDrives=True, includeItemsFromAllDrives=True)
            .execute()
            .get("files", [])
        )
        return [Transcript(id=f["id"], title=f["name"], text=self._read(f)) for f in files]

    def _read(self, f: dict) -> str:
        if f["mimeType"] == GOOGLE_DOC:
            data = self.drive.files().export(fileId=f["id"], mimeType="text/plain").execute()
        else:
            data = self.drive.files().get_media(fileId=f["id"], supportsAllDrives=True).execute()
        return data.decode("utf-8") if isinstance(data, bytes) else data

    def mark_processed(self, transcript: Transcript) -> None:
        self.drive.files().update(
            fileId=transcript.id,
            body={"appProperties": {PROCESSED_KEY: "true"}},
            supportsAllDrives=True,
        ).execute()
