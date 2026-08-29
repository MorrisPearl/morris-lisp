# Patriotic Millionaires donor-lookup Flask app.
# SQLite version -- see fec_loader_pa.py for how the database is built
# and kept up to date.

import configparser
import os
import subprocess
import sys
import sqlite3
import time

from flask import Flask, render_template, request, flash, redirect, url_for

from flask_wtf import FlaskForm
from wtforms import StringField, BooleanField, SubmitField, SelectField, TextAreaField
from wtforms.validators import DataRequired

APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Kept in sync with PENDING_MEMBERS_TABLE_SQL in fec_loader_pa.py.
PENDING_MEMBERS_CREATE_SQL = (
    "CREATE TABLE IF NOT EXISTS pending_members ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " first_name TEXT, last_name TEXT, city TEXT, state TEXT,"
    " match_name TEXT NOT NULL, priv INTEGER, pub INTEGER, mem INTEGER, prospect INTEGER,"
    " requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,"
    " processed_at TEXT, rows_matched INTEGER,"
    " status TEXT NOT NULL DEFAULT 'pending')"
)


def get_db_path():
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join(APP_DIR, "config.ini"))
    return cfg.get("sqlite", "db_path", fallback=os.path.join(APP_DIR, "fec_pa.db"))


def get_db_dir():
    return os.path.dirname(os.path.abspath(get_db_path()))


def get_status_path():
    # Kept in sync with pending_status_path() in fec_loader_pa.py.
    return os.path.join(get_db_dir(), "pending_members_status.txt")


def get_lock_path():
    # Kept in sync with pending_lock_path() in fec_loader_pa.py.
    return os.path.join(get_db_dir(), "pending_members.lock")


def get_loader_script_path():
    # fec_loader_pa.py is deployed as a sibling of the database file.
    return os.path.join(get_db_dir(), "fec_loader_pa.py")


def get_connection():
    return sqlite3.connect(get_db_path(), timeout=60)


class candidate_name_form(FlaskForm):
    cname = TextAreaField('Candidate names')
    report_type = SelectField('Report Type',
                              choices=[('mem', 'All Members'),
                                       ('pro','Prospects'),
                                       ('priv','Private Members'),
                                       ('pub', 'Public Members'),
                                       ('all','All Contacts')])
    dccc_flag = BooleanField('DCCC')
    dscc_flag = BooleanField('DSCC')
    dnc_flag = BooleanField('DNC')
    no_group = BooleanField('Show every matching donation (no grouping)')

    submit = SubmitField('Do Report')

class new_member_form(FlaskForm):
    first_name = TextAreaField('First Name')
    last_name = TextAreaField('Last Name')
    city = TextAreaField('City')
    state = TextAreaField('State')
    priv = BooleanField('Private')
    pub = BooleanField('Public')
    mem = BooleanField('Member')
    pro = BooleanField('Prospect')
    submit_add = SubmitField(label="Add Person")
    submit_del = SubmitField(label="Remove Person")
    message = TextAreaField('')


report_type_tab = {'mem'	:	'and mem > 0',
                   'pro'	:	'and prospect > 0',
                   'priv'	:	'and priv > 0',
                   'pub'	:	'and pub > 0',
                   'all'	:	' '}

app = Flask(__name__)
app.config["DEBUG"] = True

app.config['SECRET_KEY'] = "542067798312729234611824003439"

app.jinja_env.filters['zip'] = zip

@app.route('/edit', methods=['GET', 'POST'])
def do_add_form():

    f = new_member_form()

    if f.validate_on_submit():
        if (f.submit_add.data):
            queued = add_member_to_database(f)
            if queued:
                f.message.data = ("Member queued to be added. Picked up automatically "
                                   "overnight, or click \"Process New Members Now\" below "
                                   "to run it right away -- watch the status line for "
                                   "progress.")
            else:
                f.message.data = "First Name and Last Name can't both be blank -- nothing was queued."

        elif (f.submit_del.data):
            j = delete_member_from_database(f)
            f.message.data = "Deleted member with %d donations!" % j

    return render_template("add_member.html", form=f)
    # render the template initially AND after submit.

LOCK_STALE_SECONDS = 1800  # kept in sync with fec_loader_pa.py's own threshold

