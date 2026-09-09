# RUN.md

> **Primary review method: a completely local application.** Python 3.11+ and
> SQLite. No Docker, no Node, no external services, and **no API key required**
> to run the demo or the evaluation.

**The two-minute version.** Everything below is these four lines:

```bash
make install
make seed
make serve      # serves http://127.0.0.1:8000
make eval       # offline, no key, ~1 second
```

If you would rather read the evaluation than click through the demo:

```bash
make explore    # builds evals/results/explorer.html - open it, no server needed
```

---

## 1. Required runtimes and versions

| Requirement | Version | Check |
|---|---|---|
| Python | **3.11 – 3.14** | `python3 --version` |
| SQLite | 3.35+ | bundled with Python; `python3 -c "import sqlite3;print(sqlite3.sqlite_version)"` |

Nothing else. Every dependency resolves to a prebuilt wheel on all four
supported Python versions, so no compiler is needed. `make install` selects an
interpreter automatically and prints which one it used; override with
`make install PY=/path/to/python3.12`.

Verify the wheel claim yourself:

    make check-wheels     # resolves requirements.txt binary-only for cp311–cp314

Dependencies are declared as version *ranges*, not exact pins. An exact pin
looks reproducible and is actually a hazard: the pinned build only has wheels
for the Python versions that existed when it was released, so a reviewer on a
newer interpreter silently falls back to a source build and fails on something
unrelated to this project. This is not hypothetical - it is how the first
version of this file was wrong.

## 2. Required environment variables

**None are required.** The demo and the evaluation both run with no
configuration at all.

Copy `.env.example` to `.env` only to change a component or to run against the
live API:

    cp .env.example .env
    # then set SARVAM_API_KEY=...

`.env` is loaded automatically at startup if present. It is gitignored and is
not part of this repository; `.env.example` lists every variable with empty
values. No credential is committed anywhere in this repo.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `SARVAM_API_KEY` | only for `make eval-live` | - | Live model access |
| `LMH_LLM` | no | `llm.stub` | `llm.stub` \| `llm.cassette` \| `llm.sarvam` |
| `LMH_FORMATTER` | no | `formatter.passthrough` | `formatter.passthrough` \| `formatter.llm` |
| `LMH_STORE` | no | `store.sqlite` | `store.sqlite` \| `store.memory` |
| `LMH_INDEX` | no | `index.inmemory` | Candidate index |
| `LMH_PHONETICS` | no | `phonetics.dmetaphone` | `phonetics.null` is an ablation |
| `LMH_DATABASE_URL` | no | `sqlite:///./data/lmh.db` | Database location |
| `LMH_POLICIES` | no | full stack | Comma-separated; removing a name is an ablation |

## 3. Install dependencies

    make install

Equivalent to `python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt && .venv/bin/pip install -e .`

## 4. Create, migrate and seed the database

    make seed

Runs `alembic upgrade head` against `./data/lmh.db` (two hand-written revisions:
`0001` the initial schema, `0002` separating a lexeme's prior from its derived
confidence), then loads the reproducible seed persona from
`evals/data/persona_seed.json` - 24 terms with dated evidence, guards, standing
instructions and app bindings.

The persona is dated *relative* to a reference date in the file and shifted to
the current date on load, so "Rukmini Iyer has not been used in nine months" stays true
whenever you run it. Three evaluation cases depend on that.

## 5. Start every required process

    make serve

One process. FastAPI serves the JSON API, the demonstration page and the case
explorer. No worker, no queue, no cache, no build step, and no network access of
any kind.

`make seed` (step 4) is a convenience, not a prerequisite: on the first request
the server migrates the database if it has no schema and loads the seed persona
if memory is empty. The port is a variable: `PORT=8001 make serve` if 8000 is
already taken on the review machine.

There is no microphone in the demo. Recognition is upstream of this system and
owned by the platform; the input here is the recogniser's *output*, typed into a
box or loaded from a prepared case. An earlier version bundled a local
recogniser, and it made that model's accuracy the thing under evaluation - a
mangled transcript turned a correct abstention into what looked like a bug.
Text in, text out, is also exactly the contract the evaluation measures, so the
demo and the numbers describe the same system.

