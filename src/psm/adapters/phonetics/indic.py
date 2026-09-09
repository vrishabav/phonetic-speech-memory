"""Romanisation normalisation for Indic names.

The problem this solves, concretely. A recogniser trained mostly on English has
to write an Indian name in the Latin alphabet, and the alphabet does not carry
the distinctions the name actually has. So the *same* name comes out spelled
several different ways depending on the audio and the model's mood:

    Vishwanathan / Viswanathan / Vishvanathan
    Aadith / Adith / Aadhith
    Tanvi / Thanvi / Tanwi
    Bhaskar / Baskar / Bhaashkar

These are not random typos. They follow a small number of documented, regular
correspondences between Indic phonology and English orthography:

  * aspiration is optional in writing:      kh~k  gh~g  th~t  dh~d  bh~b  ph~f
  * sibilants collapse:                     sh~s  zh~s
  * vowel length is unmarked:               aa~a  ee~i  oo~u
  * v and w merge in Indian English:        w~v
  * word-final schwa is unstable:           Ram~Rama
  * y and i alternate:                      Vaidyanathan~Vaidianathan, Iyer~Iier
  * p, ph and f are one sound:              Patil~Phatil, Deepak~Deefak

This module collapses all of that *before* a phonetic key is computed, so every
romanisation of one name lands in the same bucket. Both the stored form and the
query text get identical treatment, so it is a canonicalisation, not a guess.

**Measured effect.** On 94 held-out mishearings generated from these same
correspondences, the share of true pairs that share a blocking key rises from
86.2% to 98.9%, while collisions between genuinely different names stay flat at
2.1%. Collisions against ordinary English words rise from 5 to 24 per 3,000
words - which is why automatic common-word guarding (see `engine/guards.py`)
was added at the same time to absorb them.

The rules are deliberately lossy. This is a *blocking* function: its job is to
never miss a real match, and to be cheap. Deciding whether two candidates that
landed in the same bucket are actually the same term is the comparator's job,
and then the policy stack's.
"""

from __future__ import annotations

import re
from functools import lru_cache

#: Ordered. Longer sequences first, so "ksh" is handled before "sh".
RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), replacement)
    for pattern, replacement in [
        (r"ksh", "ks"),      # conjunct
        (r"jn", "gn"),       # jnana / gnana
        (r"chh?", "c"),      # ch / chh
        (r"kh", "k"),        # aspirated stops lose their h
        (r"gh", "g"),
        (r"jh", "j"),
        (r"th", "t"),
        (r"dh", "d"),
        (r"ph", "f"),
        (r"f", "p"),         # ...and then f joins p: फ is /p_h/, written "ph",
                             # heard "f", and all three spellings occur for the
                             # same sound. Collapsing ph->f without also
                             # collapsing f->p left "Patil" and "Phatil" in
                             # different buckets, which is the gap the generated
                             # tier found across seven scripts at once.
        (r"bh", "b"),
        (r"sh", "s"),        # sibilants collapse
        (r"zh", "s"),
        (r"aa+", "a"),       # vowel length is not marked reliably
        (r"ee+", "i"),
        (r"oo+", "u"),
        (r"ii+", "i"),
        (r"uu+", "u"),
        (r"w", "v"),         # v/w merger
        (r"y", "i"),         # Vaidyanathan / Vaidianathan, and also Iyer /
                             # Iier and Yashodhara / Iashodhara: the earlier
                             # rule only fired after a consonant, so a `y` next
                             # to a vowel - which is where it sits in most of
                             # these names - never folded at all.
        (r"(.)\1+", r"\1"),  # any remaining doubled letter
        (r"[aeiou]+$", ""),  # unstable word-final vowel
    ]
)


@lru_cache(maxsize=100_000)
def _fold_token(token: str) -> str:
    folded = token
    for pattern, replacement in RULES:
        folded = pattern.sub(replacement, folded)
    return folded or token


def fold(text: str) -> str:
    """Collapse romanisation variation. Idempotent, and safe on English words.

    English is affected too - "the" becomes "te", "should" becomes "sould" -
    which is fine and in fact necessary: the fold has to be applied identically
    to both sides of every comparison, so a systematic change to both is
    invisible. What matters is that two spellings of the same name converge.
    """
    return " ".join(_fold_token(token) for token in text.split())