@app.route('/edit/run_now', methods=['POST'])
def do_run_now():
    """Launches process-pending-members as a detached background
    process and returns immediately -- the actual join is far too slow
    to run inside this request (see add_member_to_database), so this
    route only ever starts it and lets the status file (polled by the
    page's own JS) report progress."""
    lock_path = get_lock_path()
    if os.path.exists(lock_path) and (time.time() - os.path.getmtime(lock_path)) < LOCK_STALE_SECONDS:
        pass  # already running -- just go back and let the status line show it
    else:
        log_path = os.path.join(get_db_dir(), "pending_members_run.log")
        with open(log_path, "a") as logf:
            subprocess.Popen(
                [sys.executable, get_loader_script_path(),
                 "--db-path", get_db_path(), "process-pending-members"],
                stdout=logf, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    return redirect(url_for('do_add_form'))

@app.route('/edit/status')
def do_status():
    try:
        with open(get_status_path()) as f:
            return f.read()
    except FileNotFoundError:
        return "No members have been queued yet."

def normalize_name_field(value):
    """Title-cases a free-typed name/city field: first letter of each
    word upper case, everything else lower case (e.g. 'DE los santos'
    -> 'De Los Santos'), so members show up consistently in reports no
    matter how a staffer happened to type them in."""
    return (value or "").strip().title()

def normalize_state_field(value):
    """Two-letter state codes only, upper case; anything else (blank,
    a full state name, a typo) is stored blank rather than guessed at."""
    v = (value or "").strip().upper()
    return v if len(v) == 2 and v.isalpha() else ""

def delete_member_from_database(f):
    # Match on the same normalized casing new members are stored with,
    # so removal still finds them no matter how it's typed this time.
    last_name = normalize_name_field(f.last_name.data)
    first_name = normalize_name_field(f.first_name.data)

    cnx = get_connection()
    c = cnx.cursor()
    q1 = (" delete from indiv_m "
          " where last_name = ? and first_name = ? ")

    c.execute(q1, (last_name, first_name))
    j = c.rowcount

    # Also cancel any not-yet-processed Add request for the same name,
    # so a member removed right after being queued doesn't get added
    # back the next time process-pending-members runs.
    c.execute(PENDING_MEMBERS_CREATE_SQL)
    c.execute(
        "DELETE FROM pending_members WHERE status = 'pending' "
        "AND last_name = ? AND first_name = ?",
        (last_name, first_name),
    )

    cnx.commit()
    c.close()
    cnx.close()
    return j

def build_match_name(last_name, first_name):
    """Derives the FEC-name LIKE pattern the same way load_members.sql
    does: LASTNAME, FIR% (last name in full, first three letters of the
    first name), both upper-cased to match FEC's all-caps contributor
    names."""
    last = (last_name or "").strip().upper()
    first3 = (first_name or "").strip().upper()[:3]
    return "{}, {}%".format(last, first3)

def add_member_to_database(f):
    """Queues the member for the background job (process-pending-members,
    run nightly and on demand via "Process New Members Now") rather
    than joining against indiv_contributions here: that join is a scan
    of 200M+ rows and can't reliably finish inside one web request --
    PythonAnywhere kills any response after 5 minutes, far longer than
    a user would wait anyway. Returns True if queued, False if
    refused."""
    first_name = normalize_name_field(f.first_name.data)
    last_name = normalize_name_field(f.last_name.data)
    city = normalize_name_field(f.city.data)
    state = normalize_state_field(f.state.data)

    match_name = build_match_name(last_name, first_name)
    if match_name in ("", ", %"):
        # last_name (and/or first_name) was blank -- this pattern would
        # match every row in indiv_contributions, which is never what's
        # wanted, so refuse rather than silently vacuuming in everyone.
        return False

    cnx = get_connection()
    c = cnx.cursor()

    priv = int(bool(f.priv.data))
    pub = int(bool(f.pub.data))
    mem = int(bool(f.mem.data))
    pro = int(bool(f.pro.data))

    c.execute(PENDING_MEMBERS_CREATE_SQL)
    c.execute(
        "INSERT INTO pending_members "
        "(first_name, last_name, city, state, match_name, priv, pub, mem, prospect) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (first_name, last_name, city, state,
         match_name, priv, pub, mem, pro),
    )

    cnx.commit()
    c.close()
    cnx.close()
    return True

@app.route('/list')
def do_list():

    member_list_columns = ('first_name','last_name','city','state','public','private','FEC_Donor_Name',
               'FEC_city','FEC_state','Count','Total_Donations','Date_of_last_donation')

    c = get_member_list()
    return render_template("donor_report.html",
                           title_list=member_list_columns,
                           name_list=c,
                           message=" ")

