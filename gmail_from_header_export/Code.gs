/**
 * Gmail Sender List Exporter
 *
 * Builds a Google Sheet with one row per unique sender (first name, last
 * name, email address, and the raw From header) for a whole mailbox.
 *
 * A mailbox can hold hundreds of thousands of messages, far more than one
 * Apps Script run (limit: 6 minutes) can read. So the export is a "job":
 *   - it reads the mailbox one month at a time, newest month first;
 *   - after about 4 minutes it saves where it got to and schedules itself
 *     to run again in a minute (a "time-driven trigger");
 *   - this repeats until the oldest month is done.
 * The job keeps running in the background after the dialog is closed.
 *
 * Setup: paste this file as Code.gs and Dialog.html into an Apps Script
 * project bound to a Google Sheet. See README.md for step-by-step
 * instructions. Use the "Sender Export" menu that appears on the bound
 * sheet to run it.
 */

// Each run stops reading after this long, leaving time to write the sheet
// before Apps Script's 6 minute limit cancels the run.
var CHUNK_BUDGET_MS = 4 * 60 * 1000;

// How many Gmail threads we ask for at a time. Each batch costs two calls to
// Gmail (one search, one bulk fetch of the messages in those threads).
var THREADS_PER_BATCH = 100;

// Wait this long between runs, and this long before trying again after an
// error. Errors are usually Google's daily quota; the quota resets overnight,
// so retrying every hour for two days (48 times) will get past it.
var CONTINUE_DELAY_MS = 60 * 1000;
var RETRY_DELAY_MS = 60 * 60 * 1000;
var MAX_CONSECUTIVE_ERRORS = 48;

// Gmail opened in April 2004, so no mail is older than this.
var GMAIL_LAUNCH_DATE = new Date(2004, 3, 1);

var SHEET_HEADER = ['First Name', 'Last Name', 'Email Address', 'From (raw header)'];
var EMAIL_COLUMN = 3;  // position of 'Email Address' in SHEET_HEADER
var JOB_PROPERTY = 'exportJob';

// Senders whose address (the part before the @) is exactly one of these are
// organizations, not people. Add more here if you see others in your results.
var NON_PERSON_NAMES = [
  'info', 'hello', 'hi', 'contact', 'support', 'help', 'admin', 'team',
  'sales', 'billing', 'orders', 'service', 'updates', 'news', 'newsletter',
  'notifications', 'notification', 'alerts', 'security', 'accounts',
  'marketing', 'press', 'events', 'office', 'webmaster', 'postmaster'
];

// Senders whose address contains any of these anywhere are also skipped.
var NON_PERSON_FRAGMENTS = [
  'noreply', 'no-reply', 'no_reply', 'donotreply', 'do-not-reply',
  'mailer-daemon'
];

// ---------------------------------------------------------------------------
// Menu and dialog
// ---------------------------------------------------------------------------

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Sender Export')
    .addItem('Start export...', 'showDialog')
    .addItem('Show progress', 'showProgress')
    .addItem('Stop export', 'stopExport')
    .addToUi();
}

function showDialog() {
  var html = HtmlService.createHtmlOutputFromFile('Dialog')
    .setWidth(440)
    .setHeight(440);
  SpreadsheetApp.getUi().showModalDialog(html, 'Export Gmail senders');
}

function getLabelNames() {
  return GmailApp.getUserLabels()
    .map(function(label) { return label.getName(); })
    .sort();
}

function showProgress() {
  var ui = SpreadsheetApp.getUi();
  var job = loadJob();
  ui.alert('Export progress', job ? describeJob(job) : 'No export has been started.', ui.ButtonSet.OK);
}

function stopExport() {
  var ui = SpreadsheetApp.getUi();
  deleteContinuationTriggers();
  PropertiesService.getUserProperties().deleteProperty(JOB_PROPERTY);
  ui.alert('Export stopped', 'Whatever was already written stays in the results sheet.', ui.ButtonSet.OK);
}

// ---------------------------------------------------------------------------
// Starting and continuing the export job
// ---------------------------------------------------------------------------

/**
 * Called by the dialog. Creates the results sheet and the job, runs the
 * first chunk right away (so you see results and any errors immediately),
 * and returns { url, message } for the dialog to show.
 */
