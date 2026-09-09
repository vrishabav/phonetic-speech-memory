# Phonetic speech memory - engineering report

A dictation system produces text that is phonetically right and
orthographically wrong. `phonetic-speech-memory` is the stage that sits between
such a system's formatter and the text it inserts, and decides - for this user,
in this sentence, in this application - whether a word needs to be spelled
differently. Most of the time it decides that nothing does.

The examples throughout run against one persona: an engineer with colleagues,
internal services and jargon of their own, working on a dictation product. The
person and everyone around them are invented; the product and company names are
the ones this was designed against, and are used only as the vocabulary a
plausible user would have. The whole persona is one committed JSON file -
readable in full, and replaceable with somebody else's.

This is the long-form version of the submission: the product argument, the
mechanism, the evaluation and what it does and does not establish, the decisions
that were reversed by evidence, and the places the system is still wrong.
`README.md` is the short version; `RUN.md` is the procedure for running it.
Every claim names the command that reproduces it, and where a number here
disagrees with that command, the number here is wrong.

---

## Contents

**Part I - the problem**
1. [What dictation software actually does](#1-what-dictation-software-actually-does)
2. [The failure this project fixes](#2-the-failure-this-project-fixes)
3. [Why it cannot be fixed further upstream](#3-why-it-cannot-be-fixed-further-upstream)
4. [Why a dictionary is the wrong answer](#4-why-a-dictionary-is-the-wrong-answer)

**Part II - vocabulary**

5. [Every term, defined](#5-every-term-defined)

**Part III - the machine**

6. [The complete flowchart, input to output](#6-the-complete-flowchart-input-to-output)
7. [One sentence, followed all the way through](#7-one-sentence-followed-all-the-way-through)
8. [The four ideas the design rests on](#8-the-four-ideas-the-design-rests-on)
9. [Phonetics from first principles](#9-phonetics-from-first-principles)
10. [How it learns](#10-how-it-learns)

**Part IV - the code**

11. [Every file, and what it does](#11-every-file-and-what-it-does)
12. [Configuration and swapping parts](#12-configuration-and-swapping-parts)
13. [The demonstration app](#13-the-demonstration-app)

**Part V - the evidence**

14. [The evaluation: three tiers and what each proves](#14-the-evaluation-three-tiers-and-what-each-proves)
15. [The stress suite](#15-the-stress-suite)
16. [The tests](#16-the-tests)
17. [Every number, and what it means](#17-every-number-and-what-it-means)

**Part VI - what went wrong**

18. [Bugs found, and how each was found](#18-bugs-found-and-how-each-was-found)
19. [Changes made to test cases, and why](#19-changes-made-to-test-cases-and-why)
20. [What is not true yet](#20-what-is-not-true-yet)
21. [Decision log](#21-decision-log)
22. [Reproducing the numbers](#22-reproducing-the-numbers)

---

# Part I - the problem

## 1. What dictation software actually does

You speak. Software types. Between those two things are **two separate stages**,
and keeping them separate is the single most important idea for understanding
this project.

**Stage one: the recogniser (ASR).** Sound in, words out - a transcript of
sounds, not a piece of writing:

```
    ask adith narayanan to review the pull request before friday
```

**Stage two: the formatter.** A language model that turns that transcript into
something a person would send. It never hears the audio; it only sees the
recogniser's words:

```
    Ask Adith Narayanan to review the pull request before Friday.
```

**This project is a third stage, after both.** It receives the raw recogniser
output *and* the formatted text, and returns a corrected version of the
formatted text together with the complete reasoning behind every change it made
and every change it declined to make. It never touches audio.

That boundary buys three things:

- the system can be evaluated **deterministically**, because text in produces
  text out with no microphone and no randomness;
- it can be developed and tested with **no GPU and no audio data**;
- it is **cheap**, because most utterances need nothing from it at all - 71% of
  real prose never gets past the first stage of the pipeline.

## 2. The failure this project fixes

Here is what actually goes wrong. A person dictates:

> "ask adith narayanan to review the kiwi rollout"

Two of those words are wrong, and no amount of better listening will fix either.

**The colleague's name is spelled `Aadith`, with two a's.** The recogniser heard
the sound correctly. "Adith" and "Aadith" are pronounced identically. There is
no acoustic information that distinguishes them - the distinction lives entirely
in how one particular person spells one particular name.

**The product is called `Kivi`, not `kiwi`.** Here the failure is worse, because
"kiwi" is a perfectly good English word. The recogniser heard a real word,
produced a real word, and was wrong - because this speaker works on a product
whose name happens to sound like a fruit.

Both errors share a shape: **being right requires knowing this specific person.**
Not English, not the world - *this user's colleagues, this user's products, this
user's habits.*

That is what "memory" means here. It is not a chat history. It is a small,
personal, evidence-backed store of the words that belong to one individual.

## 3. Why it cannot be fixed further upstream

A reasonable first reaction is: fix the recogniser, give it the user's contact
list. That fails for three reasons, and they shape the whole design.

**The information is not in the audio.** "Adith" and "Aadith" are the same
sound. A perfect recogniser - one that made zero acoustic errors - would still
have to guess. Adding a better model does not help, because the problem is not
acoustic.

**Biasing a recogniser toward a word list is dangerous.** You can push an ASR
system to favour certain words (this is called contextual biasing or hotword
boosting). But it applies to the whole utterance and it has no notion of sense:
bias it toward "Kivi" and it will produce "Kivi" when the person means the
fruit. You have traded a rare error for a frequent one.

**The formatter cannot fix it either.** The formatter is a language model doing
style. It has no idea who Aadith is. If you put the whole contact list in its
prompt, you get the same over-correction problem plus a much larger bill.

**So the fix has to be a separate stage that can be conservative.** Something
that looks at the specific words in the specific sentence, decides whether there
is *evidence* that this particular user means their particular term, and - most
of the time - decides that there is not.

## 4. Why a dictionary is the wrong answer

The obvious implementation is a find-and-replace table: `kiwi → Kivi`,
`adith → Aadith`. Every dictation product ships something like it. It is wrong,
and understanding exactly why is understanding this project.

Consider one user with `Kivi` in their dictionary, and four sentences:

| They said | A dictionary does | The right answer |
|---|---|---|
| "the **Kiwi** service is dropping requests" | Kivi ✓ | Kivi ✓ |
| "I ate a **kiwi** for breakfast" | Kivi ✗ | **kiwi** - leave it alone |
| "she wrote, '**kiwi** approved it'" | Kivi ✗ | **kiwi** - those are her words |
| "the **kiwi** export tariff" | Kivi ✗ | **kiwi** - nothing to do with the product |

The dictionary gets one right out of four, and the three it gets wrong are
worse than doing nothing at all. A system that silently corrupts one sentence in
four forces the user to proofread **every** sentence - which is more work than
fixing the occasional name by hand.

This produces the central design commitment:

> **Doing nothing is a first-class outcome, and most of the engineering is in
> deciding when to do nothing.**

Which is why the system has three possible answers rather than two, why every
answer carries a reason, and why **998 of the 1,926 evaluation cases are cases
where any intervention is a failure**.

---

# Part II - vocabulary

## 5. Every term, defined

Used throughout the rest of this document and throughout the code, grouped by
what they describe.

### 5.1 The input

**Utterance** - one dictation, as this system receives it. It carries:

| Field | Meaning |
|---|---|
| `asr_text` | what the recogniser produced, raw |
| `formatted_text` | what the formatter made of it |
| `app` | which application is being dictated into, e.g. `com.tinyspeck.slackmacgap` |
| `persona` | an optional named context ("work", "personal") |
| `surrounding_text` | text visible on screen around the cursor, if the client can see it |

Code: `src/psm/domain/models.py`, class `Utterance`.

**Span** - a slice of text identified by character offsets, plus the text
itself: `(start, end, text)`. Character offsets rather than word indices,
because a replacement has to be spliced back into the original string with its
original punctuation intact.

**N-gram span** - every run of 1 to N consecutive words, as spans. "ask adith
narayanan" yields `ask`, `adith`, `narayanan`, `ask adith`, `adith narayanan`,
`ask adith narayanan`. This is how the system finds multi-word names without
knowing in advance where they start.

### 5.2 What is remembered

**Lexeme** - one remembered term. Not "a word": a *thing the user has a name
for*. `Aadith Narayanan` is one lexeme. `#eng-asr` is one lexeme. `theek hai`
is one lexeme. Each has:

| Field | Meaning |
|---|---|
| `canonical` | the correct form - what we would write |
| `kind` | person, org, product, place, term, code_symbol, handle, phrase |
| `variants` | forms that have stood in for it (see below) |
| `guards` | conditions under which it must **not** be applied |
| `bindings` | where it applies (see scope) |
| `instruction` | a standing rule in the user's own words, if any |
| `confidence` | how much we believe it (see below) |
| `state` | proposed / active / dormant / suppressed / retired |
| `prior` | evidence that predates the log (see §8.2) |

Code: `src/psm/domain/models.py`, class `Lexeme`.

**Variant** - a wrong form that has stood in for the canonical one. `adith
narayanan` is a variant of `Aadith Narayanan`. Every variant has a
**provenance**, and provenance is ranked, because where a form came from is
evidence about how much to trust it:

| Provenance | Meaning | Strength |
|---|---|---|
| `observed` | a recogniser actually produced this | strongest: it is grounded in something that happened |
| `declared` | the user told us | strong, but never verified in the wild |
| `generated` | we derived it phonetically ourselves | weakest - it is our guess and needs support |

That ranking is load-bearing: a guard later in the system refuses to correct an
ordinary English word unless the form was `observed`. "The recogniser has done
this six times" is a fact; "this could sound similar" is not.

**Guard** - a condition under which a lexeme must not be applied, even when it
matches. Six kinds:

| Guard | Fires when |
|---|---|
| `common_word` | the surface form is also an ordinary English word |
| `lexical_context` | certain tokens appear nearby |
| `semantic_context` | a model judges the sense wrong (not used in committed runs) |
| `scope` | outside a binding |
| `verbatim` | inside quotes or a code fence |
| `user_suppression` | created automatically after repeated reverts |

**Binding / scope** - the context a lexeme, or a piece of evidence about it,
belongs to. Three levels: `global` (anywhere), `app` (one application),
`persona` (one named context). A binding records **where evidence arrived**;
what may be concluded from that depends on the term. `#eng-asr` names a channel
that exists in Slack and nowhere else, so it must not travel; a person's name is
spelled the same way in every window. §8.4 is that argument in full.

**Tombstone** - a record that a lexeme was deleted or renamed. Deletion marks
the entry rather than removing it, keeping the old surface forms, so that
re-seeing a deleted term does not silently recreate what the user asked to
forget and a renamed term's old spelling still resolves to the new one.

### 5.3 What is learned from

**Observation** - one immutable piece of evidence. This is the **only** input to
memory; nothing else writes it. Fields:

| Field | Meaning |
|---|---|
| `source` | where it came from (below) |
| `before` / `after` | the two forms in play |
| `polarity` | `supports` or `contradicts` |
| `binding` | the scope it happened in |
| `at` | when |
| `accepted` | whether the learner judged it real evidence |

Eight sources, each with a default weight, because a user typing a term into a
dictionary is much stronger evidence than the term appearing on screen:

| Source | Meaning | Weight |
|---|---|---|
| `declared` | the user added the term explicitly | 3.0 |
| `instruction` | a spoken or typed rule about a term | 3.0 |
| `revert` | the user undid one of our corrections | 2.0 (negative) |
| `post_edit` | the user edited inserted text in place | 1.0 |
| `import` | migrated from an external dictionary | 1.0 |
| `dismissal` | the user declined a proposal | 1.0 (negative) |
| `repetition` | the term recurred in the user's own writing | 0.5 |
| `ambient` | the term was read from surrounding screen text | 0.25 |

**Polarity** - whether an observation supports the term or contradicts it. A
revert is a contradiction: the user saw our correction and undid it.

### 5.4 Belief

**Confidence** - how much the system believes a lexeme should be applied when it
matches. Not a counter: a **Beta posterior**, described fully in §8.2. Two
numbers:

- `alpha` = 1 + the sum of decayed weights of supporting observations
- `beta` = 1 + the sum of decayed weights of contradicting observations
- **confidence** (the belief) = `alpha / (alpha + beta)`
- **strength** (how much evidence backs it) = `alpha + beta - 2`

They are different questions. A term seen once with no contradiction has
confidence 0.67 and strength 1; a term seen eight times has confidence 0.90 and
strength 8. Only the second should act on its own.

**Decay** - evidence loses weight with age, exponentially, with a **90-day
half-life**: evidence is worth half as much after three months. `decay =
exp(-ln2 × age_days / 90)`.

**State** - derived from confidence, strength and recency. Never stored
independently; recomputed every time:

| State | Meaning | Condition |
|---|---|---|
| `proposed` | known, not yet trusted enough to apply | below activation threshold |
| `active` | applied when matched | confidence ≥ 0.60 **and** strength ≥ 1.5 |
| `dormant` | decayed; applies only with contextual support | confidence < 0.35, or unused long enough that decay < 0.25 |
| `suppressed` | a suppression guard is in force | two reverts in one scope |
| `retired` | tombstoned | the user deleted it |

### 5.5 Deciding

**Candidate** - a possible match: *this span of text* might be *this lexeme*,
found *this way*, with *this retrieval score*. Retrieval produces candidates;
it does not decide anything.

**Matched via** - how the candidate was found: `observed_variant`,
`declared_variant`, `generated_variant`, `canonical`, or `phonetic`. Exact form
matches score 1.00; phonetic matches score `1 − distance`.

**Policy** - one independent rule that has an opinion about one candidate. There
are eleven. Each returns:

| Part | Meaning |
|---|---|
| `signal` | `SUPPORT`, `OPPOSE`, `VETO` or `NEUTRAL` |
| `weight` | a signed number, ignored when the signal is VETO |
| `reason` | a machine-readable code |
| `rationale` | one sentence a human can read |

A **VETO** blocks the candidate regardless of every other signal. No policy can
see any other policy's answer - that independence is what makes an ablation a
configuration change rather than a code change.

**Verdict** - one of three:

| Verdict | Meaning |
|---|---|
| `APPLY` | change the text |
| `PROPOSE` | surface a suggestion, change nothing |
| `ABSTAIN` | do nothing, and record why |

**Reason code** - why a verdict was reached, from a closed vocabulary of 25
values (`exact_observed_variant`, `common_word_guard`, `script_mismatch`, …).
Every case in the evaluation asserts a reason code as well as an output, so a
case cannot pass for the wrong cause.

**Resolution** - the decision about one candidate: verdict, score, reason code,
every policy's outcome, and the replacement if any.

**Adjudication** - the complete record of one call: the utterance, the output
text, every resolution, whether the gate opened, cost, and timestamp. Written
for **every** utterance, including the ones where nothing happened.

The next section is the same objects in the order the code produces them: an
`Utterance` arrives, the index turns spans into `Candidate`s, the policy stack
turns each candidate into a `Resolution`, and the whole call is written down as
one `Adjudication`.

---

# Part III - the machine

## 6. The complete flowchart, input to output

Section 5 defined the pieces; this is the order they actually run in, with the
two paths kept apart because they are triggered by different things.

**The application path** turns one utterance into one answer. It is a funnel:
six stages, each more expensive than the one before it, and the first three can
end the call outright. The rail down the right-hand side is that early exit, and
it is the common case rather than the exception. Every stage that ends the call
still reaches `[5] RECORD`, because an abstention with a reason is a decision and
has to be as inspectable as a change.

**The learning path** is separate, runs on a different trigger, and is the only
thing that writes to memory. Nothing in the application path does.

Two conventions in the diagram: everything above the double line is upstream and
not part of this repository, and the bracketed numbers `[0]`..`[5]` and
`[L1]`..`[L5]` are the stage names used everywhere else in this report and in
the code.

```
 ┌──────────┐
 │   USER   │  speaks: "ask adith narayanan to review the kiwi rollout"
 └────┬─────┘
      │ audio
      v
 ┌────────────────────────────────────────────────────────────────────┐
 │ ASR  -  speech recognition                           NOT THIS REPO │
 │ (Saaras in production; its output is where this system begins)     │
 └────┬───────────────────────────────────────────────────────────────┘
      │ asr_text: "ask adith narayanan to review the kiwi rollout"
      v
 ┌────────────────────────────────────────────────────────────────────┐
 │ FORMATTER  -  a port, so it can be frozen for evaluation           │
 │                                                                    │
 │ conditioned on memory: for every ACTIVE / PROPOSED / DORMANT term  │
 │ bound to this app, the prompt is given                             │
 │     - the canonical form, and the forms it has been heard as       │
 │     - any standing instruction, in the user's own words            │
 │                                                                    │
 │ the only stage that can execute an instruction such as             │
 │ "never write 'Sarvam AI' mid-sentence": that is a rule about       │
 │ how to write, which no substitution engine can carry out           │
 │                                                                    │
 │ adapters: passthrough (evaluation) | llm_formatter (live)          │
 └────┬───────────────────────────────────────────────────────────────┘
      │ formatted_text: "Ask Adith Narayanan to review the Kiwi rollout."
      │
══════╪══════════ phonetic-speech-memory starts here ════════════════════
      v
 ┌────────────────────────────────────────────────────────────────────┐
 │ [0] GATE             index.probe(formatted_text)                   │
 │                                                                    │
 │   build every 1..N word span; for each, two cheap questions:       │
 │     - is its normalised form an exact key in the index?            │
 │     - do any of its phonetic keys exist in the index?              │
 │                                                                    │
 │   no, for every span: return the input unchanged, 0 candidates,    ├──┐
 │   0 model calls, ~0.3 ms. 71% of real English prose exits here.    │  │
 └────┬───────────────────────────────────────────────────────────────┘  │
      │ at least one span matched                                        │
      v                                                                  │
 ┌────────────────────────────────────────────────────────────────────┐  │
 │ [1] RETRIEVE         index.search(utterance, binding)              │  │
 │                                                                    │  │
 │   for each n-gram span, cheapest path first:                       │  │
 │                                                                    │  │
 │   a. EXACT      normalise(span) in the exact-form map              │  │
 │                 -> Candidate(score 1.00, matched_via .._variant)   │  │
 │                                                                    │  │
 │   b. PHONETIC   only for spans that did not match exactly:         │  │
 │                 keys = metaphone( fold( readings(span) ) )         │  │
 │                 any lexeme sharing a key becomes a candidate,      │  │
 │                 scored by BlendedComparator:                       │  │
 │                    0.40 x metaphone-key Jaccard                    │  │
 │                  + 0.35 x Jaro-Winkler                             │  │
 │                  + 0.25 x normalised indel distance                │  │
 │                 kept only if distance <= 0.34                      │  │
 │                                                                    │  │
 │   c. DOMINANCE  drop any span beaten by a better one for the       │  │
 │                 SAME lexeme; score first, length as tiebreak       │  │
 │                                                                    │  │
 │   no candidate survives: return the input unchanged                ├──┤
 └────┬───────────────────────────────────────────────────────────────┘  │
      │ up to 8 candidates, best first                                   │
      v                                                                  │
 ┌────────────────────────────────────────────────────────────────────┐  │
 │ [2] ADJUDICATE       one pass of the policy stack per candidate    │  │
 │                                                                    │  │
 │   ordered cheap-and-decisive first, so a veto short-circuits.      │  │
 │   each policy sees only the candidate and the context.             │  │
 │                                                                    │  │
 │    #  policy             fires when                       signal   │  │
 │    1  suppression        the user already said no         VETO     │  │
 │    2  verbatim           inside quotes or code            VETO     │  │
 │    3  already_canonical  the text is already right        VETO     │  │
 │    4  script_fit         Devanagari in, Latin out         VETO     │  │
 │    5  scope_fit          an app-native term, elsewhere    VETO     │  │
 │    6  exact_variant      a form really produced           SUPPORT  │  │
 │    7  phonetic           a form that sounds right         SUPPORT  │  │
 │    8  common_word_guard  the surface is an ordinary word  VETO     │  │
 │    9  cooccurrence       terms learned together           SUPPORT  │  │
 │   10  conflict           two memories, one sound          VETO     │  │
 │   11  recency            a decayed memory, unsupported    OPPOSE   │  │
 │                                                                    │  │
 │   weights: exact_variant +0.62, phonetic +0.30 to +0.65,           │  │
 │   cooccurrence up to +0.25, scope_fit +0.18, recency negative      │  │
 │                                                                    │  │
 │   score = sum of the signed weights                                │  │
 │                                                                    │  │
 │      any VETO         ─────────────────────────────►  ABSTAIN      │  │
 │      score >= 0.55    ─────────────────────────────►  APPLY        │  │
 │      score >= 0.30    ─────────────────────────────►  PROPOSE      │  │
 │      otherwise        ─────────────────────────────►  ABSTAIN      │  │
 │                                                                    │  │
 │   every policy's signal, weight, reason code and rationale is      │  │
 │   kept, for abstentions exactly as much as for changes             ├──┤
 └────┬───────────────────────────────────────────────────────────────┘  │
      │ at least one APPLY                                               │
      v                                                                  │
 ┌────────────────────────────────────────────────────────────────────┐  │
 │ [3] APPLY            splice accepted replacements                  │  │
 │                                                                    │  │
 │   - right-to-left, so earlier offsets stay valid                   │  │
 │   - longest span first, so "Shreyaa Bhattacharya" beats "Shreya"   │  │
 │   - overlapping spans: the first one placed wins                   │  │
 │   - casing carried from the source, unless an instruction locks    │  │
 │     it ("always lowercase, even sentence-initial")                 │  │
 └────┬───────────────────────────────────────────────────────────────┘  │
      │                                                                  │
      v                                                                  │
 ┌────────────────────────────────────────────────────────────────────┐  │
 │ [4] VERIFY           live formatter only                           │  │
 │                                                                    │  │
 │   token-level edit distance against the unconditioned text.        │  │
 │   a result that changed more than it was licensed to is            │  │
 │   rejected, and the deterministic output stands.                   │  │
 └────┬───────────────────────────────────────────────────────────────┘  │
      │                                                                  │
      v                                                                  │
 ┌────────────────────────────────────────────────────────────────────┐  │
 │ [5] RECORD           one Adjudication row, ALWAYS                  │◄─┘
 │                                                                    │
 │   including the calls where nothing happened, because an           │
 │   abstention with a reason is a decision and has to be as          │
 │   inspectable as a change                                          │
 └────┬───────────────────────────────────────────────────────────────┘
      v
  memory_aware_text   "Ask Aadith Narayanan to review the Kivi rollout."
  + adjudication      every candidate, every policy, every reason
```

**The learning path is separate and runs on a different trigger.** Nothing in
the diagram above writes to memory:

```
  the user edits inserted text  /  adds a term  /  undoes a correction
      │
      v
 ┌────────────────────────────────────────────────────────────────────┐
 │ [L1] JUDGE     is this phonetic evidence, or a rewrite?            │
 │                                                                    │
 │   token-diff before → after, and score ONLY the changed span:      │
 │     "Adith Kulkarni" → "Aadith Kulkarni"      distance 0.09  ✓     │
 │     "ship it Tuesday" → "ship it Thursday"    distance 0.61  ✗     │
 │     "Ask X to review" → "Please ask X when…"  words added   ✗      │
 │                                                                    │
 │   A rejected observation is still logged. Declining to learn is    │
 │   itself a decision worth being able to inspect.                   │
 └────┬───────────────────────────────────────────────────────────────┘
      v
 ┌────────────────────────────────────────────────────────────────────┐
 │ [L2] ATTRIBUTE  which lexeme does this belong to?                  │
 │   exact form → phonetic proximity ≤ 0.20 → otherwise create a new  │
 │   one. Instructions, renames and deletions branch here: they are   │
 │   not corrections and are handled separately.                      │
 └────┬───────────────────────────────────────────────────────────────┘
      v
 ┌────────────────────────────────────────────────────────────────────┐
 │ [L3] APPEND     one immutable Observation onto the log.            │
 │                 Nothing else is authoritative.                     │
 └────┬───────────────────────────────────────────────────────────────┘
      v
 ┌────────────────────────────────────────────────────────────────────┐
 │ [L4] PROJECT    recompute EVERY lexeme from (prior + log):         │
 │                                                                    │
 │   alpha = prior.alpha + Σ decayed weights of supports              │
 │   beta  = prior.beta  + Σ decayed weights of contradictions        │
 │   confidence = alpha / (alpha + beta)                              │
 │   strength   = alpha + beta − 2                                    │
 │   decay      = exp(−ln2 × age_days / 90)                           │
 │                                                                    │
 │   guards derived from the log (2 reverts in a scope → suppression) │
 │   state derived from confidence, strength and disuse               │
 └────┬───────────────────────────────────────────────────────────────┘
      v
 ┌────────────────────────────────────────────────────────────────────┐
 │ [L5] REINDEX    rebuild the blocking index.                        │
 │                 It is a cache and is never authoritative.          │
 └────────────────────────────────────────────────────────────────────┘
```

## 7. One sentence, followed all the way through

Input: the user says *"the sarvam kiwi service is dropping requests"* in Slack.

**Memory holds**, among 24 terms:

```
  Kivi            active   conf 0.88  strength 6.0
                  variants: kiwi (observed 6×), kivvy (observed), kivy (generated)
                  guards:   common_word, lexical_context
  Sarvam          active   conf 0.86  strength 5.0
                  variants: survam, sarwam, sarvam ai, server (all observed)
```

**Formatter output:** `The Sarvam Kiwi service is dropping requests.`

**[0] Gate.** Spans include `Sarvam`, `Kiwi`, `service`, `Sarvam Kiwi`, … .
`normalise("kiwi") = "kiwi"` is an exact key. The gate opens.

**[1] Retrieve.** Two candidates survive:

```
  span "Sarvam"  → lexeme Sarvam   via canonical            score 1.00
  span "Kiwi"    → lexeme Kivi     via observed_variant     score 1.00
```

**[2] Adjudicate - the `Sarvam` candidate.**

| policy | signal | weight | why |
|---|---|---|---|
| `already_canonical` | **VETO** | - | the text already reads 'Sarvam' |

Verdict `ABSTAIN`, reason `already_canonical`. Nothing to do, and - importantly
- no model call. Cases B5-001 and B5-002 assert exactly this zero-cost path.

**[2] Adjudicate - the `Kiwi` candidate.**

| policy | signal | weight | why |
|---|---|---|---|
| `scope_fit` | NEUTRAL | +0.00 | global memory, applies everywhere |
| `exact_variant` | SUPPORT | +0.72 | 'Kiwi' is a known observed variant of 'Kivi', seen 6× |
| `common_word_guard` | SUPPORT | +0.30 | 'kiwi' is an ordinary word, **but** 'Sarvam' and 'service' are registered support tokens |
| `cooccurrence` | SUPPORT | +0.12 | Sarvam and Kivi were learned together |

Score `1.14 ≥ 0.55`, no veto → **APPLY**, reason `context_supported`.

**[3] Apply.** Splice `Kiwi → Kivi`. Casing carried from the source.

**Output:** `The Sarvam Kivi service is dropping requests.`

---

Now the same memory, the same user, a different sentence: *"i ate a kiwi for
breakfast"*, in Mail.

**[1] Retrieve.** One candidate: span `kiwi` → lexeme `Kivi`, score 1.00.

**[2] Adjudicate.**

| policy | signal | weight | why |
|---|---|---|---|
| `scope_fit` | NEUTRAL | +0.00 | global memory, applies everywhere |
| `exact_variant` | SUPPORT | +0.72 | 'kiwi' is a known observed variant of 'Kivi', seen 6× |
| `common_word_guard` | **VETO** | - | 'kiwi' is also an ordinary English word and **nothing in this sentence suggests 'Kivi'** |

Verdict `ABSTAIN`, reason `common_word_guard`. **Output unchanged.**

The two sentences differ only in their other words. That is the entire product:
the same match, the same score from the same evidence, and opposite answers,
because one sentence contains support for the term and the other does not.

## 8. The four ideas the design rests on

### 8.1 Memory is derived, never stored

The authoritative state is an **append-only log of observations**. Every field a
reviewer sees - confidence, state, variants, guards - is *recomputed* from that
log rather than being edited in place. This is the pattern usually called event
sourcing.

Four things the brief asks for fall out of it rather than needing machinery:

| Requirement | How it falls out |
|---|---|
| **Per-case memory state** in the evaluation | replay the log up to time *t* |
| **Provenance** - "why do you believe that?" | every field traces to observations |
| **Reset** | truncate the log |
| **Reproducibility** | same log + same clock = same memory, byte for byte |

The cost is that every load recomputes. With hundreds to low-thousands of terms
that is sub-millisecond, and the projection doubles as the repair path if the
cached tables ever drift.

Code: `src/psm/engine/projector.py`.

### 8.2 Confidence is a Beta posterior, not a counter

The naive approach is a counter: seen 5 times, reverted twice, net 3. That
breaks in three places, and the Beta posterior fixes all three at once.

A Beta distribution is the standard way to represent belief about a probability
when you have counted successes and failures. Two parameters:

```
    alpha = 1 + Σ (weight × decay) over supporting observations
    beta  = 1 + Σ (weight × decay) over contradicting observations
```

The `1 +` on each is the **uniform prior**: before any evidence, alpha = beta = 1
and the belief is 0.5 - no opinion. Two derived quantities:

```
    confidence = alpha / (alpha + beta)      the belief
    strength   = alpha + beta − 2            how much evidence backs it
```

**What this buys, concretely:**

**A revert is ordinary arithmetic.** It adds to `beta`. No special case, no
"undo" logic, no separate penalty table. Contradicting evidence is just
evidence with the other sign.

**It distinguishes 0.5-from-nothing from 0.5-from-a-lot.** Two terms can both
sit at confidence 0.5 - one because nothing is known, one because it has been
confirmed ten times and reverted ten times. A counter cannot tell them apart;
`strength` can, and activation requires **both** confidence ≥ 0.60 and strength
≥ 1.5. This is why a single sighting *proposes* rather than *acts*.

**Decay makes an old memory uncertain rather than wrong.** Because decay
multiplies the evidence and not the belief, an unused term's alpha and beta both
shrink toward the uniform prior: a colleague not mentioned since April drifts
back toward 0.5 rather than toward 0. A counter would either keep it at full
strength forever or drive it negative.

**Worked example.** A term seeded with alpha 5, beta 1 - confidence 0.83,
strength 4:

| Event | alpha | beta | confidence | strength | state |
|---|---|---|---|---|---|
| seeded | 5.0 | 1.0 | 0.83 | 4.0 | active |
| + one post-edit (weight 1.0) | 6.0 | 1.0 | 0.86 | 5.0 | active |
| + one revert (weight 2.0) | 6.0 | 3.0 | 0.67 | 7.0 | active |
| + a second revert | 6.0 | 5.0 | 0.55 | 9.0 | **suppressed** (guard) |
| one year later, untouched | 3.0 | 3.0 | 0.50 | 4.0 | dormant |

After a year the belief has regressed toward no opinion, not inverted. And the
second revert triggers a guard rather than waiting for the arithmetic: two
explicit refusals from the user outrank any score.

### 8.3 A decision is a stack of independent policies

Eleven policies, in a fixed order, each returning a signal, a weight, a reason
code and a rationale. Three properties matter:

**No policy sees another's answer.** They receive the candidate and the context,
nothing else. So removing one from the list cannot change how the others behave.

**Therefore an ablation is a configuration list, not a code branch.** Every row
of the ablation table in the README was produced by
`python -m psm.cli eval --policies …` with no code edited. That is what makes
"the guards are worth 16 cases" a measurement rather than an assertion.

**Order matters for cost, not for correctness.** The cheap decisive vetoes run
first so a blocked candidate short-circuits, but because a VETO is absolute the
result would be the same in any order.

Code: `src/psm/engine/policies/`, one file per family; `src/psm/config.py`
holds the default list.

### 8.4 A binding says where evidence arrived, not where a name is valid

This one is here because it was wrong for most of the build, and getting it
wrong produced the worst class of failure the system has.

Every observation carries a **binding**: the application the user was typing in
when the evidence arrived. Corrections made in Slack bind to Slack. That much is
just bookkeeping. The mistake was in what the engine then did with it - a
mismatch between a lexeme's binding and the current application was an absolute
veto, on the reasoning that "a Slack handle is wrong in an email".

That is sound for a Slack handle and wrong for almost everything else, because
it promotes a fact about the user's afternoon into a fact about the world.
Consider a colleague whose name you first corrected in Mail:

```
  Shreya Menon    active   conf 0.89   bound to com.microsoft.Outlook
                  variants: shreya menon (observed 2x), shreya menan (observed 2x)
```

Dictate *"ask shreya menan for the revised quote"* in Slack. Memory holds an
exact observed form for that exact mishearing. Under the old rule the output was
left as **"Shreya Menan"**: the system knew the answer, had recorded it, and
refused to give it because a different window was in focus. To a user that reads
as the product forgetting who someone is when they switch app.

The fix is to separate two questions the veto had been answering at once:

| Question | Whose job |
|---|---|
| *Is this term applicable here at all?* | scope - but only for terms whose binding is intrinsic |
| *Which of two rival terms did the user mean?* | the conflict policy, which does it in every application |

A binding is intrinsic when the term **names something that exists inside one
application**: `#eng-asr` is a channel, `prod` is a deployment target in one
team's tooling. Writing those into an email is not a spelling to fix; it is a
reference to something that is not there. Every other kind - person, org,
product, place, term, phrase - keeps its spelling wherever it is typed.

So `scope_fit` now vetoes only for `handle` and `code_symbol`. For everything
else a matching scope *adds* confidence (+0.18) and a mismatching scope withholds
that bonus. Nothing is lost: the work the veto was really doing - keeping two
people with the same-sounding name apart - was already being done by the conflict
policy, which does not care which window is open.

Three cases pin the rule, and they are worth seeing together:

| Utterance | App | Answer | Because |
|---|---|---|---|
| "ask shreya menan for the revised quote" | Slack | **Shreya Menon** | a person keeps her spelling; the binding was a note about where we learned it |
| "i posted the trace in hash eng asr" | Mail | *unchanged* | `#eng-asr` is a channel that does not exist in Mail |
| "ask shreya to send the deck across" | Slack | *unchanged* | two people answer to "Shreya" and only one is in scope - being in scope is not evidence about **who was meant** |

The third row is the one that keeps the change from overreaching. Having
weakened scope as a gate, it would have been easy to let it act as a tiebreaker
and pick the in-scope Shreya. That is a coin-flip with extra steps: which
colleague you meant is not determined by which window is open, and putting the
wrong person's name in a message is the worst thing this system can do.

**What it cost.** The derived evaluation had a 69-case `scope_mismatch` family
that asserted the old semantics for *every* kind, and 66 of them broke. They
were not bent to fit - the generator was rewritten to decide the expectation
from the term's kind, which splits the construction into two families that now
prove opposite halves of the rule: `scope_mismatch` (3 cases, app-native terms,
must stay quiet) and `scope_carryover` (66 cases, everything else, must still
correct). One hand-written case, **A15-001**, was added for the same reason and
is flagged `authored_before_engine: false`, because it was written after the
engine gave the wrong answer. §19 records both.

**Why it was not caught earlier.** The fixture and the engine agreed: the
generated family was built from the same belief the engine held, so it confirmed
it 69 times over. That is the failure mode of any generated suite whose author
also wrote the system. It took someone using the demo and saying "that is
obviously wrong".

Code: `src/psm/engine/policies/context.py`, `ScopeFitPolicy` and
`APP_NATIVE_KINDS`.

## 9. Phonetics from first principles

This is the machinery that lets the system find `Aadith` when the recogniser
wrote `Adhith` - a form it has never seen before. Four layers, applied in order.

### 9.1 Normalisation

Lowercase, strip punctuation, collapse whitespace. `"Aadith,"` → `"aadith"`.
Extended to cover Indic combining marks, for reasons in §9.4.

### 9.2 The romanisation fold

**The problem.** A recogniser trained mostly on English has to write an Indian
name in the Latin alphabet, and the alphabet does not carry the distinctions the
name has. So the *same* name comes out spelled several ways:

```
    Vishwanathan / Viswanathan / Vishvanathan
    Aadith / Adith / Aadhith
    Tanvi / Thanvi / Tanwi
    Patil / Phatil
```

These are not random typos. They follow a small number of documented, regular
correspondences between Indic phonology and English orthography:

| Correspondence | Examples |
|---|---|
| aspiration is optional in writing | kh~k, gh~g, th~t, dh~d, bh~b |
| **p, ph and f are one sound** | Patil ~ Phatil ~ Fatil |
| sibilants collapse | sh~s, zh~s |
| vowel length is unmarked | aa~a, ee~i, oo~u |
| v and w merge in Indian English | Tanvi ~ Tanwi |
| word-final schwa is unstable | Ram ~ Rama |
| **y and i alternate** | Vaidyanathan ~ Vaidianathan, Iyer ~ Iier |

The **fold** applies all of these as rewrite rules, collapsing every spelling of
one name to the same string. `fold("phatil") == fold("patil") == "patil"`.

It is applied **identically to both sides of every comparison**, which is what
makes it a canonicalisation rather than a guess. It also mangles English -
"the" becomes "te" - and that is fine, because both sides get the same
treatment and only convergence matters.

The two rules in bold were added late, after the derived evaluation tier found
them missing. §18 tells that story.

Code: `src/psm/adapters/phonetics/indic.py`.

### 9.3 Metaphone keys and blocking

**Metaphone** is a classic algorithm that reduces a word to a consonant skeleton
representing roughly how it sounds. `metaphone("Kivi") = "KF"`.

**Blocking** is the reason it is used. Comparing a span against all 367 terms in
memory would be slow. Instead every term is indexed under its phonetic keys, and
a span is only compared against terms that share a key. Typically that is a
handful rather than hundreds, which is why a call that finds nothing costs about
0.22 ms and one that retrieves about 1.7 ms against a 367-term memory (S5).

Keys are computed on the *folded* form, and three sets are generated per form:
the whole phrase, each token, and the consonant skeleton. Minimum key length is
2 - set to 3 at one point, which made `metaphone("Kivi") = "KF"` unindexable and
broke retrieval for the flagship example.

**Comparison.** Once a handful of candidates share a key, they are scored by a
blend of three measures, because each catches errors the others miss:

```
    0.40 × metaphone-key Jaccard    do they sound alike?
  + 0.35 × Jaro-Winkler             do they start alike? (good for names)
  + 0.25 × normalised indel         how many edits apart?
```

Code: `src/psm/adapters/phonetics/dmetaphone.py`.

### 9.4 Native Indic scripts

Everything above works on Latin text. Indian users also dictate in their own
scripts, and the same problems occur there: vowel length, aspiration, word
boundaries.

**The key observation** is that the nine Indic Unicode blocks this system
supports are **ISCII-aligned**: the same consonant sits at the same offset in
each block. `क` is Devanagari 0x0900+0x15; `ক` is Bengali 0x0980+0x15. So one
transliteration table, applied at a block offset, serves all nine:

| Script | Block base |
|---|---|
| Devanagari | 0x0900 |
| Bengali | 0x0980 |
| Gurmukhi | 0x0A00 |
| Gujarati | 0x0A80 |
| Odia | 0x0B00 |
| Tamil | 0x0B80 |
| Telugu | 0x0C00 |
| Kannada | 0x0C80 |
| Malayalam | 0x0D00 |

Native text is transliterated to a rough Latin phonetic form and then goes
through **exactly the same fold, index and policy stack** as English. There is
no separate Indic pipeline to keep in sync.

Three details worth knowing:

**The inherent schwa.** In Devanagari, a consonant carries an implied "a" unless
suppressed. `कमल` is "kamala" or "kamal" depending on the word. Both readings are
emitted; the comparator decides.

**Ambiguous letters.** ब/व (b/v) are read both ways almost everywhere, not just
in Bengali, which merged them outright. Every combination is emitted, capped at
three ambiguous positions per word: this is a *blocking* function, and a bucket
growing as 2ⁿ costs latency on every utterance.

**Tokenisation.** Python's `\w` does **not** match Indic combining marks -
matras, virama and anusvara are all Unicode category `Mn`/`Mc`, and
`'ा'.isalnum()` is `False`. Without an explicit block range in the tokeniser,
`शर्मा` splits into `['शर', 'म']` and a replacement leaves a dangling matra.
This produced a real, visible bug; §18 has it.

**One deliberate asymmetry.** Cross-script *retrieval* is allowed - Devanagari
text can match a Latin-canonical memory, so the system can tell they are the same
person. Cross-script *rewriting* is vetoed. Correcting someone's spelling is the
job; silently changing the alphabet they chose to write in is not.

Code: `src/psm/adapters/phonetics/indic_script.py`,
`src/psm/engine/policies/script.py`.

### 9.5 Where the phonetic codes come from

There is no external phonetic dictionary and no pronunciation model. Codes are
computed from the spelling, at index time and at query time, by the pipeline
above. So it works on names no dictionary contains, needs no download, and is
deterministic: the same string always produces the same keys.

## 10. How it learns

The application path never writes memory. Learning is a separate path with its
own trigger, and one rule does most of the work:

> **A post-dictation edit is only phonetic evidence if the replaced text is
> phonetically close to what replaced it.**

Without that gate, every stylistic edit becomes a spurious lexeme and the store
fills with noise within a day. With it, the learner ignores rewrites entirely
and only ever learns about *words*.

The scoring is done on **only the changed span**, not the whole string. This
matters: "ship it on Tuesday" → "ship it on Thursday" scores 0.27 when compared
whole - a long shared prefix disguising a change of meaning - and is correctly
rejected at 0.61 when only `Tuesday → Thursday` is compared. Insertions and
deletions of whole words are rejected outright.

Three things that are **not** corrections branch off before this:

**Instructions.** "always write it Aadith with two a's" is a rule, not a
substitution. The term is extracted with a small stated heuristic (a quoted run
wins; else the longest word that is not an ordinary instruction word) and the
instruction is stored **verbatim** on the lexeme, because it travels into the
formatting prompt as the user's own words.

**Renames.** A declared observation naming an existing lexeme with a different
form is a rename. The old spelling is kept as a variant *and* recorded on a
tombstone, so it still resolves to the renamed term rather than being learned
again from zero.

**Deletions.** An explicit forget tombstones the lexeme rather than dropping it,
so a later sighting does not silently recreate what the user deleted.

Code: `src/psm/engine/learner.py`.

---

# Part IV - the code

## 11. Every file, and what it does

```
src/psm/
  domain/      the vocabulary and the data shapes. No input, no output.
  ports/       descriptions of replaceable components. No working code.
  adapters/    the working components: phonetics, index, storage, clock,
               language model, formatter
  engine/      the actual machinery
  api/         the web server, the demonstration page and the case explorer
  seed.py      loads the example persona
  cli.py       the command line
migrations/    how the database tables get created
evals/         fixtures, generators, three runners, the stress suite,
               committed results, and explorer.py which turns them into
               one browsable page
tests/         automated tests
```

Three documents, and no more: `README.md` (what it is and how to run it),
`RUN.md` (the exact review procedure), and this report.

**`domain/`** - `enums.py` holds every closed vocabulary: sources, provenances,
states, guard kinds, verdicts, signals, and the 25 reason codes. Each value
appears in the database, in fixtures and in the API, so adding one is a schema
change. `models.py` holds frozen dataclasses for everything in §5 - frozen
because memory is derived, and a mutable one would eventually be mutated behind
the log's back.

**`ports/`** - seven `Protocol` definitions with no implementations: `clock`,
`phonetics`, `index`, `store`, `llm`, `formatter`, `policy`. Nothing in
`engine/` imports an adapter; it receives one. This is what makes ablations and
component swaps configuration rather than edits.

**`adapters/`** - the working parts:

| File | What it does |
|---|---|
| `clock/system.py`, `clock/frozen.py` | real time; pinned time for reproducible cases |
| `phonetics/indic.py` | the romanisation fold (§9.2) |
| `phonetics/indic_script.py` | nine Indic blocks → Latin (§9.4) |
| `phonetics/dmetaphone.py` | metaphone keys and the blended comparator (§9.3) |
| `index/inmemory.py` | the blocking index: gate, exact map, phonetic keys, span dominance |
| `store/sqlite.py` | the observation log and projection tables, SQLAlchemy Core |
| `store/memory.py` | the same interface in RAM, used by every test and the evaluation |
| `llm/stub.py` | deterministic, abstains, needs no network - **the default** |
| `llm/sarvam.py` | the live model over the OpenAI-compatible endpoint |
| `llm/cassette.py` | record once, replay for ever, keyed by request hash |
| `formatter/passthrough.py` | the frozen formatter used by the evaluation |
| `formatter/llm_formatter.py` | the live one: memory-conditioned prompt, output verified |

**`engine/`** - the machinery:

| File | What it does |
|---|---|
| `text.py` | tokenisation, n-gram spans, protected regions, case matching, right-to-left splicing. The tokeniser explicitly includes the Indic block range (§9.4) |
| `projector.py` | replays the log into memory state: confidence, strength, decay, derived guards, derived state (§8.1, §8.2) |
| `learner.py` | §10: judges observations, attributes them, handles instructions, renames and deletions |
| `guards.py` | synthesises guards rather than requiring hand-written ones, plus the decisive rule: an ordinary English word the recogniser has never actually produced for a term is never corrected |
| `policies/` | the eleven policies: `suppression.py`; `context.py` (`verbatim`, `scope_fit`, `common_word_guard`, `cooccurrence`); `lexical.py` (`already_canonical`, `exact_variant`, `phonetic`); `script.py`; `conflict.py`; `recency.py` |
| `adjudicator.py` | runs the stack, sums the weights, applies the thresholds, picks the verdict |
| `applier.py` | splices accepted replacements into the text |
| `engine.py` | the facade: `build()` wires everything, `handle()` is the hot path, `dictate()` runs the formatter first, `observe()` is the learning path |

**`api/`** - `app.py` is FastAPI, one endpoint per capability; `schemas.py`
converts domain objects to JSON and is shared with the evaluation, so the API
and `cases.jsonl` speak the same shapes; `ui.py` is the page, as one string,
with no build step and no CDN.

**`evals/`** - the evidence:

| File | What it is |
|---|---|
| `data/tier_c_application.jsonl` | 69 hand-written cases - the specification |
| `data/tier_c_learning.jsonl` | 15 hand-written cases about memory, not text |
| `data/tier_d_generated.jsonl` | 1,842 derived cases - the measurement, rebuilt by `make generate` |
| `data/persona_seed.json` | the 24-term reproducible persona |
| `data/personas/` | the native-script and Latin personas the derived tier uses |
| `gen/indic_names.py` | native-script names and offset-based confusion rules |
| `gen/build.py` | builds the derived tier deterministically |
| `harness.py`, `learning.py`, `generated.py` | the three runners |
| `stress/` | generator and runner for the six stress experiments |
| `explorer.py` | turns results into one browsable page |
| `schema/case.schema.json` | the JSON Schema every case is validated against |
| `results/` | every committed result, regenerable |

## 12. Configuration and swapping parts

Everything replaceable is named by a string in `src/psm/config.py`, resolved
through `src/psm/registry.py` by alias or dotted path:

| Setting | Default | Alternatives |
|---|---|---|
| `clock` | `clock.system` | `clock.frozen` |
| `phonetics` | `phonetics.dmetaphone` | `phonetics.null` (an ablation) |
| `store` | `store.sqlite` | `store.memory` |
| `index` | `index.inmemory` | any `CandidateIndex` |
| `llm` | `llm.stub` | `llm.sarvam`, `llm.cassette` |
| `formatter` | `formatter.passthrough` | `formatter.llm` |
| `policies` | the eleven, in order | any subset - this is how ablations work |

Every one is overridable by environment variable (`PSM_LLM`, `PSM_POLICIES`, …)
and by `.env`. Four tests assert that every alias resolves *and* that the engine
actually honours what is set - because for a while one of them did not, and every
result file recorded a component that had never run (§18, bug 9).

Thresholds live in the same place:

| Threshold | Value | Meaning |
|---|---|---|
| `retrieval_max_distance` | 0.34 | beyond this, not even a candidate |
| `apply_score` | 0.55 | combined score required to APPLY |
| `propose_score` | 0.30 | required to PROPOSE rather than ABSTAIN |
| `activation_confidence` | 0.60 | belief required to become ACTIVE |
| `activation_strength` | 1.5 | evidence mass required to become ACTIVE |
| `dormancy_confidence` | 0.35 | below this, DORMANT |
| `decay_half_life_days` | 90 | evidence is worth half as much after 3 months |
| `learn_max_phonetic_distance` | 0.45 | above this, an edit is a rewrite not a respelling |
| `reverts_to_suppress` | 2 | reverts before a suppression guard is created |

None of these is a knife-edge. Experiment S3 sweeps the two that matter and
shows a plateau: `apply_score` gives the same result anywhere between 0.35 and
0.55, and only above 0.60 does the system start missing corrections. A threshold
in the middle of a flat region is defensible; one perched on a cliff is fitted.

## 13. The demonstration app

`make serve` starts a single FastAPI process serving both the JSON API and one
self-contained HTML page at `http://127.0.0.1:8000` (`PORT` overrides). No build step, no
framework, no CDN, and no network access of any kind.

**Layout.** Two boxes at the top - the recogniser's output, and optionally the
formatter's version of it - then three lines that appear in order: what the
recogniser **produced**, what the formatter **made of it**, what **memory** did
with the change highlighted. Underneath, always, every policy that had an
opinion and the sentence it gave. Around that: a target-application selector
(the same words produce different answers in Slack and Mail), a panel for
feeding it one piece of evidence, the full memory table, and a reset.

**Eight prepared examples**, one click each. Three of them are cases where the
correct behaviour is to change nothing. Each loads into the two boxes, so a
reviewer can edit it and re-run rather than only watch.

**The case explorer is in the page**, at `/explorer` and linked from the header,
because eight examples are an illustration and 1,926 cases are the evidence.
It is the same file `make explore` writes; if it has not been built the route
builds it, for the same reason the demo seeds itself - a results directory is an
artefact, not a source file, and a reviewer who clones and runs `make serve`
should get the page rather than a 404.

**It comes up working, or says why.** The first request migrates the database if
it has no schema and seeds it if it is empty, so `make serve` before `make seed`
is no longer a demo where every button returns 500 (§18, bug 16). Anything that
still fails is returned as JSON with the reason in it and shown in a banner at
the top of the page, rather than as a stock phrase about the client's own
confusion.

**Why there is no microphone.** An earlier version had one, backed by a local
open-source recogniser, on the argument that hearing "Kivi" come out as "kiwi"
is better evidence than reading about it. Two things were wrong with that. A
small offline model is inaccurate in ways that have nothing to do with this
project, and every one of those errors landed on the memory system: a transcript
that came back as something unrelated made a correct abstention look like a bug.
And §1 says this project is a third stage that never touches audio, which is
what §14's claim to a deterministic offline evaluation rests on. Text in, text
out is the contract the evaluation measures, so the browser and the numbers now
describe the same system.

**Nothing is behind a button that is not also on the API and in the CLI.**

---

# Part V - the evidence

## 14. The evaluation: three tiers and what each proves

Three files, three runners, reported separately: averaging them would let 1,842
easy cases drown out 69 hard ones.

### 14.1 The taxonomy the cases test against

The brief gives one example and says discovering the rest is part of the
assignment. This is that discovery, written before the engine. Each class has a
stable id used as the `class` field of every case, so a regression can be traced
to a *kind* of failure rather than to a case number.

Three outcomes exist: **APPLY** (change the text), **PROPOSE** (surface a
suggestion, change nothing), **ABSTAIN** (do nothing, and record why).

#### A - classes where memory should fire

| id | Class | ASR / formatted | Memory-aware | The reason memory is the only thing that can know |
|----|-------|-----------------|--------------|----------------------------------------------------|
| A1 | `homophone_spelling` | Adith Narayanan | Aadith Narayanan | Acoustically identical. No recogniser can resolve it. |
| A2 | `real_word_hijack` | kiwi · Sarah's · my aura | Kivi · Saaras · Mayura | A rare term heard as a common word. Highest over-correction risk in the whole system. |
| A3 | `segmentation` | grad cam · vani gateway | Grad-CAM · vaani-gateway | Word-boundary memory. The tokens are individually plausible. |
| A4 | `casing` | i i t madras | IIT Madras | Includes the inverse: `npm` stays lowercase sentence-initially. |
| A5 | `acronym_collapse` | r l h f · z d r | RLHF · ZDR | Spoken letter sequences the formatter renders inconsistently. |
| A6 | `sigil_handle` | hash eng asr | #eng-asr | Scope-bound, and intrinsically so: the channel exists in Slack and nowhere else. |
| A7 | `preferred_exonym` | Bangalore | Bengaluru | The recogniser is not wrong. The user has a preference. |
| A8 | `standing_instruction` | Sarvam AI is hiring | Sarvam is hiring | Not a substitution at all - a rule that travels with the term. |
| A9 | `script_preference` | thik hai | theek hai | Romanised vs Devanagari vs translated. Per-user, per-app. |
| A10 | `multi_token_span` | shreya bhattacharya | Shreyaa Bhattacharya | Span matching. Correcting either token alone produces nonsense. |
| A11 | `revival` | a dormant term, strongly supported by context | applied | Decay must be reversible or long-tail names are lost forever. |
| A12 | `conflict_resolved` | two lexemes share a sound; context picks one | applied | The interesting half of the ambiguity problem. |
| A13 | `unseen_mishearing` | Ishan Vaidianathan | Ishaan Vaidyanathan | A romanisation never seen before, reachable only through the fold. Distinguishes a memory from a lookup table. |
| A14 | `indic_script` | मिरा शर्मा | मीरा शर्मा | Native Indic script. Vowel length, word boundaries and mis-segmentation occur in every script; the same code handles them. |
| A15 | `scope_carryover` | Shreya Menan, in Slack, learned in Mail | Shreya Menon | A person's spelling does not depend on the window. The binding records where the evidence arrived (§8.4). |

**A8 is the class that constrains the architecture.** "Always capitalised, never
'Sarvam AI' mid-sentence" and "keep romanised, never translate" cannot be
executed by any replace-based engine. Supporting A8 is why memory conditions the
formatting prompt instead of post-processing its output.

#### B - classes where memory must deliberately do nothing

These carry more weight than section A. A find-and-replace dictionary passes
every row above and fails every row below.

| id | Class | Situation | Expected |
|----|-------|-----------|----------|
| B1 | `common_word_sense` | `Kivi` is known; the user says "I ate a kiwi" | ABSTAIN - semantic context vetoes phonetic match |
| B2 | `ambiguous_conflict` | Two known people, one sound, no disambiguating context | ABSTAIN - never coin-flip |
| B3 | `weak_evidence` | Seen once, never repeated | PROPOSE - surface it, change nothing |
| B4 | `scope_mismatch` | A Slack channel handle attempted inside an email | ABSTAIN - the channel is not there to refer to |
| B5 | `already_canonical` | The formatted text already reads "Kivi" | ABSTAIN (no-op) - and no model call |
| B6 | `phonetic_stranger` | Memory holds `Kivi`; the ASR says "Kevin" | ABSTAIN - small distance, different referent |
| B7 | `unknown_term` | A name never observed | ABSTAIN - do not snap it to the nearest neighbour |
| B8 | `suppressed_by_revert` | The user undid this correction twice | ABSTAIN - negative evidence wins |
| B9 | `verbatim_region` | Dictating a quotation, or a literal inside code | ABSTAIN |
| B10 | `dormant_unsupported` | Long-unused term, no contextual support | ABSTAIN |
| B12 | `not_phonetic` | "two crore" → "₹2 Cr" | ABSTAIN - that is formatting, not memory. Say so. |
| B13 | `near_threshold` | Phonetic distance just below the cutoff | ABSTAIN - and log it as a near-miss |
| B14 | `wrong_referent` | Memory holds "IIT Madras"; the user says "IIT Delhi" | ABSTAIN |
| B15 | `no_candidate` | Nothing in the utterance resembles anything known | ABSTAIN at the gate - 0 tokens spent |
| B16 | `sound_alike_common_word` | A memory for `WER`; the text says "were" | ABSTAIN - a sound-alike is not evidence |
| B17 | `sound_alike_common_phrase` | A memory for `Ishaan`; the text says "is an" | ABSTAIN - a run of ordinary words is ordinary text |
| B18 | `script_shift` | Devanagari text matches a Latin-canonical memory | ABSTAIN - correcting spelling is the job; changing alphabet is not |

**B15 is a performance class, not a correctness class**, and it is the majority
of real traffic. It is listed here because the evaluation has to show that the
common case costs nothing.

B16 and B17 were **not** invented by inspection - they were found by running a
367-term memory over 4,000 sentences of real English prose and looking at what
broke. Between them they accounted for every false positive the system had.

`learning_disabled` started life as B11 and moved to C13: turning learning off
stops the system *recording* evidence, not *applying* what it already knows.
Those are different behaviours and belong in different sections. The id is not
reused.

#### C - learning classes

Evidence handling, tested separately from application. A case here asserts a
change in memory state, not a change in text.

| id | Class | Signal | Expected effect |
|----|-------|--------|-----------------|
| C1 | `learn_from_edit` | Inserted "Adith", user typed "Aadith" within the window | New observed variant; lexeme → PROPOSED |
| C2 | `reject_rewrite` | "Ask Aadith" → "Please ask Aadith when he's free" | No observation. Not phonetic. |
| C3 | `learn_declared` | User adds the term explicitly | ACTIVE at n=1 |
| C4 | `activation_threshold` | The same correction, twice, in one scope | PROPOSED → ACTIVE |
| C5 | `cross_scope_activation` | The same correction twice, in two different apps | ACTIVE - evidence is scope-agnostic |
| C6 | `revert_penalty` | The user undoes an applied correction | Confidence falls; contradicting evidence recorded |
| C7 | `suppression_on_repeat_revert` | Two reverts | Suppression guard created |
| C8 | `instruction_signal` | "always spell it with two a's" | Declared variant, high weight |
| C9 | `ambient_weak` | Term seen in surrounding screen text only | Weak observation; PROPOSED at best |
| C10 | `supersession` | Canonical form renamed | Tombstone with `canonical_supersession`; old form still resolves |
| C11 | `casing_only_edit` | Edit changes case alone | Learned as a styling variant, not a new lexeme |
| C12 | `deletion` | User forgets a term | Tombstone with `user_delete`; re-observation does not silently recreate it |
| C13 | `learning_disabled` | Learning is off for this lexeme; a correction arrives | No variant recorded. Application is unaffected - the two are separately controllable |

C5 originally asserted the opposite, under the name `scope_specific_activation`:
that evidence accrues per scope, so two corrections in two apps left the term
PROPOSED. That was internally consistent and wrong to use - a person who fixed a
name once in Slack and once in Mail has fixed it twice. Evidence is now
scope-agnostic for the purpose of *believing* a term; where a term *applies* is
a separate question, answered in §8.4.

#### Reason codes

Every verdict carries one, and the evaluation reports accuracy *per reason code*
- which is how a systematic failure gets found instead of averaged away.

**APPLY** - `exact_observed_variant`, `phonetic_high_confidence`,
`context_supported`, `declared_by_user`, `standing_instruction`

**PROPOSE** - `single_observation`, `below_activation_threshold`,
`scope_unproven`, `conflict_needs_user`

**ABSTAIN** - `no_candidate`, `common_word_guard`, `guard_condition_met`,
`ambiguous_conflict`, `superseded_by_longer_span`, `already_canonical`,
`dormant_without_support`, `out_of_scope`, `semantic_mismatch`,
`verbatim_region`, `suppressed`, `not_phonetic_change`, `learning_disabled`,
`below_threshold`, `wrong_referent`, `script_mismatch`

### 14.2 Tier C application - 69 cases - *the specification*

Hand-written **before the engine existed**, and a test enforces it: every case
carries `authored_before_engine`, and the suite fails if more than 20% were
authored afterwards.

Structure: `given` (asr text, formatted text, app, optional memory overrides) and
`then` (expected output, expected reason code, optional model-call budget).

**Every case asserts a reason code as well as an output.** A case that produces
the right text through the wrong policy is recorded as `reason_mismatch`, not as
a pass - which is the usual way a green suite hides a broken system.

**32 of the 69 are negative**: cases where intervening is the failure. They are
organised by the taxonomy above - A1–A15 (memory should fire) and B1–B18 (memory
must deliberately do nothing).

Run with `make eval`. Current: **68/69**.

### 14.3 Tier C learning - 15 cases - *what evidence does to memory*

A separate file with a separate runner, because it asks a different question and
fails differently: a system can rewrite text correctly while learning the wrong
thing from it. These assert a change in **memory state** - a lexeme created, a
variant added with a given provenance and count, a guard created, confidence
decreased, a tombstone written - rather than a change in text.

Every `memory_delta` key is implemented as a check; an unrecognised key is an
error rather than a silent skip. That matters, because for a while this file had
**no runner at all** and all fifteen assertions were decorative (§18).

Runs inside `make eval`. Current: **15/15**.

### 14.4 Tier D - 1,842 cases - *the measurement*

Built mechanically from committed inputs by `evals/gen/build.py`. The property
that makes it worth anything: **its expected outcome comes from the
construction, never from what the engine did**. A case that says "take the
canonical `Vaishnavi Kulkarni`, apply the documented v→w confusion, put it in a
carrier sentence in the app this term is bound to" knows the right answer before
the engine is built. Recording the engine's replies as expectations instead
would produce a suite that can never fail.

Twelve families across four personas and ten scripts. Three of the personas have
**no hand-written guards at all**, and none is the one the thresholds were tuned
on.

| Family | n | What it varies |
|---|---|---|
| `known_variant` | 305 | forms already on file |
| `unseen_mishearing` | 306 | 20 documented Latin confusion rules, tagged by rule |
| `indic_known_variant` | 84 | nine scripts, forms on file |
| `indic_unseen` | 115 | nine scripts, offset-based confusion rules |
| `ordinary_prose` | 500 | real English prose the author did not write |
| `unknown_name` | 120 | names in no persona at all |
| `ordinary_word_sense` | 60 | terms used in their plain English sense |
| `already_canonical` | 144 | the formatter already got it right |
| `verbatim_region` | 99 | a known wrong-form inside a quotation |
| `scope_carryover` | 66 | an app-bound *person* used elsewhere - must still be corrected (§8.4) |
| `scope_mismatch` | 3 | an app-*native* term used elsewhere - must stay quiet |
| `script_shift` | 40 | Devanagari text against a Latin-canonical memory |

**Two families are meant to be hard.** `unseen_mishearing` and `indic_unseen`
ask the system to fix spellings that are in no variant table anywhere. A perfect
score there would mean the confusion rules were too timid.

**The value is the slices, not the total.** The runner reports per family, per
persona, per script and per confusion rule, because "72% overall" is not
actionable and "the fold handles aspiration but not v/w" is.

Run with `make eval-generated`, rebuild with `make generate` (deterministic -
same inputs, same seed, byte-identical output). Current: **1,839/1,842**.

### 14.5 Reading the results

`make explore` builds one self-contained page with both tiers: every
hand-written case in full detail - inputs, diffed output, the complete decision
trace, and the memory state at the moment it decided - and every derived case,
filterable by family, script, confusion rule and pass/fail, above the breakdown
tables.

## 15. The stress suite

Six experiments that measure what a hand-written case list structurally cannot.
`make stress`.

| # | Experiment | What it answers |
|---|---|---|
| S1 | Three unseen personas (24 / 104 / 367 terms) | does it work on memories the thresholds were never tuned on? |
| S2 | 4,000 sentences of real English prose | how often does it corrupt text it should not touch? |
| S3 | Threshold sweeps | plateau or knife-edge? |
| S4 | Messy input: unpunctuated, disfluent, ALL CAPS, emoji, stutters | does it survive real dictation? |
| S5 | Latency and index build at 24 / 104 / 367 terms | does it scale? |
| S6 | 94 held-out mishearings | can it fix forms it has never seen? |

**The corpus is deliberately not written by this project's author**: the 4,000
neutral sentences are harvested from Python standard-library docstrings, so
"zero false positives on real prose" is a claim about prose nobody here chose.

**Two taxonomy classes exist because of this suite.** A memory for the acronym
`WER` was rewriting the word *"were"* - 20 times in 4,000 sentences - and
`Ishaan` was rewriting the phrase *"is an"*. Between them they were **every**
false positive the system had, and no amount of thinking up cases produced
either.

## 16. The tests

**157 tests** in six files. `make test`.

| File | n | What it protects |
|---|---|---|
| `test_fixture_integrity.py` | 21 | properties of the *evaluation itself*: schema validity, unique ids, expectation self-consistency, taxonomy coverage, the negative-case ratio, that every learning fixture executes and asserts something a check reads, and that every configurable component name resolves and is honoured |
| `test_engine.py` | 40 | the engine's mechanisms: the projection under supporting and contradicting evidence, prior decay, instruction parsing, renames, deletions, suppression |
| `test_robustness.py` | 67 | regression guards for failures the stress and derived suites found - the Indic path, the fold's coverage, the b/v alternation, and the negative half of the derived tier run inline |
| `test_api.py` | 12 | one test per capability the brief asks a reviewer to exercise, plus scope enforcement, Unicode round-tripping and the zero-cost path |
| `test_live_path.py` | 5 | the live model path end to end against a stub OpenAI-compatible endpoint on localhost: memory reaching the prompt, a rewriting reply being rejected, a 500 degrading rather than crashing, the no-memory ablation really removing the memory, and the key never appearing in a prompt or a result |
| `test_demo.py` | 12 | the demo as a deliverable: every prepared example still behaving as its label claims, a database with no schema being migrated rather than reported, an unexpected failure arriving as JSON with a reason in it, one observation reporting one changed term, the explorer being reachable, the page calling nothing the API does not expose, no external resource loaded, and - using `node --check` - that its embedded JavaScript actually parses |

That last one exists because the client is ~200 lines of JavaScript inside a
Python string, which no compiler ever sees. A stray bracket produces a blank page
and a green test suite. It happened once.

## 17. Every number, and what it means

```
Specification tier      68 / 69     (99%)
Derived tier         1,839 / 1,842  (99.8%)
Learning tier           15 / 15
False interventions      0 / 998 negative cases    (0.00%)
Corruptions on 4,000 sentences of real prose   0    (0.00%)
Unseen mishearings fixed automatically            87.2%
Unseen mishearings not exactly canonical           2.1%
Model calls in the entire evaluation                  0
Median latency, derived tier                    0.67 ms
Throughput, 367-term memory            ~2,300 sentences/sec
Tests                                               157
```

The two timing figures are the only ones here that depend on the machine; every
other number is exact and reproduces anywhere.

**Which of these matter, and why:**

**`0 / 998` is the headline.** Not the pass rate. A missed correction is an
annoyance; a corrupted sentence is unshippable, and the two are not comparable,
so they are counted separately everywhere.

**`0 model calls`** means every number above is reproducible on any machine with
no key and no network. It is also the cost story: the common case is free.

**`87.2% of unseen mishearings`** is the generalisation number, and the one to be
sceptical of - it is measured on rule-generated forms, not on real
recogniser output, because no real corpus of this user's mishearings exists. The
2.1% figure beside it counts every output that is not the exact canonical form,
including a half-correction and a casing difference (§20), and is reported next
to the success rate rather than filtered.

**The ablations** are what turn these into evidence rather than assertions:

```
                              pass        useful  harmful   false intervention
full stack               68/69  (99%)         36        1                 0.0%
no cooccurrence          66/69  (96%)         34        2                 0.0%
no conflict              66/69  (96%)         36        1                 0.0%
no phonetic scoring      65/69  (94%)         35        1                 0.0%
no phonetics at all      57/69  (83%)         35        1                 0.0%
no guards                52/69  (75%)         28       11                21.9%
exact match only         41/69  (59%)         25       10                18.8%
```

Read the last two rows first. Removing the guard stack turns one harmful
intervention into eleven and takes false intervention from 0% to 21.9% - the
guards are not a safety wrapper around the product, they are the product.
Removing phonetics costs eleven *useful* corrections and no harmful ones, which
is the expected shape: phonetics decides how much the system can help, guards
decide how much it can hurt. Every row was produced by
`python -m psm.cli eval --policies …` with no code edited.

---

# Part VI - what went wrong

## 18. Bugs found, and how each was found

Twenty. The column that matters is the third one: almost none would have been
found by reading the code, and each was found by a *different kind* of looking.

| # | Bug | Found by | Symptom |
|---|---|---|---|
| 1 | Soundex in the blocking index | the specification suite | the cheap gate opened on *every* sentence |
| 2 | Span dominance ranked by length, not confidence | the specification suite | exact matches discarded for longer fuzzy ones |
| 3 | The learner compared whole strings | a unit test | "ship it on Tuesday" → "Thursday" learned as a spelling fix |
| 4 | Disuse check nested inside the confidence branch | the specification suite | well-evidenced but stale memories never faded |
| 5 | Persona dates loaded verbatim | writing this document | every term reported itself dormant on day one |
| 6 | Unguarded acronyms and phrases | the stress suite | `were → WER` in 20 of 4,000 sentences |
| 7 | Metaphone blind to romanisation variation | the stress suite | only 36% of unseen mishearings fixed |
| 8 | `\w` does not match Devanagari combining marks | adding Indic support | "शर्मा" tokenised as two words; output had a dangling matra |
| 9 | **Three configured components did not exist** | **auditing against the brief** | **every result file recorded an `index.sqlite_fts` that had never run** |
| 10 | **The ablation named "no phonetics" removed almost nothing** | **auditing against the brief** | **a headline number understated by twelve cases** |
| 11 | **Confirming a term made the system less confident of it** | **clicking a button in the demo** | **a supporting edit demoted a seeded term from active to proposed** |
| 12 | **Fifteen learning fixtures had no runner at all** | **auditing against the brief** | **six specified behaviours were never implemented and nothing noticed** |
| 13 | **The romanisation fold was one-directional** | **slicing the derived tier by confusion rule** | **`sh→s` passed 100%, `s→sh` passed 48%** |
| 14 | **b/v modelled as a Bengali peculiarity** | **slicing the derived tier by script** | **eight of nine remaining Indic failures were one letter** |
| 15 | **The generator was wrong before the engine was** | **running the derived tier the first time** | **eleven "harmful interventions" that were entirely the fixture's fault** |
| 16 | **The demo did not create its own schema** | **a reviewer starting the server** | **the page rendered and every button on it returned a bare 500** |
| 17 | **The teach panel reported all 24 terms as changed** | **clicking a button in the demo** | **"0.833 -> 0.833" for every term, burying the one that moved** |
| 18 | **A binding was read as a licence** | **someone using the demo and saying "that is obviously wrong"** | **a name with an exact recorded mishearing left uncorrected because a different window was in focus** |
| 19 | **The self-healing migration raced itself** | **a console error on a clean-start rehearsal** | **the page's first two calls both ran the migration; one returned 503 and the header read "memory unreadable"** |
| 20 | **`make eval-live` never ran anything live** | **typing every documented command in order** | **`--live` was declared and never read, so the target ran the offline stub and wrote a result file labelled `live` reporting 0 model calls** |

The first eight are ordinary engineering bugs found by ordinary means. The rest
each name a *class* of failure that testing does not catch. Three of them - 9,
10 and 20 - are the same class: configuration that claims something nothing
checks.

### 9 - a config field the engine ignores

`Settings.index` said `index.sqlite_fts`. The module had never been written; the
engine hardcoded the in-memory index and never read the field, so every ablation
result recorded a component that did not run. Nothing failed, because nothing
checked. Four tests now assert that every alias resolves *and* that a swap in
`Settings` reaches the built object. A configuration field nothing verifies is
worse than no field, because it makes a false claim in every artefact it appears
in.

### 10 - an ablation weaker than its name

Removing the `phonetic` *policy* leaves phonetic *retrieval* running, so it
measured almost nothing: 65/69. Replacing the encoder with a null one removes
retrieval too: 57/69. The first was reported under the name "no phonetics",
understating the rest of the stack by a factor of three. Both are now reported,
under names that say which is which.

### 11 - the demo found what 112 tests could not

Confidence is derived by replaying the observation log. A lexeme arriving with
evidence already attached - a seeded persona, an imported dictionary - had
nowhere to put it, so the projection used the stored number *only while the log
was empty*. The first correction of such a term replaced a history of four
sightings with an arithmetic over one, and confidence went **down**. A
supporting edit could demote a term from `active` to `proposed`.

Every test and every evaluation case missed it, for a structural reason: each
fixture pins its own memory state and then makes one decision. **None of them
adds evidence to a seeded term and looks again.** Thirty seconds of clicking
"Record evidence" in the demo surfaced it.

The fix is `Lexeme.prior`: pre-log evidence held explicitly, the projection
becoming `prior + log`, and Beta(1,1) for a term that really did start from
nothing. Migration `0002` adds the columns. It also made a documented claim true
for the first time - "decay makes an old memory uncertain rather than wrong" was
false for any seeded term, whose evidence had no date to grow old from.

### 12 - fixtures with no runner

`tier_c_learning.jsonl` existed, was schema-checked, and was **never executed**.
Writing `evals/learning.py` and running its fifteen assertions found six
behaviours that had been specified from the beginning and never implemented:
suppression on repeat reverts, instruction parsing, casing-only edits, renames,
deletions and prior decay. All six are implemented now, and the learning tier
runs inside `make eval` so it cannot silently detach again.

### 13 - the fold was one-directional

Slicing the derived tier by confusion rule showed `sh→s` passing 100% while
`s→sh` passed 48%, and `dh→d` passing 100% while `d→dh` passed 59%. That
asymmetry should have been impossible, since the fold is applied to both sides
of every comparison, and chasing it found two real holes: nothing collapsed
`p`/`ph`/`f`, so "Patil" and "Phatil" sat in different blocking buckets, and
`y→i` fired only after a consonant, which is not where `y` sits in *Iyer* or
*Yashodhara*.

Fixing both moved the derived tier from 92.8% to 99.5%, with zero new false
positives across 1,032 negative cases and 4,000 sentences of real prose. The
gate in fact opened *less* often afterwards, 43.4% → 28.7%, because the wider
fold changed which English words collide. A single pass rate would have shown
none of this.

### 14 - b/v is not a Bengali peculiarity

Slicing by script showed every remaining Indic failure was one letter, failing
identically in Devanagari, Telugu, Odia and Malayalam. The same finding exposed
a second bug: alternate readings were all-or-nothing. वैष्णवी contains two `व`,
so the alternative was "baishnabii" when the recogniser's actual error is
"baishnavii" - one letter, not both - and the word could never match its own
mishearing. Readings are now emitted per combination.

### 15 - the generator was wrong before the engine was

The first run of the derived tier reported **eleven harmful interventions** in
its easiest family. All eleven were the generator's fault: it assigned target
applications round-robin and demanded that an app-bound term be corrected inside
a *different* app. The engine refused, correctly. Nine more "failures" were the
`s→sh` rule firing on an already-aspirated `s` to produce "Deshhpande", a
doubled h that appears in no romanisation of anything. A generated expectation
is worth nothing unless the generator models the same rules the system does.

### 16 - the worst possible failure mode for a demo

`make serve` before `make seed` left an empty SQLite file. The page rendered
perfectly; `/health`, `/memory` and `/dictate` all died on `no such table:
lexeme`; and because Starlette answers an unhandled error with a plain-text
body, the page's `response.json()` threw and it reported **"API unreachable"**
and **"unreadable response"** about a server that was running, listening, and
answering with a completely clear error.

Two things were wrong and they compound. The application refused to fix a
condition it could fix - the migration exists and running it is one subprocess -
and the interface described its own confusion rather than the server's problem.

`engine()` now runs the migration when the first query finds no schema and then
seeds; an `Exception` handler returns `{"detail": "..."}` so the reason survives
the trip; and the page shows that reason in a banner. The migration still owns
the schema: the app runs it, it does not duplicate it.

Found by starting the server on a machine that had never run `make seed`. Not by
a test - every test built its engine over an already-migrated database or an
in-memory store, so the one path a reviewer takes first was the one path nothing
covered. There is a test for it now.

### 17 - a report that named everything named nothing

Recording one correction made the teach panel report **all 24 terms**, most of
them as `confidence 0.833 -> 0.833`. The guard was `abs(before - after) > 1e-9`,
which reads as generous and is useless here: every confidence is decayed against
the clock, so the projections either side of an observation differ for *every*
term somewhere around the twelfth decimal place. The comparison is now made at
the precision actually displayed.

### 18 - the fixture agreed with the bug

Dictating *"ask shreyaaa menon to review the pull request"* in Slack produced no
change at all, with two abstentions stacked on top of each other:

```
  ABSTAIN  'Shreyaaa Menon' -> unchanged     out_of_scope
           matched Shreya Menon via observed_variant, retrieval 1.00
           scope_fit  VETO  'Shreya Menon' applies only in com.microsoft.Outlook

  ABSTAIN  'Shreyaaa' -> unchanged           ambiguous_conflict
           matched Shreyaa Bhattacharya via phonetic, retrieval 0.95
           conflict   VETO  could be 'Shreyaa Bhattacharya' or Shreya Menon;
                            nothing here decides between them
```

Both lines are wrong, in different ways, and the second is the worse one. The
engine had an exact recorded form for the mishearing and refused it on scope
(§8.4). And the shorter span did not fail because nothing could tell the two
names apart - it failed because the longer span had already won; the very next
token, *Menon*, is what decides it. An explanation that says "nothing here
decides between them" while the deciding evidence sits one token to the right is
not a wording slip. This system's claim is that its reasons are the computation
rather than a story told afterwards, and that reason was a story.

The conflict policy now distinguishes the two cases and reports
`superseded_by_longer_span` with the winning span named. The verdict is
unchanged; only the truth of the sentence is.

**Why nothing caught it.** The derived tier had 69 cases asserting the very
behaviour that was wrong, because the generator was written from the same belief
the engine held. Its construction-not-behaviour rule protects against the engine
drifting away from the specification. It does not protect against the
specification being wrong, and nothing automated does. Each of the four things
that found a real bug here - the stress corpus, the slice-by-rule breakdown, the
demo, and a person's judgement - is a different *kind* of looking.

### 19 - a fix with a race in it

Bug 16's fix has the application run its own migration when the first query
finds no schema. FastAPI serves synchronous endpoints from a threadpool, and the
demo page opens `/health` and `/memory` in the same tick, so on a fresh database
both requests entered that path, both ran `alembic upgrade head`, and one of
them lost: a 503 in the console and one line in the header reading *"memory
unreadable"*, on exactly the run where the healing was supposed to matter.

D-012 says this system has no concurrency story, and that is true of *memory*:
one user, one process, no locking. Initialisation is a different claim. It is a
`threading.Lock` now, with the double check inside it, and a test that fires four
concurrent requests at a database with no schema and asserts four 200s. Found by
reading the browser console during a clean-start rehearsal.

### 20 - a flag that was declared and never read

`make eval-live` ran the offline stub. `--live` was declared on both the CLI
parser and the harness parser and neither one ever read it, so the harness built
its `Settings` from the defaults and went on its way. The target completed
happily, printed **0 model calls**, and wrote `evals/results/live/`. That is the
same shape as bug 9 and worse in one respect: bug 9 made a result file record
something untrue about itself, while this made a result file whose *name* was
the untrue part, in the one direction that flatters the author.

`--replay` had the same defect and an extra layer under it. Once the flag was
wired up, replaying against an empty cassette directory still produced the
offline numbers, because `LLMFormatter` catches every exception and degrades to
the unconditioned text. That is correct in production - a formatting stage must
not take dictation down with it - and ruinous in an evaluation, where a run that
reached no model at all is indistinguishable from a healthy one.

Three changes. The flags now select components (`llm.sarvam` + `formatter.llm`
for live, `llm.cassette` + `formatter.llm` for replay). The formatter counts its
failures and keeps the last error. And the harness makes one probe call before
running anything, so a live or replay run that cannot reach its model fails with
a sentence naming the reason and writes no file at all:

```
psm-eval: error: the formatter.llm formatter could not reach llm.cassette:
CassetteMiss: no recording for this request (b20eeaec...). Nothing was written.
Run `make eval` for the offline evaluation.
```

Found by working through `RUN.md` and typing every documented command, which is
the one kind of looking this project had not done to itself. It also prompted
`tests/test_live_path.py`, which drives the whole live chain against a stub
endpoint on localhost and turns "lightly exercised" into five assertions.

## 19. Changes made to test cases, and why

The specification cases were written before the engine. When the two disagreed
the case changed only when the case was wrong, and every change is logged here.
**Only two expected verdicts ever changed**, and both are marked.

| Case | Change | Why |
|---|---|---|
| A8-001, A8-003 | reason `standing_instruction` → `exact_observed_variant` | the replacement comes from the table of known forms; the instruction is *why the form is on file*, not what applied it |
| B12-001 | reason → `below_threshold` | the gate opens, retrieval finds nothing worth acting on. Recorded as it behaves |
| B14-001 | reason → `below_threshold` | same: we looked, and declined |
| B14-002 | reason → `ambiguous_conflict` | two known Shreyas retrieve, neither is the person in the sentence, and the system abstains. Right outcome, more precise reason |
| B6-001, B6-002, B13-001 | reason → `no_candidate` | the phonetic code differs, so the gate closes before the scorer. Better than expected: the rejection is free, not merely correct |
| B10-001 | changed the test word | the original form was too distant to retrieve at all, so the case tested nothing. The new one retrieves and is then declined for dormancy - the behaviour the case exists to test |
| **A12-002** | **`apply` → `abstain`** | the original asked the system to fix the *formatter's* output using recogniser text it had already discarded: a formatter bug dressed as a memory case. Rewritten as the other half - in email, the client's name is already right and must survive untouched |
| **L5-001** | **`proposed` → `active`; class renamed `scope_specific_activation` → `cross_scope_activation`** | a product decision, not a bug fix (D-010). Someone who fixed a colleague's name once in Slack and once in Mail has fixed it twice. Evidence is now scope-agnostic for *believing* a term; scope still decides where a term *applies*, which B4-001 tests |
| B15-001 | reason → `no_candidate` | when the fold was widened, this sentence's tokens stopped sharing a blocking key with anything, so the gate now closes before retrieval instead of opening and declining. Strictly better: the call is now free rather than merely correct |
| B7-002 | reason → `single_observation` | also from the wider fold: "Shreyas" now shares a key with "Shreya" and is PROPOSED rather than ignored. The text is still unchanged, which is what the class requires. A real cost, recorded rather than tuned away: the fold bought +21 derived cases and cost this one suggestion |
| seed: `Kivi` | veto words trimmed | listing *ate*, *eat*, *breakfast* is brittle. "A common word with no positive support is left alone" is the general rule, and the stronger claim |
| seed: `Sarvam` | added `server` as a known form | a guard referenced a form that was not in the list - dead configuration |
| seed: both Shreyas | added `shreya` as a guessed form | needed for both to retrieve on a bare first name and demonstrate the conflict |
| **A15-001** | **new case, `authored_before_engine: false`** | the counterpart to B4-001 and the only new specification case. A person bound to Mail, dictated in Slack, whose mishearing is on file: the correction must still be made. Written after the engine gave the wrong answer, and flagged as such (§8.4, §18 bug 18) |
| **derived `scope_mismatch`** | **69 cases → 3, plus 66 in a new `scope_carryover` family** | **the only generated expectations ever changed.** The family asserted that an app-bound term of *any* kind must stay quiet elsewhere: right for a channel handle, wrong for a person. The generator now decides the expectation from the term's kind |
| seed: `Shreya Menon` | added `shreya menan` as an observed form | the seed had no app-bound person with a recorded mishearing, so A15-001 had nothing to be about. A gap in the persona, not a tuned expectation |
| seed: `Mayura` | added a common-word guard | *"my aura"* **is** an ordinary English phrase and should have to earn its correction like *kiwi* does |

## 20. What is not true yet

**A binding is still a single flat fact.** §8.4 replaced a wrong rule with a
better one, but the better one is a two-way classification - intrinsic or not -
decided by the lexeme's `kind`. The real signal is richer: *how many* distinct
applications a term has been corrected in, and whether the user ever said
anything about where it belongs. A term corrected in four applications is global
in all but name, and the system cannot notice that.

**One specification case fails, on purpose.** A8-002 wants `ZDR` expanded to
`Zero-data retention (ZDR)` in an email but abbreviated in chat. The output is
not the canonical form and cannot be produced by substitution at all - it needs
the formatting model to act on the instruction. Passing it would mean either
hard-coding the case or turning on a model call the rest of the evaluation does
not use. 68/69 with a documented limitation is worth more than a green suite
hiding the gap.

**Three derived cases fail, also on purpose.** All three are terms with a single
weak observation being `PROPOSE`d rather than applied. That is the activation
threshold doing what it is for.

**Ten of ninety-four held-out mishearings are still missed, and two do not
produce the canonical form.** The misses cluster on doubled aspirates and long
vowels (`Rukmeeni`, `Dhroow`, `Aaditya Deshhpande`), forms the fold reaches but
the comparator scores just beyond the retrieval cutoff. The other two are
counted against the system rather than argued away: `Keerthhana Krishnamurthi`
came out as `Keerthana Krishnamurthi`, the given name fixed and the surname
left, which is a half-correction rather than a wrong name; and `vaaani-gateway`
came out correct but sentence-initially capitalised, which the exact-match check
does not accept. Both are scored as failures because S6 asks for the canonical
form and nothing else. Widening the fold reduces the misses and increases the
risk of real substitutions. That trade is not solved, only positioned.

**No language model is used anywhere in the committed numbers.** The whole engine
is arithmetic - zero cost, sub-millisecond. The Sarvam adapter, the cassette
recorder and the memory-conditioned formatter all exist and are wired in behind
ports, but every number in `evals/results/` was produced with no network access.
That leaves one important question unanswered: *would a well-prompted language
model with no memory system have done this anyway?* That baseline has not been
run.

**The live path has never met a real model.** `tests/test_live_path.py` stands
up a stub OpenAI-compatible endpoint on localhost and drives the whole chain
through it, but what that cannot test is whether a real model writes good prose
or how often it overreaches, which are the two numbers that would matter in
production. No cassettes are committed, because the committed evaluation makes
zero model calls and so has nothing to replay.

**One canonical form per term.** A user who writes a name in both Devanagari and
Latin is served by the system declining to convert, rather than by it holding
both spellings. That is a schema change, not an architecture one.

**More than three ambiguous letters in one word.** Alternate readings are capped
at three ambiguous positions (§9.4), so a word with four is reachable only by its
first three.

**The instruction parser is deliberately small.** It pulls a term out of a spoken
rule using stated heuristics - a quoted run, else the longest non-instruction
word - and returns nothing rather than guessing. A multi-word term yields its
most distinctive token. It is a convenience, not a claim to understand
instructions.

**No real speech data.** The evaluation's mishearings are rule-generated from
the confusion model in §9, not harvested from a recogniser. That model is built
from published Indic ASR confusions and from the ISCII alignment of the scripts,
but it is still a model, and a production recogniser's distribution would differ.
The next step is to run Saaras over recordings of these sentences and rebuild the
derived tier from what it returns: a data-collection task, not a design change,
and the generator is already separated from the fixtures so only its input would
move.

**Single user, single process.** No `user_id` anywhere, and the API keeps one
engine. Adequate for personal memory; not a concurrency story.

## 21. Decision log

Numbered and short, with the alternative that was rejected and the cost that was
accepted. The interesting ones are near the bottom: five were changed by
evidence rather than by argument, and the last, D-026, was changed by somebody
using the product and saying it was wrong.

### Foundations

**D-001 - Evidence is an append-only log; memory is a projection over it.**
*Alternative: mutate memory rows in place.* Mutation is simpler and loses four
things the brief asks for by name: per-case memory state, decision provenance, a
clean reset, and a reproducible evaluation. Cost: a rebuild step, and the
discipline of never writing to a projection table outside the projector.

**D-002 - A decision is a stack of independent policies.** *Alternative: one
scoring function.* Each policy returns a bounded contribution plus a rationale
plus a reason code. Three consequences a scoring function does not give:
ablations become a config list, a guard can veto regardless of score, and the
audit trail *is* the computation rather than a reconstruction of it.

**D-003 - Memory conditions the formatting prompt; substitution is the
fallback.** *Alternative: post-hoc find-and-replace.* Forced by the
`standing_instruction` class (A8): "always lowercase, even sentence-initial" and
"keep romanised, never translate" cannot be executed by any replace table.
Substitution remains as a deterministic fast path for exact observed variants,
and a verifier diffs the model's output to catch unauthorised edits.

**D-004 - Confidence is a Beta posterior, not a count.** *Alternative: an
integer evidence count with a threshold.* Negative evidence lives in the same
arithmetic instead of being a special case; decay makes an old memory
*uncertain* rather than *wrong*; and the number is calibratable. Cost: two
floats instead of one integer, and the obligation to publish the calibration.

**D-005 - Everything crossing a boundary is a Port, selected by config
string.** `ports/` holds Protocols; `adapters/` holds implementations; `engine/`
imports neither. The eval harness constructs an engine from a `Settings` object,
so an ablation is a serialisable value that gets embedded in the result file.

**D-006 - Cases before engine.** The Tier C fixtures and their integrity tests
were written before any engine code. `authored_before_engine` is a field on every
case and a test caps post-hoc additions at 20% (currently 11 of 84), which makes
"these were not chosen after the fact" checkable rather than asserted.

**D-007 - Deliberate non-goals.** Out of scope on purpose: episodic and semantic
memory; location-scoped memory; cross-user or team memory; ASR-side biasing
(this system stays strictly downstream of the recogniser so it can be evaluated
against any ASR); and trigger-phrase macro expansion, which is a different
feature with a different failure mode.

**D-008 - Scope dimensions are `global`, `app`, `persona`.** *Alternative: add
location.* Three dimensions produce every negative case in the taxonomy that
scope is responsible for. A fourth adds surface area without adding a failure
mode that could be demonstrated.

**D-012 - Single user.** No `user_id`. The schema has no tenancy column and the
API keeps one process-wide engine, which is what a single-user personal memory
needs. The projection design makes the migration mechanical if it is ever
needed: memory is derived from a log, so partitioning the log partitions
everything else.

### Retrieval and guards

**D-015 - Romanisation folding before phonetic keying.** *Alternative: rely on
metaphone alone.* Metaphone was designed for English and does not know that
`sh~s`, `th~t`, `aa~a`, `v~w` and word-final schwa are free variation in
romanised Indic names. Measured on 94 held-out mishearings: blocking recall
86.2% → 98.9%, end-to-end fix rate 36.2% → 72.3% (87.2% after D-023). Cost:
collisions against ordinary English words rose from 5 to 24 per 3,000 words,
which D-016 absorbs.

**D-016 - Common-word guards are synthesised, not written.** *Alternative:
hand-written guards per term.* A user does not curate guard lists. Guards are
derived from the memory itself, plus one decisive rule: **an ordinary English
word that the recogniser has never actually produced for a term is never
corrected**, whatever the context looks like. Measured on 4,000 sentences of
real English prose against a 367-term memory: 20 corruptions → 0.

**D-009 - Activation threshold: two observations.** `n = 2` within a single
scope; `declared` and `instruction` sources act at `n = 1`. The threshold sweep
(S3, §12) shows a plateau rather than a knife-edge.

**D-011 - What PROPOSE does.** A proposal changes no text and is surfaced as a
distinct verdict in the trace, the demo and the explorer, with its own reason
codes. The evaluation asserts `PROPOSE` on its own cases, so a system that
quietly collapsed propose into abstain would fail them. A user-facing review
queue is the obvious next surface and is not built.

**D-025 - A veto outranks a proposal in the reported reason.** When nothing is
applied, the headline reason should say what *stopped* it. Reporting the weakest
one hid a correctly-working `script_fit` veto behind an unrelated
single-observation proposal on a shorter span. A veto is a decision; "we have
only seen this once" is the absence of one.

### Evaluation

**D-022 - Two evaluation tiers, sized differently on purpose.** 69 hand-written
cases and 1,842 derived ones, in separate files with separate runners. The
hand-written tier is a specification - each case a judgement worth arguing about
singly - and writing three thousand of those would produce three thousand copies
of a dozen judgements. The derived tier is a measurement, and its expected
outcomes come from the construction rather than from engine behaviour, which is
the only thing that stops a large generated benchmark from being a suite that
cannot fail. Reported separately, always.

**D-017 - Ablate phonetics twice, because "no phonetics" is ambiguous.**
*This one changed a headline number.* Removing the policy leaves retrieval
running (65/69); swapping the encoder for `phonetics.null` removes retrieval too
(57/69). The first version of the table reported the weaker ablation under the
stronger name. §18, bug 10.

**D-014 - Licence: none.** No `LICENSE` file. This is a competition submission
provided for evaluation by the recipient; all rights are reserved and the README
says so. An open licence would invite reuse that is not intended here.

### Reversed by evidence

**D-010 - Scope-split evidence: made scope-agnostic.** Two corrections in two
applications now count toward the same activation rather than accruing
separately per scope. The conservative version was defensible in principle and
wrong in practice: a person who corrects a colleague's name once in Slack and
once in Mail has corrected it twice, and telling them otherwise is an
implementation detail leaking into the product. The L5-001 learning fixture was
updated to assert the new behaviour.

**D-018 - A seeded lexeme's confidence is a prior, not a value.** *This was a
bug, found by using the demo.* Pre-log evidence had nowhere to live, so
confirming a seeded term made the system **less** confident of it.
`Lexeme.prior` now holds it explicitly and the projection is `prior + log`;
migration `0002` adds the columns. §18, bug 11.

**D-023 - The romanisation fold is bidirectional.** *Found by slicing the derived
tier by confusion rule.* Derived tier 92.8% → 99.5% with zero new false
positives (§18, bug 13). Cost, stated rather than hidden: B7-002 changed from
silently ignoring the unknown name "Shreyas" to *proposing* "Shreya". The text is
still unchanged, which is what that class requires.

**D-024 - b/v is not a Bengali peculiarity.** Alternation applies in every script
that has both letters, not only the one that merged them (§18, bug 14). Tamil is
excluded, having only one labial approximant to confuse.

**D-026 - A binding records where evidence arrived, not where a name is
valid.** *Reversed by somebody using the demo.* An out-of-scope binding was an
absolute veto, so a name with an exact recorded mishearing went uncorrected
because a different window was in focus. The veto now applies only where the
binding is intrinsic - a channel handle, a service identifier. The argument and
the three cases that pin it are in §8.4. This is the only decision here that
required changing generated expectations: 69 derived cases asserted the old rule,
and the generator was rewritten rather than the cases edited.

### Open - deliberately not decided

**D-019 - Where the LLM adjudicator belongs.** The port exists, the stub
abstains, and the committed evaluation runs with zero model calls. The one
failing specification case (A8-002) shows where a model would earn its place: at
the *formatting* stage, acting on an instruction, not at the decision stage
choosing between candidates. Turning it on for that case alone would improve one
number and make every other number non-reproducible.

**D-020 - Per-script canonical forms.** A lexeme has one canonical spelling. A
user who writes a name in both Devanagari and Latin is currently served by
declining to convert (B18) rather than by holding both. A schema change, not an
architecture one, and the obvious next thing to build.

**D-021 - Where the common-word list should come from.**
`src/psm/data/common_words.txt` is a data file precisely so it can be replaced by
a proper frequency list, or better, by the recogniser's own vocabulary and
language-model priors. The guard mechanism does not care which; only the list's
coverage changes.

**D-013 - Disclosing the client teardown.** The publicly downloadable Kivi
installer was unpacked and its bundled application resources read, before
designing, to see what the shipping product's correction behaviour looks like.
No account was used, no service called, nothing modified or redistributed, and no
code from it appears here. It informed one thing in the taxonomy - that scope
binding is per-application - and is disclosed here and in the README rather than
left unsaid.

## 22. Reproducing the numbers

Every claim in this document is reproducible with one command, and `RUN.md` has
the full procedure with expected output. In short:

```bash
make install && make seed     # virtualenv, migrations, the 24-term persona
make serve                    # the demonstration page on :8000 (PORT overrides)
make eval                     # 69 specification + 15 learning cases
make eval-generated           # 1,842 derived cases, with the breakdown
make ablations                # all six ablations, exactly as committed
make stress                   # the six stress experiments
make explore                  # one browsable page covering both tiers
make test                     # 157 tests
```

Measuring one component's worth is a config change, not a code change:

```bash
python -m psm.cli eval --policies suppression,exact_variant --label my-ablation
python -m psm.cli eval --phonetics phonetics.null --label no-phonetics
```

If a number here disagrees with what those commands give you, the number here is
wrong.
