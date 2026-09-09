# language-memory-handler

Word-level phonetic memory for a dictation system. It learns the names, terms
and spellings that belong to one person, and conditions the formatting stage so
that future dictations come out the way that person writes - while doing nothing
at all when the evidence is weak, the context is wrong, or the word is just an
ordinary word.

    (asr_text, formatted_text, context) -> (memory_aware_text, adjudication)

The second half of that return value is not a debugging aid. Every call produces
an inspectable record of what was retrieved, which policies fired, what the
verdict was, and why - including the calls where nothing happened.

**Nothing in the pipeline touches audio.** The system consumes text a recogniser
has already produced. That is why the evaluation can be deterministic, and why
the system costs nothing on the majority of utterances.

---

## Run it

Three commands. Python 3.11–3.14 and nothing else - no Docker, no Node, no API
key, no network.

```bash
make install     # virtualenv + dependencies
make seed        # create the database and load a 24-term persona
make serve       # open http://127.0.0.1:8000
```

`make seed` is a convenience rather than a prerequisite: the server migrates and
seeds the database itself on the first request. If port 8000 is taken on your
machine, `PORT=8001 make serve` moves it; nothing else needs changing.

**What to do once it is open**, in about two minutes:

1. Press **Run** on what is already in the boxes - *"ask adith narayanan to
   review the pull request"*, as a recogniser would have produced it. Watch
   three lines appear: what the recogniser **produced**, what the formatter
   **made of it**, and what **memory** did - with the change highlighted.
   Underneath, every policy that had an opinion and the sentence it gave.
2. Press the prepared example **"the same word, ordinary sense"**. It says
   *"I ate a kiwi for breakfast"* and the system leaves it completely alone,
   because `kiwi` is an ordinary English word here. That abstention is the
   product.
3. Press **"a Slack handle, in Slack"**, then **"the same handle, in Mail"**.
   Same words, two answers.
4. In **Teach it**, record one correction and watch the confidence and state of
   that term move in the table below.
5. Press **Reset to the seeded persona** and do it again.
6. At the bottom, press **Open the case explorer here** - or the
   *1,926 evaluation cases* link in the header. Eight examples are an
   illustration; this is the evidence.

The same thing, from the command line:

```bash
make eval             # 69 specification cases + 15 learning cases, ~1 second
make eval-generated   # 1,842 derived cases, ~4 seconds, with the breakdown
make explore          # builds evals/results/explorer.html - open it
make test             # 150 tests
```

The explorer is the fastest way to judge this project, and it is served at
`/explorer` so you do not have to go looking for the file. One self-contained
page, two tabs: every hand-written case in full detail, and every derived case
filterable by family, script, confusion rule and pass/fail. Set the filter to
**failing only** - there are three, and they are all the same shape.

### Why there is no microphone

Recognition is upstream of this system and owned by the platform - in
production, Saaras. The demo's input is therefore the recogniser's *output*:
text, typed or loaded from a prepared case.