## 6. Interface to open

    http://127.0.0.1:8000          (or $PORT, if you set one)

## 7. Primary interactions to try

The page is laid out as the six things the brief asks a reviewer to be able to
do. Each is also a single API call and a single CLI command - there is nothing
behind a button that is not also on the API.

| | In the UI | On the API | From the CLI |
|---|---|---|---|
| 1. Provide observations | "Teach it" | `POST /observations` | `lmh teach` |
| 2. Inspect the resulting memory | the table at the bottom | `GET /memory` | `lmh inspect` |
| 3. Provide new ASR + formatted text | the two boxes at the top | `POST /dictate` | `lmh dictate` |
| 4. See the memory-aware result | the three-line reveal | same response | same |
| 5. Understand why it did or did not act | "Why", under the result | `resolutions[]` | printed underneath |
| 6. Reset and repeat | "Reset to the seeded persona" | `POST /reset` | `make reset` |
| - See all 1,926 evaluation cases | "The evidence", or the header link | `GET /explorer` | `make explore` |

**The fastest tour:** press **Run** on what is already in the boxes, and read the
three lines that appear - what the recogniser **produced**, what the formatter
**made of it**, what **memory** did. Then press the prepared example *"the same
word, ordinary sense"* and watch it do nothing at all.

**Eight prepared examples are one click each in the UI.** Three of them are
cases where the correct behaviour is to change nothing - those are the ones a
find-and-replace dictionary gets wrong, and the reason to look at this at all.

The same tour from the command line:

```bash
# 2. Inspect memory: confidence, state, variant counts, guards
python -m lmh.cli inspect

# 3/4/5. A correction that should happen
python -m lmh.cli dictate "The Sarvam Kiwi service is dropping requests." \
    --app com.tinyspeck.slackmacgap

# ... the same word, which must be left alone
python -m lmh.cli dictate "I ate a kiwi for breakfast." --app com.microsoft.Outlook

# ... both at once: one occurrence corrected, one not
python -m lmh.cli dictate \
    "Adith Narayanan is debugging Kiwi while I finish the kiwi smoothie." \
    --app com.tinyspeck.slackmacgap

# ... the same handle, right in Slack and wrong in Mail
python -m lmh.cli dictate "I posted the trace in hash eng asr." --app com.tinyspeck.slackmacgap
python -m lmh.cli dictate "I posted the trace in hash eng asr." --app com.microsoft.Outlook

# ... native Devanagari, through the same code path
python -m lmh.cli dictate "मिरा शर्मा को भेज दो।" --app com.tinyspeck.slackmacgap

# 1. Teach it something, and watch it decline a rewrite
python -m lmh.cli teach "Aadith Kulkarni" --before "Adith Kulkarni"
python -m lmh.cli teach "Please ask Aadith when he is free" --before "Ask Aadith to review it"

# 6. Reset and repeat
make reset
```

Every `dictate` prints the full decision trace underneath the output: each
candidate, each policy, the weight and the sentence it gave, and whether the
gate opened at all.

## 8. Run the evaluation

    make eval

Runs the two tiers that assert *specified* behaviour: 69 application cases
(what happens to the text) and 15 learning cases (what evidence does to
memory). They are separate files with separate runners because they fail
differently - a system can rewrite text correctly while learning the wrong
thing from it.

The large derived tier is a separate command, because it answers a different
question - not "does the specified behaviour hold?" but "across ~1,800
mechanically-derived situations, which *kinds* does it get wrong?":

    make eval-generated     # 1,842 cases, ~4 seconds, with the breakdown
    make generate           # rebuild the tier from committed inputs

`make generate` is deterministic: same inputs, same seed, byte-identical
output. The tier is committed, so it does not need regenerating to be reviewed.

Offline. No API key, no network. Deterministic: every time-sensitive case pins
its own clock, model responses (when a model is enabled at all) are replayed
from committed cassettes, and the committed run made **zero** model calls.

    make eval-live    # requires SARVAM_API_KEY; records cassettes as it goes

**Browse the results rather than reading JSON:**

    make explore      # evals/results/explorer.html

