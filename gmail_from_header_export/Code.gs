/**
 * Gmail "From" Header Exporter
 *
 * Extracts the From header (raw header, plus parsed name and email address)
 * from Gmail messages -- optionally filtered by a Gmail label and a date
 * range -- into a brand-new Google Sheet.
 *
 * Setup: paste this file as Code.gs and Dialog.html into an Apps Script
 * project bound to a Google Sheet. See README.md for step-by-step
 * instructions. Use the "From Header Export" menu that appears on the
 * bound sheet to run it.
 */

// Apps Script kills any run that lasts longer than 6 minutes, and then
// nothing is saved. We stop a little early instead, so that we can still
// write out the messages we have already read.
var TIME_BUDGET_MS = 5 * 60 * 1000;

// How many Gmail threads we ask for at a time. Each batch costs two calls to
// Gmail (one search, one bulk fetch of the messages in those threads).
var THREADS_PER_BATCH = 200;

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

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('From Header Export')
    .addItem('Export From Headers...', 'showDialog')
    .addToUi();
}

function showDialog() {
  var html = HtmlService.createHtmlOutputFromFile('Dialog')
    .setWidth(420)
    .setHeight(430);
  SpreadsheetApp.getUi().showModalDialog(html, 'Export Gmail "From" Headers');
}

function getLabelNames() {
  return GmailApp.getUserLabels()
    .map(function(label) { return label.getName(); })
    .sort();
}

function runExport(options) {
  options = options || {};
  var scope = options.scope || '__INBOX__';  // '__INBOX__', '__ALL__', or a label name
  var dedupe = !!options.dedupe;
  var skipNonPeople = !!options.skipNonPeople;

  // A Gmail search returns every thread that has at least one message in the
  // date range, and a thread can also hold older or newer messages. So we
  // check each message's own date as well.
  var rangeStart = options.startDate ? dateStringToDate(options.startDate, 0) : null;
  var rangeEnd = options.endDate ? dateStringToDate(options.endDate, 1) : null;  // exclusive

  var query = buildQuery(scope, options.startDate, options.endDate);
  var startedAt = Date.now();

  var rows = [['From (raw header)', 'Name', 'First Name', 'Last Name', 'Email Address', 'Date', 'Subject']];
  var seenEmails = {};
  var stoppedEarly = false;
  var resumeDate = null;  // when we stop early: everything newer than this is done

  var searchStart = 0;
  while (true) {
    if (Date.now() - startedAt > TIME_BUDGET_MS) {
      stoppedEarly = true;
      break;
    }

    // Gmail returns the threads newest first.
    var threads = GmailApp.search(query, searchStart, THREADS_PER_BATCH);
    if (threads.length === 0) break;

    // One call to Gmail for the whole batch -- much faster than calling
    // thread.getMessages() separately for every thread.
    var messagesByThread = GmailApp.getMessagesForThreads(threads);

    messagesByThread.forEach(function(messages) {
      messages.forEach(function(message) {
        var date = message.getDate();
        if (rangeStart && date < rangeStart) return;
        if (rangeEnd && date >= rangeEnd) return;

        var rawFrom = message.getFrom();
        var parsed = parseFromHeader(rawFrom);

        if (skipNonPeople && isNonPersonSender(parsed.email)) return;

        if (dedupe) {
          var key = parsed.email.toLowerCase();
          if (seenEmails[key]) return;
          seenEmails[key] = true;
        }

        var splitName = splitNameIntoParts(parsed.name);
        rows.push([
          rawFrom,
          parsed.name,
          splitName.firstName,
          splitName.lastName,
          parsed.email,
          date,
          message.getSubject()
        ]);
      });
    });

    resumeDate = threads[threads.length - 1].getLastMessageDate();
    searchStart += threads.length;
    if (threads.length < THREADS_PER_BATCH) break;
  }

  var ss = createResultSheet(scope, rows);

  return {
    url: ss.getUrl(),
    count: rows.length - 1,
    seconds: Math.round((Date.now() - startedAt) / 1000),
    stoppedEarly: stoppedEarly,
    resumeDate: stoppedEarly ? Utilities.formatDate(resumeDate, Session.getScriptTimeZone(), 'yyyy-MM-dd') : null
  };
}

/** Creates a new spreadsheet holding the rows (the first row is the header). */
function createResultSheet(scope, rows) {
  var scopeForName = scope === '__INBOX__' ? 'Inbox' : scope === '__ALL__' ? 'All Mail' : scope;
  var sheetName = 'Gmail From Headers - ' + scopeForName + ' - ' +
    Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HHmm');

  var ss = SpreadsheetApp.create(sheetName);
  var sheet = ss.getSheets()[0];
  sheet.setName('From Headers');
  sheet.getRange(1, 1, rows.length, rows[0].length).setValues(rows);
  sheet.setFrozenRows(1);

  // Fixed widths: autoResizeColumns has to measure every cell, which is slow
  // on thousands of rows.
  var columnWidths = [250, 160, 110, 110, 220, 150, 400];
  columnWidths.forEach(function(width, i) { sheet.setColumnWidth(i + 1, width); });

  return ss;
}

/**
 * Builds a Gmail search query from a scope ('__INBOX__', '__ALL__', or a
 * label name) and an optional 'YYYY-MM-DD' start/end date. The end date is
 * treated as inclusive (Gmail's before: operator is exclusive, so we push
 * it one day later).
 */
function buildQuery(scope, startDate, endDate) {
  var parts = [];

  if (scope === '__ALL__') {
    parts.push('in:all');
  } else if (scope === '__INBOX__' || !scope) {
    parts.push('in:inbox');
  } else {
    parts.push('label:"' + scope + '"');
  }

  if (startDate) {
    parts.push('after:' + dateStringToGmailFormat(startDate, 0));
  }
  if (endDate) {
    parts.push('before:' + dateStringToGmailFormat(endDate, 1));
  }

  return parts.join(' ');
}

/** Converts a 'YYYY-MM-DD' string to a Date at midnight, shifted by dayOffset days. */
function dateStringToDate(dateStr, dayOffset) {
  var parts = dateStr.split('-').map(Number);
  var d = new Date(parts[0], parts[1] - 1, parts[2]);
  d.setDate(d.getDate() + dayOffset);
  return d;
}

/** Converts a 'YYYY-MM-DD' string to Gmail's 'YYYY/MM/DD' search format, shifted by dayOffset days. */
function dateStringToGmailFormat(dateStr, dayOffset) {
  var d = dateStringToDate(dateStr, dayOffset);
  return Utilities.formatDate(d, Session.getScriptTimeZone(), 'yyyy/MM/dd');
}

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
