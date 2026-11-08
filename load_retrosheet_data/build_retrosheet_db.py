"""Make the SQLite database of turns at bat that lib/baseball.lsp reads.

    python3 build_retrosheet_db.py                       # downloads 2015 to the latest season Retrosheet has, then builds
    python3 build_retrosheet_db.py --first 2015 --last 2025 --directory /Users/morris/retrosheet_data

It puts the files Retrosheet gives (one zip a season, and the list of players) in <directory>/zips, and makes <directory>/retrosheet.db with the tables

  turns    a row for each turn at bat (see turns.py): who batted, who pitched, the state it began in, and where it ended
  games    a row for each game: the teams and the final score
  players  a row for each player: id, name, how he bats and throws

The information used here was obtained free of charge from and is copyrighted by Retrosheet.  Interested parties may contact Retrosheet at 20 Sunset Rd., Newark, DE 19711.
"""

import argparse
import csv
import io
import itertools
import os
import sqlite3
import urllib.request
import zipfile

from turns import TURN_COLUMNS, turns_of_game

URL = "https://www.retrosheet.org/downloads/"
GAME_COLUMNS = ["gid", "season", "date", "gametype", "visiting_team", "home_team", "visiting_runs", "home_runs", "innings"]
PLAYER_COLUMNS = ["id", "last", "first", "bats", "throws", "first_season", "last_season"]


def download(url, path):
    """Download a file, unless it is already there. False if Retrosheet does not have it."""
    if os.path.exists(path):
        return True
    try:
        with urllib.request.urlopen(url) as response, open(path, "wb") as out:
            out.write(response.read())
        return True
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return False
        raise


def download_seasons(first, last, zips):
    """Download the play-by-play of each season from first to last that Retrosheet has; the seasons it has."""
    seasons = []
    for season in range(first, last + 1):
        if download(URL + "plays/%dplays.zip" % season, os.path.join(zips, "%dplays.zip" % season)):
            seasons.append(season)
    return seasons


def rows_of_zip(path):
    """The rows of the csv file in a zip, each a dictionary of its columns."""
    with zipfile.ZipFile(path) as archive:
        name = archive.namelist()[0]
        with archive.open(name) as raw:
            yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))


def games_of_rows(rows):
    """The rows of the games, one list a game (the rows of a game are together in the file)."""
    for _, game_rows in itertools.groupby(rows, key=lambda row: row["gid"]):
        yield list(game_rows)


def add_season(conn, path):
    """Put the turns and the games of a season's zip in the database. How many turns."""
    count = 0
    for game_rows in games_of_rows(rows_of_zip(path)):
        turns, game = turns_of_game(game_rows)
        conn.executemany("INSERT INTO turns VALUES (%s)" % ",".join("?" * len(TURN_COLUMNS)), turns)
        conn.execute("INSERT INTO games VALUES (%s)" % ",".join("?" * len(GAME_COLUMNS)), game)
        count += len(turns)
    return count


def add_players(conn, path):
    """Put the players in the database: a row for each player, with the first and last season he played in."""
    players = {}
    with zipfile.ZipFile(path) as archive:
        with archive.open("allplayers.csv") as raw:
            for row in csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", newline="")):
                season = int(row["season"])
                old = players.get(row["id"])
                players[row["id"]] = (row["id"], row["last"], row["first"], row["bat"], row["throw"],
                                      min(season, old[5]) if old else season, max(season, old[6]) if old else season)
    conn.executemany("INSERT INTO players VALUES (%s)" % ",".join("?" * len(PLAYER_COLUMNS)), players.values())


def make_tables(conn):
    for table, columns in (("turns", TURN_COLUMNS), ("games", GAME_COLUMNS), ("players", PLAYER_COLUMNS)):
        conn.execute("DROP TABLE IF EXISTS " + table)
        conn.execute("CREATE TABLE %s (%s)" % (table, ", ".join(columns)))


def make_indexes(conn):
    """Indexes for the questions the Lisp library asks: a player's turns, a team's, a season's."""
    conn.execute("CREATE INDEX turns_batter ON turns (batter, season)")
    conn.execute("CREATE INDEX turns_pitcher ON turns (pitcher, season)")
    conn.execute("CREATE INDEX turns_pitching_team ON turns (pitching_team, season)")
    conn.execute("CREATE INDEX turns_season ON turns (season)")
    conn.execute("CREATE INDEX games_season ON games (season)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--first", type=int, default=2015, help="the first season")
    parser.add_argument("--last", type=int, default=2030, help="the last season to try for (the seasons Retrosheet has are used)")
    parser.add_argument("--directory", default="/Users/morris/retrosheet_data", help="where the downloads and the database go")
    args = parser.parse_args()

    zips = os.path.join(args.directory, "zips")
    os.makedirs(zips, exist_ok=True)
    seasons = download_seasons(args.first, args.last, zips)
    if not download(URL + "allplayers.zip", os.path.join(zips, "allplayers.zip")):
        raise SystemExit("Retrosheet does not have allplayers.zip")
    print("seasons", seasons[0], "to", seasons[-1])

    database = os.path.join(args.directory, "retrosheet.db")
    if os.path.exists(database):
        os.remove(database)
    conn = sqlite3.connect(database)
    make_tables(conn)
    for season in seasons:
        count = add_season(conn, os.path.join(zips, "%dplays.zip" % season))
        conn.commit()
        print(season, count, "turns")
    add_players(conn, os.path.join(zips, "allplayers.zip"))
    make_indexes(conn)
    conn.commit()
    conn.close()
    print("wrote", database)


if __name__ == "__main__":
    main()
