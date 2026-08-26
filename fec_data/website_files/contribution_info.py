# Patriotic Millionaires donor-lookup Flask app.
# SQLite version -- see fec_loader_pa.py for how the database is built
# and kept up to date.

import configparser
import os
import sqlite3

from flask import Flask, render_template, request, flash

from flask_wtf import FlaskForm
from wtforms import StringField, BooleanField, SubmitField, SelectField, TextAreaField
from wtforms.validators import DataRequired

APP_DIR = os.path.dirname(os.path.abspath(__file__))


def get_db_path():
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join(APP_DIR, "config.ini"))
    return cfg.get("sqlite", "db_path", fallback=os.path.join(APP_DIR, "fec_pa.db"))


def get_connection():
    return sqlite3.connect(get_db_path())


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
            j = add_member_to_database(f)
            f.message.data = "Added member with %d donations!" % j

        elif (f.submit_del.data):
            j = delete_member_from_database(f)
            f.message.data = "Deleted member with %d donations!" % j

    return render_template("add_member.html", form=f)
    # render the template initially AND after submit.

def delete_member_from_database(f):
    cnx = get_connection()
    c = cnx.cursor()
    q1 = (" delete from indiv_m "
          " where last_name = ? and first_name = ? ")

    c.execute(q1, (f.last_name.data, f.first_name.data))
    j = c.rowcount
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
    match_name = build_match_name(f.last_name.data, f.first_name.data)
    if match_name in ("", ", %"):
        # last_name (and/or first_name) was blank -- this pattern would
        # match every row in indiv_contributions, which is never what's
        # wanted, so refuse rather than silently vacuuming in everyone.
        return 0

    cnx = get_connection()
    c = cnx.cursor()

    priv = int(bool(f.priv.data))
    pub = int(bool(f.pub.data))
    pro = int(bool(f.pro.data))

    q1 = (" insert into indiv_m "
      " (last_name, first_name, city, state, match_name, priv, pub, mem, prospect, "
      "  fec_name, fec_city, fec_state, fec_employer, committee_id, trans_amount, trans_date) "
      " select ?, ?, ?, ?, ?, ?, ?, ?, ?, name, "
      " city, state, employer, "
      " cmte_id, transaction_amt, transaction_dt "
      " from indiv_contributions where name like ? ")

    c.execute(q1, (f.last_name.data, f.first_name.data, f.city.data, f.state.data,
                   match_name, priv, pub, (priv + pub), pro,
                   match_name))

    j = c.rowcount

    cnx.commit()
    c.close()
    cnx.close()
    return j

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
