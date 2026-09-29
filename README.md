# Meeting notes → Jira, automatically (works with a free Google account)

## The story in one picture

```
 1. You have a Google Meet call
        │
        ▼
 2. TranscripTonic (a free Chrome add-on) writes down everything people say
        │  when the call ends, it sends the notes to…
        ▼
 3. A Google Doc in your Drive folder called "TranscripTonic"
        │  every hour, a robot (GitHub Actions, free) checks that folder
        ▼
 4. Claude reads the notes and writes the tickets:
        user story + details + acceptance criteria + who owns it
        │
        ▼
 5. The tickets appear in Jira, assigned to the right developer
        │
        ▼
 6. Each developer gets an email: "Here are your new tickets"
        │
        ▼
 7. Every 6 hours: "These tickets haven't moved. Please update them."
```

You join the meeting and turn on captions. The robot does everything else.

## What each piece does and what it costs

| Piece | Its job | Cost |
|---|---|---|
| Google Meet (free account) | Where you hold the meeting | Free |
| **TranscripTonic** Chrome extension | The note taker. It saves Meet's captions as a transcript. | Free and open source |
| Google Apps Script | Catches the transcript and saves it as a Google Doc in Drive | Free |
| Google Drive | The inbox that holds the transcripts | Free |
| GitHub Actions | The robot that runs every hour and every 6 hours | Free (a private repo gets 2,000 minutes a month; this uses roughly 900–1,700. Public repos have no limit.) |
| **Claude API** | Reads the notes and writes stories, tasks and acceptance criteria | **The one paid part:** a few cents per meeting, about $1 a month for one weekly meeting (a rough estimate) |
| Jira Cloud | Where the tickets live | Free plan (up to 10 users) |
| Gmail | Sends the reminder emails | Free |

---

## Setup, step by step

Each step takes about 5–10 minutes. Do them in order. There are six steps, and you only do them once.

### Step 1: Install the note taker (TranscripTonic)

1. Open **Google Chrome** on the computer you use for meetings.
2. Go to the Chrome Web Store and install **TranscripTonic**. Its homepage is <https://github.com/vivek-nexus/transcriptonic>.
3. Join a test Google Meet call, turn on **captions (CC)**, say a few words, then leave.
4. A `.txt` file with what you said should download. If it does, the note taker works. ✅

> The add-on works by reading Meet's live captions, so **captions must be on** in every meeting. The person running the add-on (you) has to be in the call.

### Step 2: Make the note taker drop transcripts into Google Drive automatically

TranscripTonic can send each transcript to a small free Google script, and that script turns it into a Google Doc.

1. Follow TranscripTonic's **Google Docs integration guide**: <https://github.com/vivek-nexus/transcriptonic/wiki/Google-Docs-integration-guide>. In short:
   - Go to <https://script.google.com>, create a new project and paste in the script from the guide.
   - Click **Deploy → New deployment → Web app**. Set it to run as **you** and to be accessible by **Anyone**. Copy the Web App URL.
   - In TranscripTonic, open the **webhooks** page, paste the URL and click Save.
   - Tick **"Automatically post transcript after each meeting"** and choose **"Simple webhook body"**.
2. Do another short test call. A folder called **TranscripTonic** should appear in your Google Drive with a Doc inside. ✅
3. Open that folder and copy its ID from the address bar: `drive.google.com/drive/folders/`**`THIS_LONG_PART`**. You'll need it later.

### Step 3: Give the robot permission to read that folder

The robot needs its own Google "robot account", which Google calls a service account. It's free, and you don't need a credit card.

1. Go to <https://console.cloud.google.com> and sign in with your free Google account.
2. At the top, click **Select a project → New project**. Call it `meeting-to-jira` and click Create.
3. Search for **Google Drive API** and click **Enable**.
4. Go to **IAM & Admin → Service accounts → Create service account**. Name it `meeting-bot`, then click Done.
5. Click the new service account, go to **Keys → Add key → Create new key → JSON**. A file downloads. **Keep it secret.**
6. Copy the service account's email address (it looks like `meeting-bot@meeting-to-jira.iam.gserviceaccount.com`).
7. In Google Drive, right-click the **TranscripTonic** folder, choose **Share**, paste that email and make it an **Editor**. ✅

### Step 4: Get your Jira key

1. Go to <https://id.atlassian.com/manage-profile/security/api-tokens> and create an API token. Copy it.
2. Write down:
   - your Jira address, e.g. `https://yourcompany.atlassian.net`
   - the email you log into Jira with
   - your project key: the letters in front of ticket numbers, e.g. `PROJ` in `PROJ-12`
3. Optional: if your Jira has an **Acceptance Criteria** field, find its id (e.g. `customfield_10050`) under *Settings → Issues → Custom fields*. If not, the acceptance criteria go in the ticket description, which works fine. ✅

### Step 5: Get your Claude key and Gmail sending password

1. **Claude:** go to <https://console.anthropic.com>, add a small amount of credit (e.g. $5 lasts months), then open **API keys → Create key** and copy it.
2. **Gmail:** turn on **2-Step Verification** for your Google account. Then go to <https://myaccount.google.com/apppasswords> and create an app password named `meeting-bot`. Copy the 16 letters. This lets the robot send email from your Gmail. ✅

### Step 6: Put everything into GitHub and switch the robot on

