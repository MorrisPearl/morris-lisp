#!/usr/bin/env python3
"""
Make a list of everyone who has sent you email, from a Gmail Takeout export.

Google Takeout gives you your mail as one or more ".mbox" files, packed inside
".zip" files. This script reads the From header of every message in them and
writes a CSV file with one row per unique sender: first name, last name, email
address, and the raw From header (so you can check that the name and address
were split correctly). You can then import the CSV into Google Sheets.

You can give it the .zip files straight from Takeout (no need to unzip them),
or .mbox files:

    python3 mbox_senders.py takeout-20260101T000000Z-001.zip
    python3 mbox_senders.py "All mail Including Spam and Trash.mbox"
    python3 mbox_senders.py first.zip second.zip -o my_senders.csv

Only the header lines of each message are looked at; message bodies and
attachments are skipped over, so even a mailbox of many gigabytes takes only
a few minutes. Nothing is sent anywhere -- everything happens on this computer.
"""

import argparse
import csv
import email
import email.policy
import email.utils
import io
import os
import re
import zipfile

# Senders whose address (the part before the @) is exactly one of these are
# organizations, not people. This is the same list as in Code.gs.
NON_PERSON_NAMES = {
    'info', 'hello', 'hi', 'contact', 'support', 'help', 'admin', 'team',
    'sales', 'billing', 'orders', 'service', 'updates', 'news', 'newsletter',
    'notifications', 'notification', 'alerts', 'security', 'accounts',
    'marketing', 'press', 'events', 'office', 'webmaster', 'postmaster',
}

# Senders whose address contains any of these anywhere are also skipped.
NON_PERSON_FRAGMENTS = (
    'noreply', 'no-reply', 'no_reply', 'donotreply', 'do-not-reply',
    'mailer-daemon',
)

# Trailing name suffixes that are kept with the last name ("Smith Jr.").
NAME_SUFFIXES = {'jr', 'sr', 'ii', 'iii', 'iv', 'v'}

# The only header fields we need from each message. Takeout adds the
# X-Gmail-Labels header, which lists the labels the message had in Gmail.
WANTED_HEADERS = {b'from', b'date', b'x-gmail-labels'}

# Messages with one of these labels are left out unless --include-spam-trash.
SPAM_TRASH_LABELS = {'spam', 'trash'}

PROGRESS_EVERY = 50000  # print a progress line after this many messages
BUFFER_SIZE = 4 * 1024 * 1024  # read the file in 4 MB pieces


def open_mailboxes(path):
    """
    Yield (name, size, stream) for each mailbox in path, which is either a
    .mbox file or a Google Takeout .zip file containing .mbox files. Reading
    straight from the .zip means you don't have to unzip a huge download first.
    The stream is only open until you ask for the next mailbox.
    """
    if path.lower().endswith('.zip'):
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                if member.filename.lower().endswith('.mbox'):
                    # BufferedReader makes reading line by line much faster.
                    with io.BufferedReader(archive.open(member), BUFFER_SIZE) as stream:
                        yield member.filename, member.file_size, stream
    else:
        with open(path, 'rb', buffering=BUFFER_SIZE) as stream:
            yield path, os.path.getsize(path), stream


def read_message_headers(mbox_stream):
    """
    Go through an open mbox file and yield (headers, position) for each message.

    headers is a dict holding the raw bytes of the wanted header fields,
    keyed by lower-case field name. position is how far into the file we are,
    for the progress display.

    In an mbox file every message starts with a line beginning "From " (right
    after a blank line), then comes the header, a blank line, and the body.
    We read each line once, keep only the wanted header lines, and ignore the
    body.
    """
    headers = None        # while reading a message's header: its wanted fields; otherwise None
    current_field = None  # the wanted field we are in the middle of, if any
    previous_line_blank = True

    for line in mbox_stream:
        if headers is not None:
            if line.strip() == b'':
                yield headers, mbox_stream.tell()  # a blank line ends the header
                headers = None
            elif line[:1] in (b' ', b'\t'):
                # A long header field is "folded" onto the next line.
                if current_field is not None:
                    headers[current_field] += line
            else:
                field_name = line.split(b':', 1)[0].strip().lower()
                current_field = field_name if field_name in WANTED_HEADERS else None
                if current_field is not None:
                    headers[current_field] = line
        elif previous_line_blank and line.startswith(b'From '):
            headers = {}
            current_field = None

        previous_line_blank = (line.strip() == b'')


def decode_headers(headers):
    """Turn the raw header bytes into (from_header, timestamp, labels) using Python's email parser."""
    block = b''.join(headers.values())
    message = email.message_from_bytes(block, policy=email.policy.default)
    from_header = str(message['From'] or '')
    labels = str(message['X-Gmail-Labels'] or '')
    return from_header, date_to_timestamp(str(message['Date'] or '')), labels


def date_to_timestamp(date_text):
    """Seconds since 1970 for a Date header; 0 (the oldest possible) if it can't be read."""
    try:
        return email.utils.parsedate_to_datetime(date_text).timestamp()
    except (TypeError, ValueError, IndexError, OverflowError):
        return 0.0


