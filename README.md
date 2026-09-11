# phonetic-speech-memory

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

Every example runs against one persona: an engineer with colleagues, internal
services and jargon of their own, working on a dictation product. The people are
invented. The persona is a single committed JSON file, so you can read every
term the system knows and swap the lot for your own.

---

## Run it

Python 3.11-3.14 and nothing else: no Docker, no Node, no API key, no network.

```bash
make install     # virtualenv + dependencies
make seed        # create the database and load a 24-term persona
make serve       # open http://127.0.0.1:8000
make eval        # the evaluation, offline, about a second
```

[`RUN.md`](RUN.md) is the review procedure in full: every environment variable,
every command, what to click, where results are written, how to reset, and what
to do when something goes wrong. Nothing about running this is repeated here.

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
| Median latency | **0.67 ms** |
| Tests | **157** |

The engine is entirely deterministic. A language model sits behind a port and is
used by the *formatting* stage; no decision about memory is delegated to one,
and every committed number was produced with no network access at all.

## Read these first

Three documents, and no more.

| Document | What it is |
|---|---|
| [`RUN.md`](RUN.md) | How to run it, in the brief's numbered form. Start here. |
| **[`REPORT.md`](REPORT.md)** | **The engineering report**: the product argument, the mechanism in full, the case taxonomy, the evaluation and what it does and does not establish, the decision log, twenty bugs and how each was found, and everything that is still wrong |
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
src/psm/
  domain/      dataclasses and closed vocabularies. No I/O.
  ports/       Protocol definitions only. The swap surface.
  adapters/    phonetics, index, store, clock, llm, formatter
  engine/      text, projector, learner, policies, adjudicator, applier
  api/         FastAPI app, the demo page, and the case explorer
migrations/    hand-written Alembic revisions
evals/         fixtures, generators, three runners, committed results, explorer
```

Nothing in `engine/` imports an adapter - it receives one. Component selection
happens in `src/psm/config.py` by dotted path or registry alias, so replacing the
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

**The two tiers are different kinds of object, and the sizes are deliberate.**
The 69 hand-written cases are a *specification*: each one is a judgement about
what the product should do, written before the engine existed, and a test caps
post-hoc additions at 20% of the suite. The 1,842 derived cases are a
*measurement*, built mechanically from committed inputs, and the property that
makes them worth anything is that every expected outcome comes from the
construction rather than from what the engine did - the alternative, recording
the engine's replies as the expectation, is how a large benchmark comes to mean
nothing. They are reported separately, always, because averaging them would let
1,842 easy cases drown out 69 hard ones. `REPORT.md` §14 has both in full,
including the twelve families and what each one varies.

`make stress` measures what a case list structurally cannot: 4,000 sentences of
real English prose the author did not write, three personas the thresholds were
never tuned on, threshold sweeps, messy input, and 94 held-out mishearings. Two
taxonomy classes exist only because it found them.

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
- **No speaker diarisation, no multi-speaker context.** The design assumes
  single-user dictation.
- **Scripts outside the nine Indic blocks** - Arabic (Urdu), Ol Chiki, Meetei
  Mayek - are not handled. The encoder abstains rather than guessing.
- **Numeric and unit formatting** (*"two crore"* → *"₹2 Cr"*) is classified only
  so the system can refuse it. That is the formatter's job, not memory's.
- **The API is a single-process, single-user surface.** That is the right model
  for personal memory; adding locking would imply a concurrency story the design
  does not have.
- **The live model path has never met a real model.** Every committed number is
  offline. The whole chain is driven end to end by `tests/test_live_path.py`
  against a stub OpenAI-compatible endpoint on localhost, so the request, the
  memory-conditioned prompt, the verifier and the failure paths are all covered
  - but whether a real model writes good prose, and how often it overreaches,
  are unmeasured.
- **A binding is a two-way classification, and the real signal is richer.** Out
  of scope vetoes for app-native terms (a channel, a service identifier) and is
  merely neutral for everything else. How *many* applications a term has been
  corrected in, and whether the user ever said where it belongs, are better
  evidence and are not used. `REPORT.md` §8.4.
- **Ten of ninety-four held-out mishearings are missed and two do not come out
  exactly canonical.** Widening the fold trades the first against the second.
  The trade is positioned, not solved. `REPORT.md` §20.
- **Recognition is upstream and not measured.** The mishearings in the
  evaluation are generated from documented confusion rules, not harvested from a
  recogniser. The rules are defensible; the distribution is a model.

## AI use

This project was designed and built with substantial assistance from LLM agents, used for architecture review, fixture authoring,
stress-test data generation and coding. The design decisions, the taxonomy and the evaluation methodology are mine; the agent was used to
pressure-test ideas and to write, draft elements and organize the repository structure. Specific uses are recorded in
[`REPORT.md`](REPORT.md).

Two research notes, for completeness:

- **Client inspection.** A shipping dictation client .exe was unpacked from its
  public installer and its bundled application resources read, to see what a
  real product's dictionary and correction behaviour looks like before
  designing against assumptions. No account was used, no service was called,
  nothing was modified or redistributed, and no code from it appears here. It
  informed the taxonomy - chiefly the observation that scope binding is
  per-application - and nothing else.

---

## Licence

**None. All rights reserved.**

This repository was written as a take-home submission and is published for
reading. No permission is granted to copy, modify, redistribute, or use this
code or its evaluation data for any other purpose.

Third-party dependencies keep their own licences and are not vendored here.
