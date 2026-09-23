/**
 * Gmail "From" Header Exporter
 *
 * Extracts the From header (raw header, plus parsed name and email address)
 * from Gmail messages -- optionally filtered by a Gmail label -- into a
 * brand-new Google Sheet.
 *
 * Setup: paste this file as Code.gs and Dialog.html into an Apps Script
 * project bound to a Google Sheet. See README.md for step-by-step
 * instructions. Use the "From Header Export" menu that appears on the
 * bound sheet to run it.
 */

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('From Header Export')
    .addItem('Export From Headers...', 'showDialog')
    .addToUi();
}

function showDialog() {
  var html = HtmlService.createHtmlOutputFromFile('Dialog')
    .setWidth(420)
    .setHeight(340);
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
  var startDate = options.startDate;  // 'YYYY-MM-DD' or falsy
  var endDate = options.endDate;      // 'YYYY-MM-DD' or falsy

  var query = buildQuery(scope, startDate, endDate);

  var rows = [['From (raw header)', 'Name', 'First Name', 'Last Name', 'Email Address', 'Date', 'Subject']];
  var seenEmails = {};

  var batchSize = 100;
  var start = 0;
  var threads;

  do {
    threads = GmailApp.search(query, start, batchSize);
    threads.forEach(function(thread) {
      thread.getMessages().forEach(function(message) {
        var rawFrom = message.getFrom();
        var parsed = parseFromHeader(rawFrom);
        var splitName = splitNameIntoParts(parsed.name);

        if (dedupe) {
          var key = parsed.email.toLowerCase();
          if (seenEmails[key]) return;
          seenEmails[key] = true;
        }

        rows.push([
          rawFrom,
          parsed.name,
          splitName.firstName,
          splitName.lastName,
          parsed.email,
          message.getDate(),
          message.getSubject()
        ]);
      });
    });
    start += batchSize;
  } while (threads.length === batchSize);

  var scopeForName = scope === '__INBOX__' ? 'Inbox' : scope === '__ALL__' ? 'All Mail' : scope;
  var sheetName = 'Gmail From Headers - ' + scopeForName + ' - ' +
    Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HHmm');

  var ss = SpreadsheetApp.create(sheetName);
  var sheet = ss.getSheets()[0];
  sheet.setName('From Headers');
  sheet.getRange(1, 1, rows.length, rows[0].length).setValues(rows);
  sheet.setFrozenRows(1);
  sheet.autoResizeColumns(1, rows[0].length);

  return {
    url: ss.getUrl(),
    count: rows.length - 1
  };
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

/** Converts a 'YYYY-MM-DD' string to Gmail's 'YYYY/MM/DD' search format, optionally shifted by dayOffset days. */
function dateStringToGmailFormat(dateStr, dayOffset) {
  var parts = dateStr.split('-').map(Number);
  var d = new Date(parts[0], parts[1] - 1, parts[2]);
  d.setDate(d.getDate() + dayOffset);
  return Utilities.formatDate(d, Session.getScriptTimeZone(), 'yyyy/MM/dd');
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
