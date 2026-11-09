# Retrosheet plays, for a model of baseball

These scripts make a SQLite database of the plays of Major League Baseball since 2015, one row for each batter's turn at bat. `lisp_interp/lib/baseball.lsp` reads it
and builds transition matrices of the league, of batters and of pitchers, and plays games from them; the manual is `doc/lisp_baseball_manual.md`.

The information used here was obtained free of charge from and is copyrighted by Retrosheet.  Interested parties may contact Retrosheet at 20 Sunset Rd., Newark, DE 19711.

## Making the database

```bash
python3 build_retrosheet_db.py --first 2015
```

It downloads Retrosheet's parsed play-by-play, a zip file a season (<https://retrosheet.org/downloads/plays.html>), as far as Retrosheet has them (2025, in November 2026), and
the list of players (`allplayers.zip`), into `/Users/morris/retrosheet_data/zips` (a file already there is not downloaded again; delete it to get a newer one, as Retrosheet
corrects its files), and makes `/Users/morris/retrosheet_data/retrosheet.db` in about 20 seconds. `--directory` says where else to put them. When Retrosheet
publishes another season, run it again.

## The files

| File | What it does |
|---|---|
| `build_retrosheet_db.py` | downloads, reads each season, and writes the tables `turns`, `games` and `players` (its docstring says what each has) |
| `turns.py` | makes turns from rows; this is where the rules are |
| `test_turns.py` | tests of `turns.py` on rows made by hand: `python3 -m unittest test_turns.py` |

## What a turn is

A row of Retrosheet's file is one event: a plate appearance, or something during one (a steal, a wild pitch, a pickoff). The model counts **turns**: everything from the
moment a batter steps up until his plate appearance ends, or the inning does. So a steal during an at bat is part of that batter's turn, and each turn begins in the state
that the last one ended in. The state at the start is the outs, the runners (`bases`: 1 for first, 2 for second, 4 for third, added up), and the batting team's lead; the end
is the outs, the runners, and the runs that scored in between.

How odd rows are handled:

- A row whose event is `NP` ("no play") marks a substitution. It is dropped.
- A turn that ends with the third out has no runners, whoever was left on base.
- The turn is credited to the batter and the pitcher of the row that ended it. A pitching change in the middle of a plate appearance gives the plate appearance to the new pitcher.
- Runs are the runs of Retrosheet's `runs` column, the offense's credit and the defense's blame, earned or not, with or without an error.
- A game that ends with a walk-off ends with runners still on base; the turn is kept as it was.
- A pitcher "started" if he was the first pitcher his team used in the game (`starter`).
- `park` is Retrosheet's id for the ballpark (`NYC21`); `games` has it too.
- `batters_faced` is how many batters the turn's pitcher had faced in the game before it, and `removed_after` is 1 if the next turn of his team's pitching in the game is another pitcher's:
  how a starter's removal is counted (the usual number of batters a starter faces, and how the score and the end of an inning change it).
- `result` is what the batter did in the plate appearance that ended the turn: `strikeout`, `walk` (also a hit by pitch and interference), `single`, `double`, `triple`,
  `home run`, `other` (every other plate appearance), or `none` (the inning ended on a steal before the plate appearance was over).

All game types are kept (`gametype`: regular season, the postseason rounds, the All-Star game); the library uses the regular season for fitting.
