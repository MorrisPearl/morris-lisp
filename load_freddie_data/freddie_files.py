"""
freddie_files.py

Reading Freddie Mac's Single-Family Loan-Level Dataset: where the files of a
quarter are, and what the fields of their rows are.

Each quarter has two pipe-delimited text files:
  orig_<YYYY>Qn.txt  one row per loan: what the loan was when it was made
  perf_<YYYY>Qn.txt  one row per loan per month: its balance, its rate, whether
                     it is delinquent, and, in its last month, how it ended

For each year, the data directory has one of:
  - historical_data_<YYYY>.zip, containing four quarter zips
    historical_data_<YYYY>Qn.zip, each containing the two text files, OR
  - a historical_data_<YYYY>/ directory with those quarter zips in it,
    and/or the two text files already taken out of them.
QuarterSource reads any of these without writing anything to disk: a quarter
zip is read into memory, and the text files are streamed from there.

Only the fields that the loader uses are named here. Freddie's user guide
("Single-Family Loan-Level Dataset General User Guide" and its file layout)
describes them all.
"""

import io
import re
import zipfile

ENCODING = "latin-1"

# --- Fields of the origination file (0-indexed) ---
O_CREDIT_SCORE = 0          # 300-850; 9999 if not known
O_FIRST_PAYMENT_DATE = 1    # YYYYMM
O_FIRST_TIME_HOMEBUYER = 2  # Y, N; 9 if not known
O_OCCUPANCY = 7             # P primary home, I investment property, S second home
O_DTI = 9                   # debt-to-income, percent; 999 if not known
O_ORIG_UPB = 10             # the balance when it was made, rounded to $1,000
O_ORIG_LTV = 11             # percent; 999 if not known
O_ORIG_RATE = 12            # the note rate, percent
O_CHANNEL = 13              # R retail, B broker, C correspondent, T not specified
O_AMORTIZATION_TYPE = 15    # FRM (fixed rate) or ARM
O_STATE = 16                # two letters
O_PROPERTY_TYPE = 17        # SF single family, CO condo, CP co-op, PU planned unit development, MH manufactured housing
O_POSTAL_CODE = 18          # the first three digits of the zip code, then "00"
O_LOAN_ID = 19
O_LOAN_PURPOSE = 20         # P purchase, C cash-out refinance, N no-cash-out refinance, R refinance not specified
O_ORIG_TERM = 21            # months
O_BORROWERS = 22            # how many borrowers; 99 if not known

# --- Fields of the performance file (0-indexed) ---
P_LOAN_ID = 0
P_PERIOD = 1                # YYYYMM, the month of the row
P_CURRENT_UPB = 2           # the balance at the end of the month (rounded to $1,000 for the first six months)
P_DELINQUENCY = 3           # months delinquent: 0, 1, 2, ...; RA if the home was acquired by foreclosure
P_LOAN_AGE = 4              # months since the first payment, less one
P_REMAINING_MONTHS = 5      # months to the legal maturity
P_MODIFICATION_FLAG = 7     # Y in the month of a modification, P in the months after it
P_ZERO_BALANCE_CODE = 8     # how the loan ended, in its last month: 01 prepaid or matured, 02 third-party sale,
                            # 03 short sale or charge-off, 06 repurchase, 09 REO disposition, 15 note sale,
                            # 16 reperforming loan sale, 96 removed for another reason
P_CURRENT_RATE = 10         # the note rate now, percent
P_DEFERRED_UPB = 11         # principal put off by a modification or a deferral, which bears no interest
P_ESTIMATED_LTV = 25        # Freddie's own estimate of the loan-to-value now, percent; 999 if not known


def blank_or(value, missing):
    """The text, or None if it is empty or is the code that means 'not known'."""
    return None if value == "" or value == missing else value


def origination_record(fields):
    """What the loader keeps of a row of the origination file: a dict of the loan's facts."""
    credit_score = blank_or(fields[O_CREDIT_SCORE], "9999")
    dti = blank_or(fields[O_DTI], "999")
    ltv = blank_or(fields[O_ORIG_LTV], "999")
    borrowers = blank_or(fields[O_BORROWERS], "99")
    first_time = blank_or(fields[O_FIRST_TIME_HOMEBUYER], "9")
    postal_code = blank_or(fields[O_POSTAL_CODE], "000")
    return {
        "loan_id": fields[O_LOAN_ID],
        "first_payment": fields[O_FIRST_PAYMENT_DATE],
        "orig_upb": float(fields[O_ORIG_UPB]),
        "orig_rate": float(fields[O_ORIG_RATE]),
        "orig_ltv": int(ltv) if ltv else None,
        "orig_term": int(fields[O_ORIG_TERM]),
        "credit_score": int(credit_score) if credit_score else None,
        "dti": int(dti) if dti else None,
        "borrowers": int(borrowers) if borrowers else None,
        "first_time_buyer": None if first_time is None else (1 if first_time == "Y" else 0),
        "occupancy": fields[O_OCCUPANCY],
        "purpose": fields[O_LOAN_PURPOSE],
        "property_type": fields[O_PROPERTY_TYPE],
        "channel": fields[O_CHANNEL],
        "state": fields[O_STATE],
        "zip3": postal_code[:3] if postal_code else None,
    }


