# Gmail Sender List Exporter

A small Google Apps Script tool. It reads a Gmail mailbox and builds a
brand-new Google Sheet with **one row per unique sender**.

Output columns: **First Name**, **Last Name**, **Email Address**,
**From (raw header)**. The raw header is only there so you can check that
the first name / last name / email were split correctly.

It runs entirely inside the user's own Google account (no API keys, no
credentials file) -- each org member sets it up once in their own Gmail/Sheets,
using their own login, and it only ever touches their own mailbox.

## How it handles a big mailbox

Apps Script cancels any single run after 6 minutes, and a mailbox can hold
hundreds of thousands of messages. So the export is a background job:

- It reads the mailbox one month at a time, **newest month first**.
- After about 4 minutes it saves its place, adds the new senders to the
  sheet, and schedules itself to run again a minute later.
- It repeats until it reaches the oldest month. The job runs on Google's
  servers, so the laptop can be closed or turned off.
- Each new sender is checked against the senders already in the sheet, so
  each email address appears once (the case of the address is ignored). The
  row kept is from the newest message, so the name is the most recent one.
- If a run fails (usually Google's daily quota), it tries again in an hour,
  for up to two days, and carries on from where it stopped.

### Google's daily limits

These come from [Apps Script's quota page](https://developers.google.com/apps-script/guides/services/quotas):

| | Consumer (gmail.com) | Google Workspace |
|---|---|---|
| Total background run time per day | 90 minutes | 6 hours |
| Gmail reads/writes per day | 20,000 | 50,000 |

Google doesn't say whether the Gmail limit counts messages or calls. If it
counts messages, a mailbox of 300,000 messages needs about 6 days on
Workspace (the job simply waits out each day's limit and continues). If it
takes far longer than you expect, the alternative that has no daily limit
is Google Takeout: export the mailbox as an `.mbox` file and read the
`From:` headers with a Python script (the `mailbox` module in the standard
library does this).

## Setup (one time, per person)

1. Go to [sheets.google.com](https://sheets.google.com) and create a new
   blank spreadsheet. (This spreadsheet is just the "launcher" -- the actual
   results land in a *separate*, brand-new sheet each time you start an
   export.)
2. In the menu bar: **Extensions > Apps Script**. This opens the script
   editor in a new tab.
3. Delete whatever is in the default `Code.gs` file and paste in the
   contents of [`Code.gs`](Code.gs) from this folder.
4. In the script editor, click the **+** next to "Files" and choose
   **HTML**. Name the new file exactly `Dialog` (Apps Script adds the
   `.html` extension automatically). Paste in the contents of
   [`Dialog.html`](Dialog.html) from this folder.
5. Save the project (File > Save, or Ctrl/Cmd+S).
6. Go back to the Google Sheet tab and reload the page.
7. A new menu should appear: **Sender Export**. Click it, then
   **Start export...**.
8. The first time you run it, Google will ask you to authorize the script
   (it needs permission to read Gmail, create Sheets, and run in the
   background when you are not present). Since this is a
   personal/unpublished script, you'll likely see an "unverified app"
   screen -- this is expected for scripts you write or paste yourself.
   Click **Advanced**, then **Go to (project name) (unsafe)**, then
   **Allow**.

If you set up an earlier version of this tool, paste in the new `Code.gs`
**and** `Dialog.html`, save, reload, and authorize again (the background
permission is new).

## Using it

- **Sender Export > Start export...** opens a dialog:
  - **What to search**: All Mail (the default; every folder except
    Spam/Trash), Inbox only, or one of your Gmail labels.
  - **Date range** (optional): leave both blank to cover all dates. The To
    date is inclusive.
  - **Skip senders that are not people** (checked by default): leaves out
    addresses like info@, hello@, support@, no-reply@, and similar. The
    lists are `NON_PERSON_NAMES` and `NON_PERSON_FRAGMENTS` at the top of
    `Code.gs`; edit them to taste.
- Click **Start Export** and keep the box open for the first few minutes.
  It then reports how far it got and gives a link to the results sheet.
- After that it continues on its own. **Sender Export > Show progress**
  tells you how many senders it has found and how far back it has read.
- **Sender Export > Stop export** cancels the job. What was already written
  stays in the sheet. Only one export can run at a time.

## Notes

- The script only reads mail; it never sends, deletes, or modifies
  anything in Gmail.
- Messages whose From header has no email address are skipped.
- The results sheet is filled in as the job runs, newest senders first, so
  you can open it and look while it is still working.
- Names are split on whitespace: the last word is the last name and
  everything before it is the first name, except common suffixes (Jr., Sr.,
  II, III, IV, V) are folded into a multi-word last name (e.g. "John Smith
  Jr." -> first name "John", last name "Smith Jr."). This is a simple
  heuristic and won't be right for every name (multi-word last names without
  a suffix, single-word display names, names in "Last, First" order); the
  raw header column is there to check.
- From-header parsing handles the common forms (`Name <email@x.com>`,
  `"Quoted Name" <email@x.com>`, bare `email@x.com`).