1. Open this repository on GitHub and go to **Settings → Secrets and variables → Actions**.
2. On the **Secrets** tab, click **New repository secret** for each of these (secrets are hidden once saved):

   | Name | What to paste |
   |---|---|
   | `ANTHROPIC_API_KEY` | Claude key (step 5) |
   | `JIRA_API_TOKEN` | Jira token (step 4) |
   | `GOOGLE_SERVICE_ACCOUNT_JSON` | The **whole contents** of the JSON key file (step 3) |
   | `SMTP_PASSWORD` | The 16-letter Gmail app password (step 5) |

3. On the **Variables** tab, add:

   | Name | Example |
   |---|---|
   | `JIRA_BASE_URL` | `https://yourcompany.atlassian.net` |
   | `JIRA_EMAIL` | `you@gmail.com` |
   | `JIRA_PROJECT_KEY` | `PROJ` |
   | `DRIVE_FOLDER_ID` | the folder ID from step 2 |
   | `SMTP_HOST` | `smtp.gmail.com` |
   | `SMTP_USER` | `you@gmail.com` |
   | `TEAM_JSON` | your team list, see below |
   | `JIRA_ACCEPTANCE_CRITERIA_FIELD` | *(optional)* `customfield_10050` |
   | `REMINDER_STALE_HOURS` | *(optional)* `6` |

   `TEAM_JSON` tells Claude who's who. Use the **same email each developer uses for Jira**. Add nicknames under `aliases`, because captions often mishear names:
   ```json
   [
     {"name": "Ada Obi", "email": "ada@gmail.com", "aliases": ["Ada"]},
     {"name": "Tunde Bello", "email": "tunde@gmail.com", "aliases": ["Tunde", "TB"]}
   ]
   ```

4. Go to the **Actions** tab. If GitHub asks, click **"I understand my workflows, go ahead and enable them"**.
5. Click **Meeting notes to Jira → Run workflow → process**. When it goes green ✅, check Jira for new tickets.
6. Run it again with **remind** to test the reminder emails.

**You're done.** 🎉 From now on:

- **Every hour**, the robot looks for new transcripts and turns them into Jira tickets. Each transcript is only used once.
- **Every 6 hours** (00:30, 06:30, 12:30 and 18:30 UTC), each developer with open tickets that haven't been updated in 6 hours gets a reminder email. Developers with nothing stale get no email.

---

## Your routine after setup

1. Start the Google Meet call and **turn on captions**.
2. Have the meeting. Say owners out loud, e.g. *"Tunde, can you take the webhook retry?"*
3. Leave the call. That's it.
4. Within about an hour, the tickets are in Jira and the developers have their emails.
5. Look over the new tickets (filter by the label `from-meeting`) and fix anything Claude got wrong.

## What a ticket looks like

> **Add retry to payment webhook**  · Bug · High · assigned to Tunde Bello
>
> **User story:** As a customer, I want my payment to be confirmed even if the payment provider is slow, so that my order doesn't get stuck in "pending".
>
> **Details:** When the payment webhook times out, we never retry, so some orders stay pending. Add retries with backoff (about 3 attempts) and log the final failure.
>
> **Acceptance criteria**
> - Given the webhook times out, when it fails, then it is retried up to 3 times with increasing delay
> - Given all retries fail, then an error is logged with the order ID
> - Given a retry succeeds, then the order moves from "pending" to "paid"

## Try it on your computer first (optional)

```bash
pip install -r requirements.txt
cp .env.example .env              # at minimum, add ANTHROPIC_API_KEY
cp team.example.json team.json    # add your developers
python -m meeting_to_jira process --file samples/standup_transcript.txt --dry-run
```

This prints the tickets Claude *would* create and doesn't touch Jira.

## Changing things

- **How tickets are written** (story style, number of acceptance criteria, what counts as a task): edit `SYSTEM_PROMPT` in `meeting_to_jira/extract.py`.
- **How often it runs:** edit the `cron` lines in `.github/workflows/meeting-to-jira.yml`. The times are UTC. For example, `30 8,14 * * 1-5` means 08:30 and 14:30 on weekdays.
- **How "stale" a ticket must be before a reminder:** the `REMINDER_STALE_HOURS` variable.

## If something goes wrong

| Problem | Fix |
|---|---|
| No `.txt` downloads after a meeting | Captions weren't on, or you left before anyone spoke. Turn on CC. |
| No Doc appears in the TranscripTonic folder | Check the webhook URL in TranscripTonic and that "Automatically post" is ticked. |
| The Actions run says `File not found` / 404 for Drive | The folder isn't shared with the service-account email, or `DRIVE_FOLDER_ID` is wrong. |
| Tickets are created but unassigned | The name said in the meeting isn't in `TEAM_JSON`. Add it under `aliases`. Also check the email matches the developer's Jira login. |
| No emails arrive | Check `SMTP_USER` and `SMTP_PASSWORD` (the app password, not your normal password), and look in spam. |
| A Jira error mentions `issuetype` or `priority` | Your project doesn't have Story, Bug or that priority. The tool retries as a plain Task, so check that `JIRA_ISSUE_TYPE` exists. |

Every run's log is on the **Actions** tab. Click a run to see what happened.

## Good to know

- Captions-based transcripts aren't perfect, so names and technical words can be misheard. Claude corrects for this using context and the `aliases` in your team list.
- Claude only makes tickets for work someone owned or was asked to do. When it isn't sure who owns something, it leaves the ticket unassigned instead of guessing.
- If a transcript fails partway, it's retried on the next run. Tickets created before the failure could be created twice.
- Tests: `pip install -r requirements-dev.txt && pytest`.