def performance_record(fields):
    """What the loader keeps of a row of the performance file: a dict of the loan's month."""
    delinquency = fields[P_DELINQUENCY]
    return {
        "period": fields[P_PERIOD],
        "upb": float(fields[P_CURRENT_UPB]) if fields[P_CURRENT_UPB] else 0.0,
        "months_delinquent": int(delinquency) if delinquency.isdigit() else None,
        "loan_age": int(fields[P_LOAN_AGE]),
        "remaining_months": int(fields[P_REMAINING_MONTHS]) if fields[P_REMAINING_MONTHS] else 0,
        "modified": fields[P_MODIFICATION_FLAG] in ("Y", "P"),
        "zero_balance_code": fields[P_ZERO_BALANCE_CODE] or None,
        "rate": float(fields[P_CURRENT_RATE]),
        "deferred_upb": float(fields[P_DEFERRED_UPB]) if fields[P_DEFERRED_UPB] else 0.0,
        "freddie_ltv": int(fields[P_ESTIMATED_LTV]) if fields[P_ESTIMATED_LTV] not in ("", "999") else None,
    }


# --- Finding the files ---

QUARTER_ZIP_RE = re.compile(r"^historical_data_(\d{4})Q([1-4])\.zip$")


class QuarterSource:
    """Opens the two files of a quarter, wherever they are: `with QuarterSource(dir, 2023, 1) as (orig, perf):`
    gives two text streams."""

    def __init__(self, data_dir, year, quarter):
        self.data_dir = data_dir
        self.year = year
        self.quarter = quarter
        self._zf = None
        self._files = []

    def _open_text(self, path):
        f = open(path, "r", encoding=ENCODING, newline="")
        self._files.append(f)
        return f

    def _open_zip_member(self, zf, name):
        wrapped = io.TextIOWrapper(zf.open(name), encoding=ENCODING, newline="")
        self._files.append(wrapped)
        return wrapped

    def __enter__(self):
        year, q = self.year, self.quarter
        year_dir = self.data_dir / f"historical_data_{year}"
        orig_name = f"orig_{year}Q{q}.txt"
        perf_name = f"perf_{year}Q{q}.txt"

        # 1. The text files, already taken out of their zip.
        if year_dir.is_dir():
            orig_path = year_dir / orig_name
            perf_path = year_dir / perf_name
            if orig_path.is_file() and perf_path.is_file():
                return self._open_text(orig_path), self._open_text(perf_path)

        # 2. The quarter's zip, on disk.
        quarter_zip_name = f"historical_data_{year}Q{q}.zip"
        candidates = ([year_dir / quarter_zip_name] if year_dir.is_dir() else []) + [self.data_dir / quarter_zip_name]
        for path in candidates:
            if path.is_file():
                self._zf = zipfile.ZipFile(path)
                return self._open_zip_member(self._zf, orig_name), self._open_zip_member(self._zf, perf_name)

        # 3. The quarter's zip, inside the year's zip.
        outer_zip_path = self.data_dir / f"historical_data_{year}.zip"
        if outer_zip_path.is_file():
            with zipfile.ZipFile(outer_zip_path) as outer:
                if quarter_zip_name in outer.namelist():
                    self._zf = zipfile.ZipFile(io.BytesIO(outer.read(quarter_zip_name)))
                    return self._open_zip_member(self._zf, orig_name), self._open_zip_member(self._zf, perf_name)

        raise FileNotFoundError(f"Could not find {orig_name} and {perf_name} under {self.data_dir}")

    def __exit__(self, *exc):
        for f in self._files:
            f.close()
        if self._zf is not None:
            self._zf.close()


def discover_quarters(data_dir, year):
    """The quarters (1-4) that there are files for, in a year."""
    year_dir = data_dir / f"historical_data_{year}"
    found = set()
    if year_dir.is_dir():
        for p in year_dir.iterdir():
            m = re.match(rf"^orig_{year}Q([1-4])\.txt$", p.name)
            if m:
                found.add(int(m.group(1)))
            m = QUARTER_ZIP_RE.match(p.name)
            if m and int(m.group(1)) == year:
                found.add(int(m.group(2)))
    outer_zip_path = data_dir / f"historical_data_{year}.zip"
    if outer_zip_path.is_file():
        with zipfile.ZipFile(outer_zip_path) as outer:
            for name in outer.namelist():
                m = QUARTER_ZIP_RE.match(name)
                if m and int(m.group(1)) == year:
                    found.add(int(m.group(2)))
    return sorted(found)


def discover_years(data_dir):
    """The years that there are files for."""
    years = set()
    for p in data_dir.iterdir():
        m = re.match(r"^historical_data_(\d{4})(\.zip)?$", p.name)
        if m and (m.group(2) or p.is_dir()):
            years.add(int(m.group(1)))
    return sorted(years)