function startExport(options) {
  options = options || {};

  var existingJob = loadJob();
  if (existingJob && !existingJob.done) {
    throw new Error('An export is already running. Use "Stop export" in the menu first, or wait for it to finish.');
  }

  var scope = options.scope || '__ALL__';  // '__INBOX__', '__ALL__', or a label name
  var rangeStart = options.startDate ? dateStringToDate(options.startDate, 0) : GMAIL_LAUNCH_DATE;
  var rangeEnd = options.endDate ? dateStringToDate(options.endDate, 1) : new Date(Date.now() + 24 * 60 * 60 * 1000);
  if (rangeStart >= rangeEnd) {
    throw new Error('The "From" date must be before the "To" date.');
  }

  var ss = createResultSheet(scope);
  saveJob({
    spreadsheetId: ss.getId(),
    spreadsheetUrl: ss.getUrl(),
    scope: scope,
    skipNonPeople: !!options.skipNonPeople,
    rangeStartMs: rangeStart.getTime(),
    windowEndMs: rangeEnd.getTime(),  // we work backward from here toward rangeStartMs
    threadOffset: 0,                  // how far into the current month's search results we are
    messagesRead: 0,
    uniqueSenders: 0,
    workSeconds: 0,
    consecutiveErrors: 0,
    lastError: '',
    done: false
  });

  continueExport();

  var job = loadJob();
  return { url: job.spreadsheetUrl, message: describeJob(job) };
}

/**
 * Runs one chunk of the job, then schedules the next one (or a retry if
 * this one failed). This is also the function the time-driven trigger calls.
 */
function continueExport() {
  try {
    runChunk();
  } catch (error) {
    var failedJob = loadJob();
    if (!failedJob) return;
    failedJob.lastError = String(error);
    failedJob.consecutiveErrors += 1;
    saveJob(failedJob);
    if (failedJob.consecutiveErrors <= MAX_CONSECUTIVE_ERRORS) {
      scheduleContinuation(RETRY_DELAY_MS);
    }
    return;
  }

  var job = loadJob();
  if (job && !job.done) {
    scheduleContinuation(CONTINUE_DELAY_MS);
  }
}

/**
 * Reads Gmail until the time budget is used up or the oldest month is done,
 * adds the new senders to the results sheet, and saves the job's position.
 */
function runChunk() {
  var job = loadJob();
  if (!job || job.done) return;

  var startedAt = Date.now();
  var sheet = SpreadsheetApp.openById(job.spreadsheetId).getSheets()[0];
  var seenEmails = loadSeenEmails(sheet);
  var newRows = [];

  while (job.windowEndMs > job.rangeStartMs && Date.now() - startedAt < CHUNK_BUDGET_MS) {
    // The current "month" is the span from windowStart up to windowEnd.
    var windowEnd = new Date(job.windowEndMs);
    var windowStart = new Date(Math.max(job.rangeStartMs, monthBefore(windowEnd).getTime()));

    var query = buildQuery(job.scope, windowStart, windowEnd);
    var threads = GmailApp.search(query, job.threadOffset, THREADS_PER_BATCH);

    if (threads.length > 0) {
      // One call to Gmail for the whole batch -- much faster than calling
      // thread.getMessages() separately for every thread.
      GmailApp.getMessagesForThreads(threads).forEach(function(messages) {
        messages.forEach(function(message) {
          // A thread can hold messages from other months; each message is
          // counted only in the month it was sent.
          var date = message.getDate();
          if (date < windowStart || date >= windowEnd) return;
          job.messagesRead += 1;

          var rawFrom = message.getFrom();
          var parsed = parseFromHeader(rawFrom);
          if (!parsed.email) return;
          if (job.skipNonPeople && isNonPersonSender(parsed.email)) return;

          var key = parsed.email.toLowerCase();
          if (seenEmails[key]) return;
          seenEmails[key] = true;

          var name = splitNameIntoParts(parsed.name);
          newRows.push([name.firstName, name.lastName, parsed.email, rawFrom]);
        });
      });
    }

    job.threadOffset += threads.length;
    if (threads.length < THREADS_PER_BATCH) {
      // That was the last batch for this month; move on to the one before it.
      job.windowEndMs = windowStart.getTime();
      job.threadOffset = 0;
    }
  }

  appendRows(sheet, newRows);

  job.uniqueSenders += newRows.length;
  job.workSeconds += Math.round((Date.now() - startedAt) / 1000);
  job.done = job.windowEndMs <= job.rangeStartMs;
  job.consecutiveErrors = 0;
  job.lastError = '';

  // "Stop export" may have been clicked while this chunk was running.
  if (!loadJob()) return;
  saveJob(job);
}