One self-contained page, two tabs, no server and no network:

- **Specification** - each of the 69 hand-written cases in full: inputs, the
  diffed output, the complete decision trace with every policy's rationale, and
  the memory state at the moment it decided.
- **Derived** - all 1,842 generated cases, filterable by family, script,
  confusion rule and pass/fail, above the breakdown tables that say *where* the
  system fails rather than whether. Start by setting the filter to "failing
  only": there are three, and they are all the same shape.

## 9. Where results are written

    evals/results/
      explorer.html                    every case, browsable - start here
      baseline/
        summary.json                   aggregate metrics, per class, per reason code
        cases.jsonl                    one row per case: input, expected, actual,
                                       memory state, full decision trace
        learning.jsonl                 the learning tier: one row per memory-state case
        report.html                    self-contained summary report
      generated/
        summary.json                   the derived tier, sliced by family, persona,
                                       script and confusion rule
        cases.jsonl                    one row per derived case
      ablation-no-guards/              …and five more ablations, same shape
      stress/report.json               the stress-suite output

All of it is committed, and all of it regenerates:

    make eval             # specification + learning tiers
    make eval-generated   # the 1,842-case derived tier
    make ablations        # all six ablations, exactly as committed
    make stress           # the stress suite
    make explore          # rebuild the explorer page

An ablation is a configuration list, never a code branch - which is what makes
the table in the README checkable rather than assertable:

    python -m lmh.cli eval --policies suppression,exact_variant --label my-ablation
    python -m lmh.cli eval --phonetics phonetics.null --label no-phonetics

## 10. Reset procedure

    make reset

Deletes `./data/` and re-seeds. The observation log is the only authoritative
state, so this is a complete reset - there is nothing else to clear. `POST
/reset` does the same thing in-process for the running demo.

---

## Verify the setup

    make test

**150 tests** in five files:

| File | Count | What it protects |
|---|---|---|
| `tests/test_fixture_integrity.py` | 19 | Properties of the *evaluation itself*: schema validity, unique ids, expectation self-consistency, taxonomy coverage, the negative-case ratio, that every learning fixture actually executes and asserts something a check reads, and that every configurable component name resolves and is honoured |
| `tests/test_engine.py` | 40 | The engine's mechanisms: the projection under supporting and contradicting evidence, prior decay, instruction parsing, renames, deletions and suppression |
| `tests/test_robustness.py` | 67 | Regression guards for failures the stress and derived suites found, including the Indic-script path, the romanisation fold's coverage, and the negative half of the derived tier run inline |
| `tests/test_api.py` | 12 | One test per capability the brief asks a reviewer to exercise, plus scope enforcement, Unicode round-tripping and the zero-cost path |
| `tests/test_demo.py` | 12 | The demo as a deliverable: that every prepared example still behaves as its label claims, that a database with no schema is migrated rather than reported, that an unexpected failure arrives as JSON with a reason in it, that one observation reports one changed term, that the explorer is reachable, that the page calls nothing the API does not expose, that it loads no external resource, and - via `node --check` - that its embedded JavaScript actually parses |

The stress suite is run separately, because it takes seconds rather than
milliseconds:

    .venv/bin/python evals/stress/run.py

It measures the properties a hand-written case list cannot: corruption rate on
4,000 sentences of real English prose, fix rate on mishearings never seen
before, threshold sensitivity (plateau or knife-edge), messy-input robustness,
and latency at scale. Output goes to `evals/results/stress/report.json`.

## If something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `no Python 3.11+ found` | `make` could not find a suitable interpreter | `make install PY=/path/to/python3` |
| `the database has no schema` | a CLI command run before `make seed` - the server migrates itself, the CLI does not | `make seed` |
| `Address already in use` | something else holds port 8000 | `PORT=8001 make serve` |
| a banner across the top of the demo | a request failed; the server's own reason is quoted in it verbatim | follow what it says - it is the real error, not a guess |
| a dependency builds from source and fails | very new or very old interpreter | `make check-wheels` will say which one |
| `SARVAM_API_KEY is not set` | `make eval-live` without a key | use `make eval`; it needs no key |