An earlier version of this demo bundled a local recogniser so a reviewer could
speak into the page, and it was the wrong trade. A small offline model is
inaccurate in ways that have nothing to do with this project, and every one of
those errors landed on the memory system: a mangled transcript made a correct
abstention look like a bug, and the thing under evaluation quietly became the
recogniser. Text in, text out, is also exactly the contract
[the evaluation](#the-evidence) measures - so what you see in the browser and
what the numbers describe are the same thing.

### If something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `no Python 3.11+ found` | `make` could not find a suitable interpreter | `make install PY=/path/to/python3` |
| `the database has no schema` | a CLI command run before seeding - the server does this itself | `make seed` |
| `Address already in use` | something else holds port 8000 | `PORT=8001 make serve` |
| A banner at the top of the demo | the server said what went wrong; it is quoted verbatim | follow what it says |
| A dependency builds from source and fails | very new or very old interpreter | `make check-wheels` says which |

[`RUN.md`](RUN.md) is the same thing in the numbered form the brief asks for,
with every environment variable and every output path.

---

## The evidence

| | |
|---|---|
| Hand-written specification cases | **68 / 69 (99%)** |
| Derived cases, four personas, ten scripts | **1,839 / 1,842 (99.8%)** |
| Learning cases (assertions about memory, not text) | **15 / 15** |
| **False interventions across 998 negative cases** | **0 (0.00%)** |
| Corruptions across 4,000 sentences of real English prose, 367-term memory | **0 (0.00%)** |
| Model calls in the entire evaluation | **0** |
| Median latency | **0.62 ms** |
| Tests | **150** |

The engine is entirely deterministic. A language model sits behind a port and is
used by the *formatting* stage; no decision about memory is delegated to one,
and every committed number was produced with no network access at all.

## Read these first

Three documents, and no more.

| Document | What it is |
|---|---|
| [`RUN.md`](RUN.md) | How to run it, in the brief's numbered form. Start here. |
| **[`REPORT.md`](REPORT.md)** | **The engineering report**: the product argument, the mechanism in full, the case taxonomy, the evaluation and what it does and does not establish, the decision log, eighteen bugs and how each was found, and everything that is still wrong |
| This file | What the product is, how it is built, what the numbers say, and where it stops |

If you read one thing, read `REPORT.md` §4 (why a dictionary is the wrong
answer), §8.4 (what a binding means, and the decision that got reversed) and §18
(the bugs, and what kind of looking found each one).

---

## What the product is

A person dictates. The recogniser hears *"ask adith narayanan to review the
kiwi rollout"*. Two of those words are wrong in a way no recogniser can fix,
because being right requires knowing this particular person: their colleague
spells it **Aadith**, and the product they work on is **Kivi**, not the fruit.

That is the whole problem. It is not spell-checking - every word is a real word.
It is not a dictionary - a dictionary would also rewrite *"I ate a kiwi for
breakfast"*, and a system that does that is worse than no system, because now
the user proofreads every sentence instead of one.

So the design is organised around the second half:

- **Doing nothing is a first-class outcome.** Three verdicts, not two: `APPLY`,
  `PROPOSE`, `ABSTAIN`. 998 of the 1,926 evaluation cases are ones where any
  intervention is a failure, and none of them fires.
- **Every decision states its reason**, both as a machine-readable code and as a
  sentence a person can read. An abstention is as inspectable as a change.
- **Evidence accumulates and decays.** Memory is not a table someone edited; it
  is a projection over an append-only log of observations, so it can be replayed
  to any point in time, explained back to its sources, and reset by truncation.

## Architecture, in three ideas

**1 · Memory is derived, never stored.** The authoritative state is an
append-only `Observation` log. Everything a reviewer sees - confidence, state,
variants, guards - is recomputed from it. Time-travel, provenance, clean reset
and a reproducible evaluation all fall out of this rather than needing machinery.

**2 · Confidence is a Beta posterior, not a counter.** `alpha` accumulates
supporting evidence, `beta` contradicting; the mean is the belief and
`alpha + beta - 2` is how much evidence stands behind it. A revert is ordinary
arithmetic rather than a special case, and decay (90-day half-life) makes an
unused memory *uncertain* rather than *wrong*.

**3 · A decision is a stack of independent policies.** Eleven of them, ordered,
each returning a signal (`SUPPORT` / `OPPOSE` / `VETO` / `NEUTRAL`), a weight, a
reason code and a rationale. No policy sees another's answer. This is why an
ablation is a configuration list rather than a code branch - and why every
number in the table below was produced without editing a line.

```
src/lmh/
  domain/      dataclasses and closed vocabularies. No I/O.
  ports/       Protocol definitions only. The swap surface.
  adapters/    phonetics, index, store, clock, llm, formatter
  engine/      text, projector, learner, policies, adjudicator, applier
  api/         FastAPI app, the demo page, and the case explorer
migrations/    hand-written Alembic revisions
evals/         fixtures, generators, three runners, committed results, explorer
```

Nothing in `engine/` imports an adapter - it receives one. Component selection
happens in `src/lmh/config.py` by dotted path or registry alias, so replacing the
phonetic encoder, the store, the index, the language model, the formatter or the
policy list is a configuration change rather than an edit. A
test asserts that every configurable name resolves *and* that the engine honours
it, because for a while one of them did not and every result file recorded a
component that had never run.

## Results

```
                              pass        useful  harmful   false intervention
full stack               68/69  (99%)         36        1                 0.0%
no co-occurrence         66/69  (96%)         34        2                 0.0%
no conflict              66/69  (96%)         36        1                 0.0%
no phonetic scoring      65/69  (94%)         35        1                 0.0%
no phonetics at all      57/69  (83%)         35        1                 0.0%
no guards                52/69  (75%)         28       11                21.9%
exact match only         41/69  (59%)         25       10                18.8%
```

Two rows carry the argument. **`no guards`** turns one harmful intervention into
eleven and puts the false-intervention rate above one negative case in five.
Guards are not a safety wrapper around the product; they *are* the product.
**`no phonetics at all`** - the encoder replaced with a null one, so retrieval
falls back to exact forms - costs 11 cases with no change in harm: that is the
measured value of generalising beyond the forms already on file, and it is
cleanly separable from the value of the guards.

Note that `no phonetic scoring` (removing the *policy*) costs 3 cases while
`no phonetics at all` (removing *retrieval*) costs 11. Reporting only the first
under the name "no phonetics" would have understated the stack by a factor of
three; both are listed under names that say which is which.

Reproduce any of them without touching code: `make ablations`.

## Two tiers, and why they are different sizes

**69 hand-written cases, and 1,842 derived ones.** They are not the same kind of
object and the sizes are deliberate.

The hand-written tier is a **specification**. Each case encodes a judgement
about what the product should do, was written before the engine existed (a test
enforces that), and is worth arguing about on its own. Writing three thousand of
those would not produce three thousand judgements - it would produce three
thousand copies of a dozen, and the number would mean nothing. Exactly one case
was added after the engine existed, and it is flagged as such.

The derived tier is a **measurement**. Every case is built mechanically from
committed inputs by `evals/gen/build.py`, and the property that makes it worth
anything is that **its expected outcome comes from the construction, not from
what the engine did**. A case that says *"take the canonical `Vaishnavi
Kulkarni`, apply the documented v→w confusion to get `waishnavi Kulkarni`, put
it in a carrier sentence in the app this term is actually bound to"* knows the
right answer before the engine is built. Generating inputs and recording the
engine's replies as the expectation would produce a suite that can never fail,
which is the usual way a large benchmark comes to mean nothing.

Twelve families, four personas - three with no hand-written guards at all, and
none of them the one the thresholds were tuned on - ten scripts:

```
                        n     pass   useful  missed  harmful
unseen_mishearing     306    99.0%      303       3        0
already_canonical     144   100.0%        0       0        0
indic_known_variant    84   100.0%       84       0        0
indic_unseen          115   100.0%      115       0        0
known_variant         305   100.0%      305       0        0
ordinary_prose        500   100.0%        0       0        0
ordinary_word_sense    60   100.0%        0       0        0
scope_carryover        66   100.0%       66       0        0
scope_mismatch          3   100.0%        0       0        0
script_shift           40   100.0%        0       0        0
unknown_name          120   100.0%        0       0        0
verbatim_region        99   100.0%        0       0        0
```

The three remaining failures are all the same shape: a term with a single weak
observation is `PROPOSE`d rather than applied. That is the threshold doing what
it is for, and it is left visible rather than tuned away.

**The tier paid for itself twice on its first run**, and neither finding was
reachable from 69 cases:

- Slicing by confusion rule showed `sh→s` passing 100% while `s→sh` passed 48%,
  and `ph` names failing across seven scripts at once. Both were holes in the
  romanisation fold: nothing collapsed `p`/`ph`/`f`, and `y→i` only fired after
  a consonant - which is not where `y` sits in *Iyer*, *Iyengar* or
  *Yashodhara*. Fixing them moved the derived tier from 92.8% to 99.5%.
- Slicing by script showed every remaining Indic failure was one letter: ब/व.
  That confusion was modelled as a Bengali peculiarity; it is universal. It also
  exposed that alternate readings were all-or-nothing, so a word with two
  ambiguous letters (*वैष्णवी*, *వెంకటేశ్వర్లు*) could never match its own
  mishearing. Readings are now emitted per combination, capped.

It also found two bugs in **itself**, which is worth saying plainly: the first
run reported eleven harmful interventions that were entirely the generator's
fault - it assigned applications round-robin and demanded that app-bound terms
be corrected in the wrong app. The engine was right and the fixture was wrong.
The fix turned that mistake into a real family. A generated expectation is only
worth something if the generator models the same rules the system does.

That cuts both ways, and the third finding is the one worth reading. A year's
worth of generated agreement is worth nothing if the generator inherited the
system's mistake: 69 of those cases asserted that an app-bound term must never be
corrected in another application, which is right for a Slack channel and wrong
for a person's name. Nothing automated could have found it, because the fixture
and the engine held the same wrong belief. Somebody using the demo found it in a
sentence. The rule, the argument and the two families it split into are in
[`REPORT.md`](REPORT.md) §8.4.

Separately, `make stress` measures what a hand-written case list cannot:

```
corruptions on 4,000 sentences of real English prose      0  (0.00%)
mishearings never seen before, fixed automatically     87.2%
mishearings never seen before, corrupted                2.1%
false fires on three unseen personas (24/104/367 terms)   0  (0.00%)
throughput                                            2,547 sentences/sec
```

Two classes in the taxonomy - `sound_alike_common_word` and
`sound_alike_common_phrase` - exist **because** of that suite. Running a
367-term memory over real prose found that a memory for the acronym `WER` was
rewriting the word *"were"*, and that `Ishaan` was rewriting the phrase *"is
an"* - between them, every false positive the system had. No amount of thinking
up cases produced either one.

## Indian languages

Memory works in native Indic script, not only in romanisation. Nine
ISCII-aligned Unicode blocks - Devanagari, Bengali, Gurmukhi, Gujarati, Odia,
Tamil, Telugu, Kannada, Malayalam - are transliterated to a Latin phonetic form
and then go through exactly the same fold, blocking index and policy stack as
English. There is no separate Indic pipeline to keep in sync.

All nine are measured, not asserted. 199 derived cases run against a
native-script persona of 42 real names, with mishearings produced by confusion
rules expressed as *offsets from a block base* - the same ISCII alignment the
encoder is built on, so one rule ("an aspirated consonant is heard as its plain
counterpart") applies in every script at once:

| | | | |
|---|---|---|---|
| मीरा शर्मा → मिरा शर्मा | vowel length | ਹਰਪ੍ਰੀਤ ਸਿੰਘ → ਹਰਫ੍ਰੀਤ ਸਿੰਘ | p/ph |
| সুদীপ্ত মুখার্জি → সুধীপ্ত মুখার্জি | aspiration | ପଣ୍ଡା → ଫଣ୍ଡା | p/ph |
| વૈષ્ણવી → બૈષ્ણવી | b/v merger | வெங்கடேசன் → வெங்கதேசன் | retroflex/dental |
| వెంకటేశ్వర్లు → బెంకటేశ్వర్లు | b/v merger | ಶ್ವೇತಾ → ಸ್ವೇತಾ | sibilant |

Where a script does not have a distinction, the rule simply does not fire:
Tamil has no aspirate series, so its cases exercise vowel length and sibilants
instead. The generator refuses to emit an unassigned code point, which it did
until that was caught - producing "letters" no font renders and no person could
have typed.

Cross-script *retrieval* is allowed (Devanagari text can match a Latin-canonical
memory) but cross-script *rewriting* is vetoed (`ScriptFitPolicy`, reason
`SCRIPT_MISMATCH`): correcting someone's spelling is the job, silently changing
the alphabet they chose to write in is not. Alternate readings are capped at
three ambiguous letters per word - beyond that the blocking bucket grows faster
than the recall it buys.

## Decisions

Twenty-six numbered decisions, with their alternatives and their costs, are in
[`REPORT.md`](REPORT.md) §21. The ones that shape everything else:

- **Evidence is an append-only log; memory is a projection over it.** Mutating
  memory rows is simpler and loses per-case memory state, provenance, a clean
  reset and a reproducible evaluation - four things the brief asks for by name.
- **Memory conditions the formatting prompt; substitution is only the fast
  path.** Forced by standing instructions: *"always lowercase, even
  sentence-initial"* cannot be executed by any replace table.
- **Confidence is a Beta posterior, not a count**, so a revert is ordinary
  arithmetic and decay makes an old memory uncertain rather than wrong.
- **Guards are synthesised from the memory, not written by the user.** A person
  does not curate a list of words their dictation tool should be careful with.
- **Cases before engine**, enforced by a test that caps post-hoc additions at
  20% of the suite. It currently sits at 13%.

Four decisions were **reversed by evidence rather than by argument**, and those
are the ones worth reading: scope-split evidence (D-010), the phonetics ablation
that was weaker than its name (D-017), seeded confidence being a prior rather
than a value (D-018), and what a binding actually means (D-026). Three of the
four were found by using the demo rather than by running the evaluation.

## Limitations

Stated plainly, because the interesting ones are design decisions rather than
bugs.

- **A8-002 fails, and is committed failing.** A conditional standing instruction
  - *expand `ZDR` to "Zero-data retention (ZDR)" on first use in email, keep it
  abbreviated in chat* - cannot be executed by a deterministic replace stage; it
  needs the formatting model to act on the instruction. Passing it would mean
  either hard-coding the case or turning on a model call the rest of the
  evaluation does not use. It is left visible instead.
- **One canonical form per lexeme.** If the user writes a name in Devanagari and
  memory holds it in Latin, the system declines rather than converting. A
  per-script canonical is a schema change, not an architecture one.
- **No speaker diarisation, no multi-speaker context.** Kivi is single-user
  dictation and the design assumes it.
- **Scripts outside the nine Indic blocks** - Arabic (Urdu), Ol Chiki, Meetei
  Mayek - are not handled. The encoder abstains rather than guessing.
- **Numeric and unit formatting** (*"two crore"* → *"₹2 Cr"*) is classified only
  so the system can refuse it. That is the formatter's job, not memory's.
- **The API is a single-process, single-user surface.** That is the honest model
  for personal memory; adding locking would imply a concurrency story the design
  does not have.
- **The live model path is implemented but lightly exercised.** `make eval` and
  every committed number are offline; `SarvamModel` and the cassette recorder
  exist and are tested for construction and replay, not against a long live run.
- **A binding is a two-way classification, and the real signal is richer.** Out
  of scope vetoes for app-native terms (a channel, a service identifier) and is
  merely neutral for everything else. How *many* applications a term has been
  corrected in, and whether the user ever said where it belongs, are better
  evidence and are not used. `REPORT.md` §8.4.
- **Ten of ninety-four held-out mishearings are missed and two are corrupted.**
  Widening the fold trades the first against the second. The trade is positioned,
  not solved.
- **Recognition is upstream and not measured.** The mishearings in the
  evaluation are generated from documented confusion rules, not harvested from a
  recogniser. The rules are defensible; the distribution is a model.

## Configuration and secrets

No environment variable is required to run anything here - the demo, the
evaluation and the tests all default to offline components.

To run against the live Sarvam model, copy `.env.example` to `.env` and set
`SARVAM_API_KEY`. **`.env` is gitignored and must never be committed**;
`.env.example` documents every variable with empty values. `.env` is read
automatically at startup when present, and the key is never logged, never
written to a cassette, and never included in an evaluation result. No credential
appears anywhere in this repository.

## AI use

This project was designed and built with substantial assistance from a large
language model, used throughout for architecture review, fixture authoring,
stress-data generation and code generation. The design decisions, the taxonomy
and the evaluation methodology are the author's; the model was used to
pressure-test them and to write. Specific uses are recorded in
[`REPORT.md`](REPORT.md) §21.

Two research notes, for completeness:

- **Client inspection.** The publicly downloadable Kivi Windows installer was
  unpacked and its bundled application resources were read, to check what the
  shipping product's dictionary and correction behaviour actually looks like
  before designing against assumptions. No account was used, no service was
  called, nothing was modified or redistributed, and no code from it appears
  here. It informed the taxonomy - chiefly the observation that scope binding is
  per-application - and nothing else.
- **The stress corpus is synthetic-but-real.** The 4,000 neutral sentences are
  harvested from Python standard-library docstrings, not generated by a model,
  precisely so that "no false positives on real prose" is a claim about prose
  the author did not write.

---

## Licence

**None. All rights reserved.**

This repository is a submission for the Sarvam AI "The Words Kivi Keeps"
assignment. It is provided for evaluation by the recipient only. No permission
is granted to copy, modify, redistribute, or use this code or its evaluation
data for any other purpose.

Third-party dependencies keep their own licences and are not vendored here.