def get_member_list():

    cnx = get_connection()
    c = cnx.cursor()

    q = ("select first_name, last_name, city, state, "
         "case when pub > 0 then 'Yes' else 'No' end, "
         "case when priv > 0 then 'Yes' else 'No' end, "
         "fec_name, fec_city, fec_state, "
         "count(*), sum(trans_amount), max(trans_date) "
         "from indiv_m d "
         "group by d.first_name, "
         "d.last_name, d.city, d.state, pub, priv, fec_name, fec_city, fec_state "
         "order by last_name, first_name "   )

    c.execute(q)

    cc = list(c)

    return(cc)

@app.route('/member_summary')
def do_member_summary():

    member_summary_columns = ('first_name', 'last_name', 'city', 'state', 'Count', 'Total_Donations')

    c = get_member_summary()
    return render_template("donor_report.html",
                           title_list=member_summary_columns,
                           name_list=c,
                           message=" ")

def get_member_summary():
    """One row per member (grouped only by first_name/last_name/city/
    state, unlike get_member_list() which also groups by fec_name/
    fec_city/fec_state and so can split one member's totals across
    several rows if their matched FEC contributions vary slightly in
    name/city spelling)."""
    cnx = get_connection()
    c = cnx.cursor()

    q = ("select first_name, last_name, city, state, "
         "count(*), sum(trans_amount) "
         "from indiv_m "
         "group by first_name, last_name, city, state "
         "order by last_name, first_name "   )

    c.execute(q)

    cc = list(c)

    return(cc)

@app.route('/', methods=['GET', 'POST'])
def do_form():
    f = candidate_name_form()
    if f.validate_on_submit():
        no_group = bool(f.no_group.data)
        names = query_report_multi_list(f, no_group=no_group)
        if no_group:
            columns = ('first_name','last_name','city','state','committee','Candidate','FEC_Donor_Name',
                       'FEC_city','FEC_state','FEC_Employer','Amount','Date')
        else:
            columns = ('first_name','last_name','city','state','committee','Candidate','FEC_Donor_Name',
                       'FEC_city','FEC_state','FEC_Employer','Count','Total_Donations','Date_of_last_donation')

        return render_template("donor_report.html",
                               title_list=columns,
                               name_list=names,
                               message=" ")

    return render_template("candidate_name.html",form=f)

def query_report_multi_list(f, no_group=False):

    cnx = get_connection()
    c = cnx.cursor()

    q1 = ("create temp table comm_ids ("
          "committee_id text, committee_name text, candidate_name text, "
          "primary key (committee_id))")
    c.execute(q1)

    if (f.dscc_flag.data):
        qa = 'insert into comm_ids values ("C00042366","DSCC","N/A")'
        c.execute(qa)

    if (f.dccc_flag.data):
        qa = 'insert into comm_ids values ("C00000935","DCCC","N/A")'
        c.execute(qa)

    if (f.dnc_flag.data):
        qa = 'insert into comm_ids values ("C00010603","DNC Services","N/A")'
        c.execute(qa)
        qa = 'insert into comm_ids values ("C00307991","DNC PAC","N/A")'
        c.execute(qa)
        qa = 'insert into comm_ids values ("C00493254","DNC Charlotte","N/A")'
        c.execute(qa)

    for cname in f.cname.data.split():
        # "insert or ignore" means to ignore rows which would duplicate index values,
        # i.e. if we find the same committee_id multiple times, it's only inserted once.
        q2 = (" insert or ignore into comm_ids select distinct c.cmte_id, c.cmte_nm, a.cand_name"
              " from committee_master c, candidate_master a"
              " where a.cand_name like ? and a.cand_id = c.cand_id")
        c.execute(q2, (cname.strip() + "%",))

        cnx.commit()

    if no_group:
        q3 = ("select first_name, last_name, city, state, c.committee_name, c.candidate_name, "
             " fec_name, fec_city, fec_state, "
             " fec_employer, trans_amount, trans_date "
             " from comm_ids c, indiv_m d "
             " where c.committee_id = d.committee_id "
              + report_type_tab[f.report_type.data] +
             " order by last_name, first_name, c.candidate_name, trans_date "   )
    else:
        q3 = ("select first_name, last_name, city, state, c.committee_name, c.candidate_name, "
             " fec_name, fec_city, fec_state, "
             " fec_employer, count(*), sum(trans_amount), max(trans_date) "
             " from comm_ids c, indiv_m d "
             " where c.committee_id = d.committee_id "
              + report_type_tab[f.report_type.data] +
             " group by d.first_name, "
             " d.last_name, d.city, d.state, c.committee_name, fec_city, fec_state, fec_employer "
             " order by last_name, first_name, c.candidate_name "   )

    c.execute(q3)

    cc = list(c)

    c.execute("drop table comm_ids")
    cnx.commit()

    return(cc)