def has_spam_or_trash_label(labels_header):
    labels = [label.strip().strip('"').lower() for label in labels_header.split(',')]
    return any(label in SPAM_TRASH_LABELS for label in labels)


def parse_from_header(raw_from):
    """
    Split a From header into (name, email_address).
    Handles 'Name <a@b.com>', '"Name" <a@b.com>' and a bare 'a@b.com'.
    """
    if not raw_from:
        return '', ''

    match = re.match(r'^(.*)<([^>]+)>\s*$', raw_from)
    if match:
        name = match.group(1).strip()
        if len(name) >= 2 and name.startswith('"') and name.endswith('"'):
            name = name[1:-1]
        return name, match.group(2).strip()

    trimmed = raw_from.strip()
    if re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', trimmed):
        return '', trimmed

    return trimmed, ''


def split_name(name):
    """
    Split a display name into (first_name, last_name). The last word is the
    last name and everything before it is the first name -- unless the last
    word is a suffix like Jr. or III, in which case the word before it joins
    the suffix to make the last name.
    """
    parts = name.split()
    if len(parts) == 0:
        return '', ''
    if len(parts) == 1:
        return '', parts[0]

    last_name_start = len(parts) - 1
    if parts[-1].lower().rstrip('.') in NAME_SUFFIXES:
        last_name_start = len(parts) - 2

    return ' '.join(parts[:last_name_start]), ' '.join(parts[last_name_start:])


def is_non_person(email_address):
    """True for addresses like info@, no-reply@, hello@ that are not a person."""
    local_part = email_address.split('@')[0].split('+')[0].lower()
    if local_part in NON_PERSON_NAMES:
        return True
    return any(fragment in local_part for fragment in NON_PERSON_FRAGMENTS)


def add_message(headers, args, senders, skipped):
    """
    Record the sender of one message in senders -- unless it is left out, in
    which case skipped counts the reason. If we already have this sender, the
    row from the newest message is kept.
    """
    try:
        raw_from, timestamp, labels = decode_headers(headers)
    except Exception:
        skipped['unreadable'] += 1
        return

    if not args.include_spam_trash and has_spam_or_trash_label(labels):
        skipped['spam or trash'] += 1
        return

    name, address = parse_from_header(raw_from)
    if not address:
        skipped['no email address'] += 1
        return
    if not args.include_non_people and is_non_person(address):
        skipped['not a person'] += 1
        return

    key = address.lower()
    if key not in senders or timestamp > senders[key][0]:
        first_name, last_name = split_name(name)
        senders[key] = (timestamp, first_name, last_name, address, raw_from)


def main():
    parser = argparse.ArgumentParser(description='List the unique senders in Gmail Takeout .mbox or .zip files.')
    parser.add_argument('mbox_files', nargs='+', help='one or more .mbox files, or the Takeout .zip files that contain them')
    parser.add_argument('-o', '--output', help='CSV file to write (default: senders.csv next to the first file given)')
    parser.add_argument('--include-non-people', action='store_true',
                        help='keep senders like info@ and no-reply@ (they are skipped by default)')
    parser.add_argument('--include-spam-trash', action='store_true',
                        help='keep messages that were in Spam or Trash (they are skipped by default)')
    args = parser.parse_args()

    output_path = args.output or os.path.join(os.path.dirname(os.path.abspath(args.mbox_files[0])), 'senders.csv')

    # lower-case email address -> (timestamp, first, last, email, raw header) for the newest message so far
    senders = {}
    messages_read = 0
    skipped = {'spam or trash': 0, 'no email address': 0, 'not a person': 0, 'unreadable': 0}

    mailboxes_found = 0

    for path in args.mbox_files:
        for mailbox_name, mailbox_size, mbox_stream in open_mailboxes(path):
            mailboxes_found += 1
            print('Reading', mailbox_name, flush=True)

            for headers, position in read_message_headers(mbox_stream):
                messages_read += 1
                if messages_read % PROGRESS_EVERY == 0:
                    print('  %s messages read (%d%% of this file), %s unique senders so far' %
                          (format(messages_read, ','), 100 * position // max(mailbox_size, 1), format(len(senders), ',')),
                          flush=True)

                add_message(headers, args, senders, skipped)

    if mailboxes_found == 0:
        print('No .mbox files were found in what you gave me. Did you pick the right file?')

    # Newest senders first, like the Google Sheets version.
    rows = sorted(senders.values(), key=lambda sender: sender[0], reverse=True)

    # errors='replace': a few messages contain bytes that are not valid text.
    with open(output_path, 'w', newline='', encoding='utf-8', errors='replace') as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(['First Name', 'Last Name', 'Email Address', 'From (raw header)'])
        for _timestamp, first_name, last_name, address, raw_from in rows:
            writer.writerow([first_name, last_name, address, raw_from])

    print()
    print('Read %s messages.' % format(messages_read, ','))
    for reason, count in skipped.items():
        if count:
            print('  Left out %s messages: %s' % (format(count, ','), reason))
    print('Wrote %s unique senders to %s' % (format(len(rows), ','), output_path))


if __name__ == '__main__':
    main()