function scheduleContinuation(delayMs) {
  deleteContinuationTriggers();
  ScriptApp.newTrigger('continueExport').timeBased().after(delayMs).create();
}

function deleteContinuationTriggers() {
  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    if (trigger.getHandlerFunction() === 'continueExport') {
      ScriptApp.deleteTrigger(trigger);
    }
  });
}

// ---------------------------------------------------------------------------
// Job state (kept between runs in the user's script properties)
// ---------------------------------------------------------------------------

function loadJob() {
  var text = PropertiesService.getUserProperties().getProperty(JOB_PROPERTY);
  return text ? JSON.parse(text) : null;
}

function saveJob(job) {
  PropertiesService.getUserProperties().setProperty(JOB_PROPERTY, JSON.stringify(job));
}

/** A plain-English description of the job, for the dialog and the progress menu. */
function describeJob(job) {
  var counts = job.uniqueSenders + ' unique senders found in ' + job.messagesRead +
    ' messages (' + Math.round(job.workSeconds / 60) + ' minutes of work so far).';

  var text;
  if (job.done) {
    text = 'Finished. ' + counts;
  } else {
    text = 'Still running. It continues by itself in the background, so you can close this window. ' +
      'It reads from newest mail to oldest, and is now at about ' +
      Utilities.formatDate(new Date(job.windowEndMs), Session.getScriptTimeZone(), 'yyyy-MM-dd') + '. ' + counts;
  }

  if (job.lastError) {
    text += ' The last run failed with: ' + job.lastError;
    text += job.consecutiveErrors > MAX_CONSECUTIVE_ERRORS
      ? ' It has given up.'
      : ' It will try again in about an hour.';
  }
  return text;
}

// ---------------------------------------------------------------------------
// The results sheet
// ---------------------------------------------------------------------------

function createResultSheet(scope) {
  var scopeForName = scope === '__INBOX__' ? 'Inbox' : scope === '__ALL__' ? 'All Mail' : scope;
  var sheetName = 'Gmail Senders - ' + scopeForName + ' - ' +
    Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HHmm');

  var ss = SpreadsheetApp.create(sheetName);
  var sheet = ss.getSheets()[0];
  sheet.setName('Senders');
  sheet.getRange(1, 1, 1, SHEET_HEADER.length).setValues([SHEET_HEADER]);
  sheet.setFrozenRows(1);

  var columnWidths = [150, 150, 250, 350];
  columnWidths.forEach(function(width, i) { sheet.setColumnWidth(i + 1, width); });

  return ss;
}

/** Returns an object with a key for every email address already in the sheet (lower case). */
function loadSeenEmails(sheet) {
  var seen = {};
  var lastRow = sheet.getLastRow();
  if (lastRow < 2) return seen;

  sheet.getRange(2, EMAIL_COLUMN, lastRow - 1, 1).getValues().forEach(function(row) {
    seen[String(row[0]).toLowerCase()] = true;
  });
  return seen;
}

/** Adds rows below the existing ones, making the sheet taller first if needed. */
function appendRows(sheet, rows) {
  if (rows.length === 0) return;

  var firstRow = sheet.getLastRow() + 1;
  var lastRow = firstRow + rows.length - 1;
  if (lastRow > sheet.getMaxRows()) {
    sheet.insertRowsAfter(sheet.getMaxRows(), lastRow - sheet.getMaxRows());
  }
  sheet.getRange(firstRow, 1, rows.length, rows[0].length).setValues(rows);
}

// ---------------------------------------------------------------------------
// Searching and dates
// ---------------------------------------------------------------------------

