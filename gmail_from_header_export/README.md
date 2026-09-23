# Gmail "From" Header Exporter

A small Google Apps Script tool. It reads messages from a Gmail account
(optionally filtered to one label), pulls out the raw `From:` header from
each one, splits it into name / email, and writes everything into a brand
new Google Sheet.

Output columns: **From (raw header)**, **Name**, **First Name**, **Last Name**,
**Email Address**, **Date**, **Subject**.

First/last name are derived from the Name column by splitting on whitespace:
the last word is the last name and everything before it is the first name,
except common suffixes (Jr., Sr., II, III, IV, V) are folded into a
multi-word last name (e.g. "John Smith Jr." -> first name "John", last name
"Smith Jr."). This is a simple heuristic and won't be right for every name
(e.g. multi-word last names without a suffix, single-word display names,
names in "Last, First" order) -- the raw Name column is always kept
alongside it so nothing is lost.

It runs entirely inside the user's own Google account (no API keys, no
credentials file) -- each org member sets it up once in their own Gmail/Sheets,
using their own login, and it only ever touches their own mailbox.

## Setup (one time, per person)

1. Go to [sheets.google.com](https://sheets.google.com) and create a new
   blank spreadsheet. (This spreadsheet is just the "launcher" -- the actual
   exported data lands in a *separate*, brand-new sheet every time you run
   the tool.)
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
7. A new menu should appear: **From Header Export**. Click it, then
   **Export From Headers...**.
8. The first time you run it, Google will ask you to authorize the script
   (it needs permission to read Gmail and create Sheets). Since this is a
   personal/unpublished script, you'll likely see an "unverified app"
   screen -- this is expected for scripts you write or paste yourself.
   Click **Advanced**, then **Go to (project name) (unsafe)**, then
   **Allow**.

## Using it

- A dialog box opens with a dropdown: **Inbox** (default), **All Mail**
  (every folder except Spam/Trash), or any of your Gmail labels.
- Optionally set a **date range** (From / To). Leave both blank to include
  every date. The To date is inclusive.
- Optionally check "Only keep one row per unique sender" to get one row
  per distinct email address instead of one row per message.
- Click **Create Sheet**. For large mailboxes/labels this can take a
  little while (it processes messages in batches of 100 threads).
- When it finishes, a link to the newly created Google Sheet appears --
  click it to open the results.

## Notes

- The script only reads mail; it never sends, deletes, or modifies
  anything in Gmail.
- Very large inboxes (many thousands of messages) may hit Apps Script's
  execution time limit (6 minutes on personal accounts, 30 minutes on
  Google Workspace). Filtering to a specific label keeps runs fast.
- From-header parsing handles the common forms (`Name <email@x.com>`,
  `"Quoted Name" <email@x.com>`, bare `email@x.com`); a handful of
  unusual headers may parse with an empty name or email -- the raw
  header is always preserved in the first column so nothing is lost.
