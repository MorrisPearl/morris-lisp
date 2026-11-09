# morris-lisp — Baseball

A baseball game is a long chain of small events. A batter steps up with some outs and some runners on base, and a moment later there are
different outs and different runners, and perhaps a run. If we know how often each of those changes happens, from each situation, we can play
games on a computer: draw a change, move to the new situation, draw the next. Play a game 10,000 times and you know how often each team wins.

This manual builds that, from the plays that [Retrosheet](https://www.retrosheet.org) has recorded, and says what it can and cannot tell you.
The functions are in `lisp_interp/lisp_baseball.py` (the arithmetic, builtins) and `lisp_interp/lib/baseball.lsp` (reading the plays and
asking for players), so there is nothing to load before calling them: they are loaded when called (see `lazy-load`). The program
`examples/baseball_example.lsp` is a short tour.

> The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at
> 20 Sunset Rd., Newark, DE 19711.

`(retrosheet-notice)` shows that statement, as the example program does at its end.

There are ten documents. The **language manual**, [lisp_interpreter_reference.md](lisp_interpreter_reference.md), covers the syntax and the
general builtins (the tables and vectors that appear here are described there). The **library manual**,
[lisp_library_reference.md](lisp_library_reference.md), covers getting data, models, and investments. The **regression manual**,
[lisp_regression_manual.md](lisp_regression_manual.md), covers fitting models to data. The **example programs**,
[lisp_example_programs.md](lisp_example_programs.md), say how whole programs are put together; `examples/baseball_example.lsp` is this one's. The
**CMO manual**, [lisp_cmo_manual.md](lisp_cmo_manual.md), the **forecasting manual**, [lisp_forecasting_manual.md](lisp_forecasting_manual.md), the
**paths manual**, [lisp_paths_manual.md](lisp_paths_manual.md), the **macro models manual**,
[lisp_macro_models_manual.md](lisp_macro_models_manual.md), and the **data guide**, [economic_data_guide.md](economic_data_guide.md), cover structured
deals, forecasting questions, yield curves and paths, models of the whole economy, and which agency publishes what data. **This one is baseball.** A
section name in quotes is a section of this manual, unless it says otherwise.

<!-- This list is made from the headings below: after adding or renaming a section, run
     python3 tools/make_contents.py -->
## Contents

- [The idea](#the-idea)
- [Getting the data](#getting-the-data)
- [States and outcomes](#states-and-outcomes)
- [The league's matrix](#the-leagues-matrix)
- [Players](#players)
- [Ballparks](#ballparks)
- [A batter against a pitcher](#a-batter-against-a-pitcher)
- [When a starter comes out](#when-a-starter-comes-out)
- [Playing games](#playing-games)
- [How good is it?](#how-good-is-it)
- [Reference](#reference)

## The idea

Each plate appearance starts in a **state**: how many outs there are, which bases have runners on them, and how far ahead or behind the batting team
is. It ends in a different state, with some runs scored. A **transition matrix** has a row for each state, and says how likely each ending is.

The league's matrix comes from counting what happened, in every plate appearance of eleven seasons. A player's is the league's, changed to be like
the player: a batter who hits more home runs than most has a matrix with more of the endings that home runs make. A batter facing a pitcher is a
combination of the two. Then a game is a walk through the states, drawing each ending from the right player's row.

Five decisions shape it, and each is explained where it is made:

1. A **turn** is a plate appearance and whatever happens during it (a steal, a wild pitch), so that each turn begins where the last one ended.
   "States and outcomes".
2. Rare situations borrow from common ones: the **smoothing** in "The league's matrix".
3. A player's matrix is made from his **results** (strikeouts, walks, singles ...) over all the states, not state by state, because there are too
   few turns in each state to say anything: "Players". This is the Dirichlet prior with a "starting record" that new players start from.
4. A batter and a pitcher are combined by **odds ratio**, and a **ballpark** is one more factor: "A batter against a pitcher".
5. A starting pitcher is taken out **by chance**, more often as his workload grows, as his team falls behind, and between innings: "When a starter
   comes out".

## Getting the data

Retrosheet's parsed play-by-play, one zip file a season, is at <https://retrosheet.org/downloads/plays.html>. The program that downloads the seasons
from 2015 on (as far as Retrosheet has them: 2025, in November 2026) and makes the database is in `load_retrosheet_data/`:

```bash
python3 load_retrosheet_data/build_retrosheet_db.py --first 2015
```

It puts the zip files in `/Users/morris/retrosheet_data/zips`, and makes `/Users/morris/retrosheet_data/retrosheet.db`, in about 20 seconds, with the
tables

| Table | A row is | Columns |
|---|---|---|
| `turns` | a turn at bat | `gid` (the game), `season`, `date`, `gametype`, `park`, `inning`, `home_batting`, `batting_team`, `pitching_team`, `batter`, `pitcher`, `starter` (1 if the pitcher started the game), the state it began in (`outs`, `bases`, `score_difference`), where it ended (`new_outs`, `new_bases`, `runs`), `plate_appearance` (1 unless the inning ended on a steal), `result`, `batters_faced` (by the pitcher before the turn) and `removed_after` (1 if the pitcher is replaced right after it) |
| `games` | a game | `gid`, `season`, `date`, `gametype`, `visiting_team`, `home_team`, `visiting_runs`, `home_runs`, `innings`, `park` |
| `players` | a player | `id` (Retrosheet's: five letters of the name and a number, `judga001`), `last`, `first`, `bats`, `throws`, `first_season`, `last_season` |

The library reads it by its path, `retrosheet-database`, which is the one above; to keep it elsewhere pass `:database` to `fit-baseball-model`. A
season is added by running the program again when Retrosheet has it. `python3 -m unittest test_turns.py`, in that directory, tests how a turn is made
from Retrosheet's rows; `load_retrosheet_data/README.md` says what it does with each odd row (a "no play" row that notes a substitution is not a
turn).

## States and outcomes

A **state** is what is known when a batter steps up:

| Part | Values |
|---|---|
| `home_batting` | 0 if the visiting team is batting (the top of an inning), 1 if the home team is |
| `outs` | 0, 1 or 2 |
| `bases` | the runners, as a number from 0 to 7: 1 for a runner on first, 2 on second, 4 on third, added up (5 is first and third) |
| `score_difference` | the batting team's score less the other team's, from -3 (for -3 or less) to 3 (for 3 or more) |

That is 2 x 3 x 8 x 7 = 336 states. The home team is separate from the visitors because it plays differently at the end of a game (it does not bat if it is
ahead after the top of the last inning, and a lead ends the game). Seven score differences are enough to tell a close game from a rout.

An **outcome** is where the turn ends: `new_outs` (0, 1, 2, or 3, which ends the inning), `new_bases` (the runners then; 0 if the inning is over), and
`runs` (0 to 4). A **turn** is one batter's plate appearance and what happens to the runners during it, so a runner who steals second while the
batter is up is part of the batter's turn. That is what lets one turn begin in the state the last one ended in.

A matrix has a row for each of the 336 states and a column for each of the 4 x 8 x 5 = 160 outcomes (most of which cannot happen from most states).
When the inning ends, the next state is the other team's, with no outs and no runners and the score difference turned around.

The runs and the outs are the whole of what the model knows about a turn's effect. It does not know whether a run came from a home run or from an error,
and does not separate earned runs from unearned ones: if a run scores, the batter's team is credited and the pitcher's blamed.

## The league's matrix

`transition-counts` counts the turns in a table (the same SQL that picks the turns gives the columns it needs):

```lisp
(define turns (make-table "home_batting" (vector 0 0 0)  "outs" (vector 0 0 0)  "bases" (vector 0 0 0)  "score_difference" (vector 0 0 0)
                          "new_outs" (vector 1 0 0)  "new_bases" (vector 0 1 0)  "runs" (vector 0 0 1)  "count" (vector 70 25 5)))
(define counts (transition-counts turns))
(table-row-count (transition-table counts))     ; => 3
```

Three kinds of turn, that began with no one out and no one on, in 100 turns: 70 were an out, 25 put a runner on first, and 5 were a home run.
`transition-table` shows any matrix as a table with a row for each state and outcome that happened, and `transition-row` shows one state's row,
the most likely first:

```lisp
(transition-row counts 0 0 0 0)     ; the visitors batting, no outs, no one on, tied
```

The league's counts, from the database (the example program shows this row too):

```lisp
(define model (fit-baseball-model))                        ; the seasons 2015 to 2025, in a few seconds
(define league (baseball-model-league model))              ; its probabilities
(transition-row league 0 0 0 0)
```

| `new_outs` | `new_bases` | `runs` | Chance | What it is |
|---|---|---|---|---|
| 1 | 0 | 0 | 0.690 | an out |
| 0 | 1 | 0 | 0.227 | a runner on first: a single, a walk, an error |
| 0 | 2 | 0 | 0.046 | a runner on second: a double |
| 0 | 0 | 1 | 0.033 | a home run |
| 0 | 4 | 0 | 0.005 | a runner on third: a triple |

**Smoothing.** Some states are rare (the home team, down by 3 or more, with two outs and the bases loaded) and the count of a rare state is a poor
guide to its chances. `smooth-transitions` turns counts into probabilities after adding a few imaginary turns to each state, spread the way the real
turns are in the states with the same outs and runners, whoever is batting and whatever the score. The default is 20 imaginary turns (`:weight`). A
state that never happened gets the probabilities of those states, and an outcome that is possible from a state like it is possible from it. A state
with thousands of real turns is changed hardly at all.

**The matrix of states.** `state-transition-table` turns an outcomes matrix into the state to state matrix that the idea began with, with a row for
each state and next state: the outs and runners are the outcome's, the score difference is changed by the runs (and stays at 3 or -3), and a third out
passes the inning to the other team. It is the form to use if you want to raise the matrix to a power, or find the long-run frequency of each state.

**What an inning is worth.** `run-expectancy` solves for the runs that are expected in the rest of an inning, from each of the 24 combinations of outs
and runners, if the turns go the way the matrix says (the "RE24" table, a classic of baseball analysis):

```lisp
(run-expectancy (baseball-model-league-counts model))
```

| Runners \ Outs | 0 | 1 | 2 |
|---|---|---|---|
| none | 0.50 | 0.27 | 0.10 |
| first | 0.89 | 0.53 | 0.23 |
| second | 1.14 | 0.69 | 0.33 |
| first and second | 1.50 | 0.93 | 0.45 |
| third | 1.39 | 0.97 | 0.37 |
| first and third | 1.79 | 1.19 | 0.50 |
| second and third | 1.97 | 1.39 | 0.60 |
| loaded | 2.33 | 1.59 | 0.78 |

The pitch-by-pitch details are gone, but the table is the same as the published ones: an inning that begins with no one on and no one out is worth about
half a run, and a runner on first with no outs adds about 0.4. A team that has one out and a runner on second has 0.69 runs coming; if it bunts the
runner to third and makes a second out, it has 0.37.

## Players

The counts of one batter, in one state, are tiny: a regular batter has about 4,000 turns in ten seasons, spread over 336 states, 10 or 20 turns each in
the ordinary states and none in most of the others. A matrix made from them would say how lucky the batter was in those turns. But what makes a
batter different from the next one is mostly **what he does at the plate**, which he does in every state. So a player's matrix is made in two steps.

**Results.** Each turn has a result, from the plate appearance that ended it:

| Result | |
|---|---|
| `strikeout` | |
| `walk` | a walk, a hit by pitch, interference |
| `single`, `double`, `triple`, `home run` | |
| `other` | any other plate appearance: an out on a ball in play, an error, a fielder's choice, a sacrifice |
| `none` | the inning ended on a steal before the plate appearance was over |

The league's counts are of each outcome in each state *and* each result. A home run from a state with a runner on first is an outcome of 2 runs and
no runners; a single from there may be a runner on first and one on third, or one on second, or a run: the outcome says what happened to the runners and
the outs, and the result what the batter did to make it happen.

**A starting record.** A player's *profile* is the number of turns he had with each result. The league's mix of results is the prior, worth some
number of turns, `strength`; the player's shares are

    share = (his turns with the result + strength x the league's share) / (all his turns + strength)

This is the mean of a **Dirichlet distribution** of the results: it started out as the league's mix, and learned what the player did. The strength is
the "starting record" that a new player starts from: a batter with no turns has exactly the league's shares, and with a few hundred turns he is
partly the league and partly himself. A batter with thousands is mostly himself.

**Tilting the league.** The player's matrix is the league's with each result's counts multiplied by the player's share of the result over the league's
share, and each state's row then scaled to add up to 1 (`tilt-transitions`). A batter whose share of home runs is twice the league's has twice the
league's counts of every home run outcome, in every state:

| Chance, from no outs, no one on | League | Aaron Judge | Tarik Skubal pitching |
|---|---|---|---|
| out | 0.690 | 0.603 | 0.734 |
| runner on first | 0.227 | 0.276 | 0.190 |
| runner on second | 0.046 | 0.042 | 0.041 |
| home run | 0.033 | 0.077 | 0.031 |

The runs a lineup would make tell the same story. If all nine batters were the league's average, an inning would be worth 0.50 runs; if all nine were
Judge, 0.99 (the model is fitted to turns from 2015 to 2025); if the pitcher were Skubal, 0.38. (`run-expectancy` of the player's matrix with the
league's counts as `:weights`.)

**How strong the prior is.** If players differed a lot, the strength would be small, and a few turns would already say something about a player. If
they were all alike, the differences would be luck, and the strength would be large. `prior-strength` finds the strength at which what we saw of all the
players is most likely if each player's shares were drawn from a Dirichlet distribution around the league's (the maximum of
`prior-strength-loglik`, which gives the likelihood of any strength you try). `fit-baseball-model` does this for the batters and the pitchers
separately:

```lisp
(baseball-model-batter-strength model)         ; 123, for the seasons 2015 to 2025: a batter's own record is worth as much as it is
                                               ; after 123 turns' worth of the league's, to a new batter
(baseball-model-pitcher-strength model)        ; 334
```

The pitchers' is bigger: pitchers differ less from each other, in the mix of results they allow, than batters do in the mix they make, so a pitcher's
own record has to be longer before it says as much.

**Why not count state by state?** The first attempt at this was to give each player a Dirichlet prior in every state separately, with the league's
row as its mean, and to add the player's own counts in that state. It does not work, and the measurement that shows why is worth knowing. Played on
the turns of 2025, the average log probability of a turn's real outcome, given its state, is -1.1623 from the league's matrix, and -1.1620 from the
state-by-state matrices of the batters (made from 2015 to 2024). The result-based matrices of the batters give -1.1595, of the pitchers -1.1616, and of
a batter and a pitcher together, combined as in the next section, -1.1587. A batter's turns in one state say little about his turns in another, but his rate of strikeouts, which he has in every state, says a lot about
them all.

Functions: `baseball-batter-matrix`, `baseball-pitcher-matrix`, `baseball-bullpen-matrix`, `baseball-players`.

```lisp
(baseball-players model "Judge")                        ; a table: the ids of players named Judge
(define judge (baseball-batter-matrix model "judga001"))
```

A pitcher's matrix is made the same way. `baseball-bullpen-matrix` is that of all the relievers (pitchers who did not start the game), of a team's if you
give `:team "NYA"` (the abbreviations are Retrosheet's).

**What a pitcher's matrix is.** It is a measure of the pitcher *together with* everything that goes with him. The outcomes are runs and outs: the model does
not know whether an out was made by a good fielder or a batter's strikeout, or whether a hit on a ball in play was a good pitch badly hit or a good swing
against a bad one, and it does not separate errors from other plays. So a pitcher whose team has a fine defense looks better than he is, one with a poor
defense looks worse, and a pitcher who pitches in a ballpark that gives up home runs shows the ballpark in his record. A pitcher who pitched for several
teams in the seasons of the model has their defenses averaged; one who stayed with a team has his team's. The same is true of a batter, who carries his
home park. The ballpark is separated out below ("Ballparks"), but not the defense; and since a player's record has his own ballpark in it, the park
factor, which is applied to both teams' batters, counts it twice for the home team's players. It is a small effect (the next section says how small).

## Ballparks

A ballpark changes what happens in it: Coors Field gives up home runs and hits, Oracle Park and T-Mobile Park take them away. The model treats it as one more
tilt, of the same kind as a player's. Its profile is the results of the turns in the park. Its prior is not the league's mix of results: a park with a lot
of home runs may be a park of sluggers (the home team's players are in all of its home games). It is the mix of results in the **road games of the team
that played there most**, whose players are the same ones, in other parks. The park's share of each result, with the prior, is

    share = (its turns with the result + strength x the road games' share) / (its turns + strength)

and its matrix is the league's counts multiplied by the park's share over the road games' share: the same arithmetic as a player's, with another prior
(`tilt-transitions` with `:prior`). The strength is found the same way, `prior-strength` with `:priors`, a table with each park's own prior; it is about 2,600
turns, which is a great deal less than a park has (about 6,000 a season, 60,000 in the eleven seasons), so the park's own results nearly all count. The park is named by Retrosheet's
id, `"DEN02"` for Coors Field, or by a team: `(baseball-park-matrix model "COL")`.

| Chance, from no outs, no one on | League | Coors Field | T-Mobile Park |
|---|---|---|---|
| out | 0.690 | 0.655 | 0.707 |
| runner on first | 0.227 | 0.244 | 0.218 |
| home run | 0.033 | 0.037 | 0.031 |

**Does it help?** Slightly. On the turns of 2025 the average log probability of the real outcome improves from -1.1587 (batter against pitcher) to -1.1584
when the park is in. Almost all of that is Coors Field (+0.0033 a turn there); 19 parks gained a little and 11 lost a little.

## A batter against a pitcher

The league, the batter, the pitcher, and perhaps the ballpark each have a matrix. If the batter is twice as likely as the league to strike out, and the pitcher is twice as
likely, how likely is the matchup? The **odds ratio** method, called "log5" when there are two outcomes, says: each outcome's chance is the batter's
times the pitcher's over the league's, and the row is then scaled to add up to 1. So an outcome that both make more likely is made more likely still, but
not twice as much:

```lisp
(define skubal (baseball-pitcher-matrix model "skubt001"))
(define matchup (baseball-matchup model judge skubal))     ; = (combine-transitions judge skubal league)
(transition-row matchup 0 0 0 0)
```

| Chance, from no outs, no one on | Judge against the league | Judge against Skubal |
|---|---|---|
| out | 0.603 | 0.651 |
| runner on first | 0.276 | 0.235 |
| home run | 0.077 | 0.074 |

The matchup is in between: Skubal takes away some of what Judge does, and not all. A ballpark is one more factor: its chances over the league's, so
that an outcome the park makes more likely is made more likely still. `(baseball-matchup model judge skubal :park "COL")` is `(combine-transitions judge
skubal league park-matrix)`.

## When a starter comes out

A game is not pitched by one man. The starter faces batters until he is taken out, then relievers pitch (all of a team's together, as one matrix). When
he is taken out is up to the manager, and the model draws it. After each turn of his, he is taken out with a chance that depends on three things,
estimated from every start since 2015 (`removal-chances`, from the turns' columns `batters_faced` and `removed_after`):

- **His workload**: the batters he has faced, over the batters he usually faces in a start (22.5 for Skubal), in tenths. A starter well past his usual
  workload is very likely to be out; one who has done half of it is rarely taken out.
- **The score**: how many runs his team is ahead (or behind: from -5 or fewer to 5 or more). A starter who is behind by 4 or more is taken out more often
  than one in a close game: managers do not leave a man in who is losing.
- **Whether the turn ended the inning**: between innings is the easy time to change pitchers, and a starter near his usual workload is taken out in about 30% of those
  turns, against 7% in the middle of one.

| After his 20th batter, when he usually faces 22 | Chance he comes out |
|---|---|
| in a tie, in the middle of an inning | 0.07 |
| behind by 5 or more, in the middle of an inning | 0.17 |
| in a tie, with the third out | 0.31 |
| behind by 5 or more, with the third out | 0.45 |

(`removal-chance` gives any of these.) A team whose `starter-batters` is a number has its starter face that many batters and then come out; one whose is
`'()`, the default, has him taken out by chance. The chances are for every starter alike; what is each starter's own is the number of batters he usually faces.

## Playing games

`simulate-baseball-games` plays a game between two teams, many times. A team is made with `make-baseball-team`:

| Slot | |
|---|---|
| `lineup` | the nine batters' ids, in the order they bat |
| `starter` | the starting pitcher's id |
| `bullpen` | the team whose relievers pitch after the starter ("NYA"), or `'()` for relievers in general |
| `starter-batters` | how many batters the starter faces before a reliever comes in, or `'()` (the usual) for the starter to be taken out by chance ("When a starter comes out"), from the number of batters he faced per start in the seasons of the model (`baseball-starter-batters`: 22.5 for Skubal) |
| `park` | the ballpark of the game, when the team is the home team: Retrosheet's id for it ("NYC21"), a team's abbreviation for its home park, or `'()` for none in particular |

```lisp
(define home (make-baseball-team :lineup (list "grist001" "riceb001" "judga001" "bellc002" "stanm004" "wella002" "volpa001" "mcmar001" "cabaj001")
                                 :starter "gil-l001" :bullpen "NYA" :starter-batters '() :park "NYA"))
(define visitors (baseball-team-in-last-game model "BOS" 2025))     ; the Red Sox's lineup and starter in their last game of 2025
(define played (simulate-baseball-games model home visitors :games 10000 :seed 1))
(home-win-probability played)
```

`baseball-team-in-game` takes the batting order, starting pitcher and ballpark of any game in the database (given its id), which is the way to try a model on a
real game: the example program plays Game 7 of the 2025 World Series, Toronto against the Dodgers, whose starter was Shohei Ohtani. The model gives
Toronto 44% (the Dodgers won, in 11 innings).

The result is a table with a row for each game (`home_runs`, `visiting_runs`, `innings`). From it, anything: the chance of winning, the distribution of
total runs, the chance of an extra-inning game.

The rules played: nine innings, and more while the score is tied; the home team does not bat in the bottom of the last inning if it is ahead, and the
game ends the moment it takes the lead in it; in extra innings a runner starts on second base (the rule since 2020, unless `:ghost-runner #f`); the
starter pitches until he is taken out, and relievers the rest of the game (a game still tied after the 30th inning is stopped, and `home-win-probability` leaves it out). The same `:seed` gives the same games; without one, the numbers come from the shared generator that `random-seed` sets.

**How it is done.** The games are played together, not one after the other: each step draws the next turn of every game still being played, with the
row of the right matchup for each, so 10,000 games take about a second.

## How good is it?

`baseball-backtest` plays out the games of a season that the model was not fitted to: each game, with the batting order and starting pitchers it really
had, 1,000 times (`:games-per-game`), and records how often the home team won:

```lisp
(define model (fit-baseball-model :last-season 2024))
(define tried (baseball-backtest model 2025 :games-per-game 1000))
(baseball-scores tried)
```

| Forecast | Log loss | Brier score | Picked the winner |
|---|---|---|---|
| the model (ballparks, starters taken out by chance) | 0.6825 | 0.2447 | 55.9% |
| the home team's usual rate, always | 0.6895 | 0.2482 | 54.3% (the home team, every time) |

For the 2,430 games of 2025 (log loss and Brier score: lower is better; 0.693 is saying 50% every time). The model's chances are 53.1% for the home team, on
average, and it won 54.3% of the time in 2025 (it was between 52.1% and 55.7% in the seasons 2015 to 2024); it expects 9.05 runs a game, and 8.89 were scored.
Those are the calibration checks. The 0.007 improvement in log loss is not large, which is what you should expect of baseball: a baseball game is mostly
unpredictable. The chances it gives have a standard deviation of 0.08, and the team it likes better wins 55.9% of the games, against 54.3% for the home
team every time.

**Are the parks and the pitching changes worth it?** The `:parks` and `:removal` options of `baseball-backtest` turn each off, so that each can be
tried on the same games and the same random numbers:

| Ballparks | Starters taken out by chance | Log loss | Picked the winner |
|---|---|---|---|
| no | no (they face their usual number of batters) | 0.6820 | 55.8% |
| yes | no | 0.6823 | 55.2% |
| no | yes | 0.6833 | 54.5% |
| yes | yes | 0.6825 | 55.9% |

No: to the accuracy these can be measured, neither changes how well the model forecasts a game. The differences are within the noise of the simulation (two runs of the
same model differ by about 0.0004 in log loss, since each game is played 1,000 times and the chance of a win has an error of 0.015). They are in the model because they are what happens,
not because they forecast better: the ballpark helps a little in predicting a single turn ("Ballparks"), and the starter's removal makes the innings
the relievers pitch more like those of real games, which matters for the distribution of the score and for questions that are not who wins.

**What it leaves out.** It is a model of the average of what a lineup and a pitcher do, in the way the league plays:

- *Defense and the catcher.* A pitcher's matrix is the pitcher with his defense: "Players".
- *Handedness.* Whether a left-handed batter faces a left-handed pitcher.
- *Changes during a season.* Injuries, a pitcher who is tired, a lineup that rests a star. The team's lineup is what it was in the games that are played.
- *The bullpen is a team's relievers all together*: who comes in, and when, is not modeled (the starter is taken out by chance, "When a starter comes
  out", and then the team's relievers pitch the rest of the game as one pitcher).
- *Aging.* A player's record is all of his turns in the seasons of the model, the older ones as much as the recent ones. (`:first-season` of
  `fit-baseball-model` is the way to say recent.)
- *The score and the inning.* Only the score difference is known to a state, not the inning, so a pitching change or a bunt in the ninth looks like
  one in the first.

**Next season.** To say how often each team wins in 2026 needs the schedule, the lineups, and the starters, none of which exist yet; what this model
does is say, for any lineup and any starter you decide on, how that game would go. A season is the sum of its games, so a season of games, each with
the lineup you expect and a pitcher you pick from the rotation, is the way to build the chance a team wins 90 games.

## Reference

#### `(fit-baseball-model [:database path] [:first-season 2015] [:last-season 2025])`

Reads the turns of the regular seasons from the database and returns a `baseball-model`: the league's counts (`baseball-model-league-counts`),
its probabilities (`baseball-model-league`), the strength of the priors for batters, for pitchers and for ballparks (`baseball-model-batter-strength`,
`baseball-model-pitcher-strength`, `baseball-model-park-strength`), the matrix of each ballpark, the chances that a starter is taken out
(`baseball-model-removal`), and the matrices made so far. A few seconds.

#### `(baseball-batter-matrix model id)`, `(baseball-pitcher-matrix model id)`, `(baseball-bullpen-matrix model [:team abbreviation])`

A player's, or a team's relievers', probabilities: `tilt-transitions` of the league's with the profile of the player's turns in the seasons of the model.
A player who has no turns gets the league's. They are made once and kept.

#### `(baseball-park-matrix model park)`

A ballpark's probabilities: the league's tilted toward the results in the park, from a prior of the road games of the team that played there most. `park` is
Retrosheet's id for it (`"DEN02"`) or a team's abbreviation for the park it played most of its home games in in the last season of the model. The league's
own for a park that is not in the seasons of the model.

#### `(baseball-matchup model batter-matrix pitcher-matrix [:park park])`

The probabilities of a batter against a pitcher, in a ballpark if there is one: `combine-transitions` with the model's league (and the park's matrix).

#### `(baseball-players model last-name)`

A table of the players with the last name (or beginning with it, if it ends with `%`): `id`, `first`, `last`, `bats`, `throws`, `first_season`, `last_season`.

#### `(baseball-starter-batters model id)`

How many batters a starting pitcher faced per game he started, in the model's seasons (22 if he started none).

#### `(make-baseball-team :lineup ids :starter id :bullpen team :starter-batters n :park park)`, `(baseball-team-in-game model gid home)`, `(baseball-team-in-last-game model team season)`

A team to play a game with. `starter-batters` is a number of batters, or `'()` for the starter to be taken out by chance; `park` matters for the home team. `baseball-team-in-game`
is the team that played in a game of the database, with its park: `home` is 1 for the home team, 0 for the visitors.

#### `(simulate-baseball-games model home visitors [:games n] [:seed n] [:ghost-runner #t])`

A table of games played (`home_runs`, `visiting_runs`, `innings`). `(home-win-probability results)` is how often the home team won.

#### `(baseball-backtest model season [:games-per-game 500] [:max-games n] [:seed 1] [:parks #t] [:removal #t])`, `(baseball-scores tried)`

The model's chance that the home team won, for each game of a season, with the real lineups, starters and ballparks; and how good those chances were, beside the home
team's usual rate (`log_loss`, `brier`, and `picked`, the share of games won by the team with the better chance). Game n is played with the seed `seed` + n, so that
two backtests see the same random numbers; `:parks #f` and `:removal #f` leave the ballparks out and have each starter face his usual number of batters.

#### `(retrosheet-notice)`

Shows the statement that Retrosheet asks to appear wherever its information is used.

#### `(transition-counts table)`

A matrix of counts from a table of turns, with a row for each turn or kind of turn and the columns `home_batting`, `outs`, `bases`, `score_difference`, `new_outs`,
`new_bases`, `runs` and optionally `count` and `result`.

#### `(smooth-transitions counts [:weight 20])`

The probabilities of a matrix of counts: see "The league's matrix". Needs the 24 combinations of outs and runners each to have occurred.

#### `(tilt-transitions league profile strength [:prior profile])`

A player's (or a ballpark's) probabilities. `profile` is a table of the turns, with a row for each `result` and its `count`; `strength` is how many turns the prior is worth;
the prior is the league's mix of results, or another table of turns (`:prior`), such as the road games of a ballpark's team. `league` is the probabilities of counts that
have a column `result`.

#### `(combine-transitions batter pitcher league [park])`

The probabilities of a batter against a pitcher, by the odds ratio; with a ballpark's matrix, its ratio to the league's is another factor.

#### `(prior-strength table group league [:priors table])`, `(prior-strength-loglik table group league strength [:priors table])`

How strongly the prior pulls on a player's mix of results: the strength at which the players of a table (rows of `group`, `result`, and `count`) are most likely, and the
log likelihood of any strength. The prior of every player is the league's mix, or, with `:priors` (a table of the same form), the player's own.

#### `(removal-chances table)`, `(removal-chance chances batters-faced usual lead inning-ended)`

How likely a starting pitcher is to be taken out after a turn: `removal-chances` of a table of the turns of starters, with the columns `batters_faced`, `usual`, `lead`,
`inning_ended` and `removed_after`; and the chance, from the batters a starter has faced so far, the number he usually faces, his team's lead after the turn, and whether the turn
ended the inning (1 or 0).

#### `(run-expectancy matrix [:weights counts])`

The runs expected in the rest of an inning, from each of the 24 combinations of outs and runners: a table of `outs`, `bases`, and `runs`. The 336 states are weighted
by `counts` (a matrix of counts), or by the matrix's own counts.

#### `(transition-table matrix)`, `(transition-row matrix home-batting outs bases score-difference)`, `(state-transition-table matrix)`

A matrix as a table: with a row for each state and outcome (`value` is the count or the chance); one state's row, the most likely first; and as states to next states.

#### `(simulate-games home visitors [:games n] [:seed n] [:ghost-runner #t])`

What `simulate-baseball-games` calls: a team is a list of nine matrices against the other team's starter, nine against its relievers, and either the batters its starter
faces, or a list of the chances `removal-chances` makes and the batters he usually faces.