/**
 * Builds a Gmail search query for one month. Gmail reads the after:/before:
 * dates in its own time zone, so we widen the search by a day on each side;
 * the exact date check happens on each message in runChunk.
 */
function buildQuery(scope, windowStart, windowEnd) {
  var parts = [];

  if (scope === '__ALL__') {
    parts.push('in:all');
  } else if (scope === '__INBOX__' || !scope) {
    parts.push('in:inbox');
  } else {
    parts.push('label:"' + scope + '"');
  }

  parts.push('after:' + gmailDate(windowStart, -1));
  parts.push('before:' + gmailDate(windowEnd, 1));

  return parts.join(' ');
}

/** Formats a date as Gmail's 'YYYY/MM/DD' search format, shifted by dayOffset days. */
function gmailDate(date, dayOffset) {
  var d = new Date(date.getTime());
  d.setDate(d.getDate() + dayOffset);
  return Utilities.formatDate(d, Session.getScriptTimeZone(), 'yyyy/MM/dd');
}

/** Returns the date one month earlier. */
function monthBefore(date) {
  var d = new Date(date.getTime());
  d.setMonth(d.getMonth() - 1);
  return d;
}

/** Converts a 'YYYY-MM-DD' string to a Date at midnight, shifted by dayOffset days. */
function dateStringToDate(dateStr, dayOffset) {
  var parts = dateStr.split('-').map(Number);
  var d = new Date(parts[0], parts[1] - 1, parts[2]);
  d.setDate(d.getDate() + dayOffset);
  return d;
}

// ---------------------------------------------------------------------------
// Understanding the From header
// ---------------------------------------------------------------------------

/**
 * Returns true if the email address looks like it belongs to an organization
 * or an automated sender (info@, no-reply@, hello@, ...) rather than a person.
 * Any "+tag" in the address is ignored, so support+123@ counts as support@.
 */
function isNonPersonSender(email) {
  var localPart = email.split('@')[0].split('+')[0].toLowerCase();

  if (NON_PERSON_NAMES.indexOf(localPart) !== -1) return true;

  return NON_PERSON_FRAGMENTS.some(function(fragment) {
    return localPart.indexOf(fragment) !== -1;
  });
}

/**
 * Parses a raw RFC 2822 "From" header into { name, email }.
 * Handles "Name <email@domain.com>", "\"Name\" <email@domain.com>",
 * and bare "email@domain.com" forms.
 */
function parseFromHeader(rawFrom) {
  if (!rawFrom) return { name: '', email: '' };

  var match = rawFrom.match(/^(.*)<([^>]+)>\s*$/);
  if (match) {
    var name = match[1].trim().replace(/^"(.*)"$/, '$1');
    var email = match[2].trim();
    return { name: name, email: email };
  }

  var trimmed = rawFrom.trim();
  if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed)) {
    return { name: '', email: trimmed };
  }

  return { name: trimmed, email: '' };
}

// Trailing-name suffixes (case-insensitive, trailing period optional) that get folded
// into the last name instead of being treated as a standalone last-name token.
var NAME_SUFFIXES = ['jr', 'sr', 'ii', 'iii', 'iv', 'v'];

/**
 * Splits a display name into { firstName, lastName }. The last whitespace-
 * separated token is treated as the last name, and everything before it as
 * the first name -- unless the last token is a common suffix (Jr., Sr., II,
 * III, IV, V), in which case the suffix and the token before it together
 * form a multi-word last name.
 */
function splitNameIntoParts(name) {
  if (!name) return { firstName: '', lastName: '' };

  var parts = name.split(/\s+/).filter(Boolean);
  if (parts.length === 0) return { firstName: '', lastName: '' };
  if (parts.length === 1) return { firstName: '', lastName: parts[0] };

  var lastNameStartIdx = parts.length - 1;
  var lastToken = parts[parts.length - 1].toLowerCase().replace(/\.$/, '');

  if (NAME_SUFFIXES.indexOf(lastToken) !== -1) {
    lastNameStartIdx = Math.max(0, parts.length - 2);
  }

  return {
    firstName: parts.slice(0, lastNameStartIdx).join(' '),
    lastName: parts.slice(lastNameStartIdx).join(' ')
  };
}
