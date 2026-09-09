"""Native Indic scripts, reduced to a comparable form.

Kivi dictates in 22 Indian languages, so the memory has to work when the text
is Devanagari, Tamil, Telugu, Bengali - not only when it is romanised. Three
things have to be true, and this module makes all three true with one table.

**1. Two spellings of one word in the same script must match.**
`ठीक` and `ठिक` differ only in vowel length, which Devanagari marks and casual
typing does not respect.

**2. A word must match across scripts.**
The same person dictating Hindi may get `ठीक है` on Monday and `theek hai` on
Tuesday, depending on the recogniser's transliteration mode. To the memory
those are one term, not two.

**3. None of the English machinery may break.**
Metaphone raises or returns nonsense on non-ASCII input, so nothing downstream
can see a Devanagari character.

All three fall out of the same move: **transliterate to Latin first**, then run
the existing romanisation fold and metaphone over the result. The fold is not a
liability here - it is exactly right, because the choice between `ee` and `i`
when romanising `ी` is arbitrary, and the fold is what makes arbitrary choices
stop mattering.

### One table for nine scripts

The Indic Unicode blocks are ISCII-derived and **aligned by design**: the same
offset means the same sound in every block.

    क U+0915   ক U+0995   ਕ U+0A15   ક U+0A95   କ U+0B15
    க U+0B95   క U+0C15   ಕ U+0C95   ക U+0D15      all offset 0x15 = KA

Verified across nine blocks and thirteen probe characters: 116 of 117 align.
(The exception is Tamil having no separate letter for GA, which is a property
of the writing system, not a gap in the mapping.)

So any Indic character is mapped to its Devanagari equivalent by subtracting
its block base, and a single Devanagari table does the rest.

### What this is and is not

This is a **phonetic blocking function**, not a transliteration library. Its job
is to put things that sound alike into the same bucket, cheaply and without
ever missing a real match. `स्` and `श्` both becoming `s` would be wrong in a
transliterator and is correct here, because a recogniser confuses them
constantly. Deciding whether two things in one bucket are really the same term
is the comparator's job, and then the policy stack's.
"""

from __future__ import annotations

import re
from functools import lru_cache

#: Block base for every Indic script that follows the ISCII layout.
BLOCK_BASES: tuple[int, ...] = (
    0x0900,  # Devanagari - Hindi, Marathi, Nepali, Konkani, Sanskrit
    0x0980,  # Bengali    - Bengali, Assamese
    0x0A00,  # Gurmukhi   - Punjabi
    0x0A80,  # Gujarati
    0x0B00,  # Odia
    0x0B80,  # Tamil
    0x0C00,  # Telugu
    0x0C80,  # Kannada
    0x0D00,  # Malayalam
)

#: Independent vowels, at offsets 0x05-0x14.
VOWELS: dict[int, str] = {
    0x05: "a", 0x06: "aa", 0x07: "i", 0x08: "ii", 0x09: "u", 0x0A: "uu",
    0x0B: "ri", 0x0C: "lri", 0x0D: "e", 0x0E: "e", 0x0F: "e", 0x10: "ai",
    0x11: "o", 0x12: "o", 0x13: "o", 0x14: "au",
    0x60: "ri", 0x61: "lri",
}

#: Vowel signs (matras), 0x3E-0x4C. They replace a consonant's inherent vowel.
MATRAS: dict[int, str] = {
    0x3E: "aa", 0x3F: "i", 0x40: "ii", 0x41: "u", 0x42: "uu", 0x43: "ri",
    0x44: "ri", 0x45: "e", 0x46: "e", 0x47: "e", 0x48: "ai",
    0x49: "o", 0x4A: "o", 0x4B: "o", 0x4C: "au",
    0x62: "ri", 0x63: "lri",
}

#: Consonants, 0x15-0x39. Every one carries an inherent "a" unless a matra or
#: a virama follows.
CONSONANTS: dict[int, str] = {
    0x15: "k",  0x16: "kh", 0x17: "g",  0x18: "gh", 0x19: "ng",
    0x1A: "ch", 0x1B: "chh", 0x1C: "j", 0x1D: "jh", 0x1E: "ny",
    0x1F: "t",  0x20: "th", 0x21: "d",  0x22: "dh", 0x23: "n",
    0x24: "t",  0x25: "th", 0x26: "d",  0x27: "dh", 0x28: "n",
    0x29: "n",  0x2A: "p",  0x2B: "ph", 0x2C: "b",  0x2D: "bh", 0x2E: "m",
    0x2F: "y",  0x30: "r",  0x31: "r",  0x32: "l",  0x33: "l",  0x34: "l",
    0x35: "v",  0x36: "sh", 0x37: "sh", 0x38: "s",  0x39: "h",
    # Nukta forms used for Perso-Arabic and English loans.
    0x58: "k", 0x59: "kh", 0x5A: "g", 0x5B: "j", 0x5C: "d", 0x5D: "dh",
    0x5E: "f", 0x5F: "y",
    # Block-extension letters some scripts use for sounds the base range lacks.
    0x71: "v",   # Odia WA
    0x72: "a", 0x73: "i", 0x74: "u",
}

#: A nukta modifies the PRECEDING consonant rather than standing alone. In
#: Gurmukhi it is how the script writes sounds Punjabi borrowed from Persian and
#: English, so skipping it turns "vishvanathan" into "visavanathana".
NUKTA_FORMS: dict[str, str] = {
    "s": "sh", "k": "kh", "g": "g", "j": "z", "d": "r", "dh": "rh",
    "ph": "f", "p": "f", "t": "t", "n": "n", "y": "y",
}

#: Letters whose reading is genuinely ambiguous. Blocking is allowed to be
#: generous - both readings are emitted and the comparator decides - so the
#: cost of listing one is a slightly wider bucket, and the cost of omitting one
#: is a name that can never be found.
#:
#: **b/v is not a Bengali peculiarity.** Bengali and Assamese merged /v/ into
#: /b/ outright, which is why ব was listed first; but the same confusion is
#: routine wherever a recogniser has to choose between ब and व, and the
#: generated tier found it failing identically in Devanagari, Telugu, Odia and
#: Malayalam - भाबना for भावना, బెంకటేశ్వర్లు for వెంకటేశ్వర్లు, ബിഷ്ണു for വിഷ്ണു.
#: Eight of the nine remaining failures in that tier were this one letter.
_B_AS_V = {0x2C: "v"}   # ब / ব / ਬ ... read as v
_V_AS_B = {0x35: "b"}   # व / ব-adjacent व-slot ... read as b

SCRIPT_AMBIGUITY: dict[int, dict[int, str]] = {
    base: {**_B_AS_V, **_V_AS_B}
    for base in (0x0900, 0x0980, 0x0A00, 0x0A80, 0x0B00, 0x0C00, 0x0C80, 0x0D00)
}
# Tamil (0x0B80) is deliberately absent: it has no ब/व distinction to confuse -
# வ is the only labial approximant in the script - so an alternate reading there
# would widen the bucket for nothing.

VIRAMA = 0x4D          # suppresses the inherent vowel
ANUSVARA = 0x02        # nasalisation
CANDRABINDU = 0x01
VISARGA = 0x03
NUKTA = 0x3C
DIGITS = range(0x66, 0x70)

#: Any codepoint inside one of the nine blocks.
_INDIC_RANGE = re.compile(r"[ऀ-ൿ]")


def is_indic(text: str) -> bool:
    """Does this text contain any native Indic character?"""
    return bool(_INDIC_RANGE.search(text))


def _locate(char: str) -> tuple[int, int] | None:
    """(block base, offset within block), or None if this is not Indic."""
    code = ord(char)
    for base in BLOCK_BASES:
        if base <= code < base + 0x80:
            return base, code - base
    return None


@lru_cache(maxsize=100_000)
def transliterate(
    text: str,
    *,
    alternate: bool = False,
    drop_schwa: bool = False,
    swap: int = -1,
) -> str:
    """Indic script to a rough Latin phonetic form.

    Deliberately lossy in exactly the places a recogniser is unreliable:
    retroflex and dental stops collapse, both sibilants become `sh`, and
    nasalisation becomes a plain `n`. The romanisation fold then collapses
    aspiration and vowel length on top of that.

    Non-Indic characters pass through untouched, so mixed text - which is what
    code-switched dictation actually looks like - works without a separate path.
    """
    out: list[str] = []
    inherent_at: set[int] = set()  # indices in `out` that are inserted schwas
    pending_inherent = False       # a consonant is waiting for its vowel
    # `swap` is a bitmask over the ambiguous letters in this word, counted left
    # to right. `alternate=True` is the "swap everything" case and stays for
    # compatibility; a mask lets a word with two ambiguous letters produce the
    # four readings it actually needs rather than only the all-or-nothing pair.
    ambiguous_seen = 0

    def emit_inherent() -> None:
        inherent_at.add(len(out))
        out.append("a")

    for char in text:
        located = _locate(char)
        if located is None:
            if pending_inherent:
                emit_inherent()
                pending_inherent = False
            out.append(char)
            continue

        base, offset = located
        if offset in CONSONANTS:
            if pending_inherent:
                emit_inherent()
            sound = CONSONANTS[offset]
            swapped = SCRIPT_AMBIGUITY.get(base, {}).get(offset)
            if swapped is not None:
                take = alternate if swap < 0 else bool(swap >> ambiguous_seen & 1)
                ambiguous_seen += 1
                if take:
                    sound = swapped
            out.append(sound)
            pending_inherent = True
        elif offset in MATRAS:
            out.append(MATRAS[offset])
            pending_inherent = False
        elif offset == VIRAMA:
            pending_inherent = False
        elif offset in VOWELS:
            if pending_inherent:
                emit_inherent()
                pending_inherent = False
            out.append(VOWELS[offset])
        elif offset in (ANUSVARA, CANDRABINDU):
            if pending_inherent:
                emit_inherent()
                pending_inherent = False
            out.append("n")
        elif offset == VISARGA:
            if pending_inherent:
                emit_inherent()
                pending_inherent = False
            out.append("h")
        elif offset in DIGITS:
            if pending_inherent:
                emit_inherent()
                pending_inherent = False
            out.append(str(offset - 0x66))
        elif offset == NUKTA:
            # Modify the consonant just emitted; do NOT touch pending_inherent,
            # which still belongs to that consonant.
            if out and out[-1] in NUKTA_FORMS:
                out[-1] = NUKTA_FORMS[out[-1]]
        else:
            if pending_inherent:
                emit_inherent()
                pending_inherent = False

    if pending_inherent:
        emit_inherent()
    if drop_schwa:
        # Hindi, Punjabi and Bengali delete most inherent schwas in speech even
        # though the script still writes them: "vishwanathan", not
        # "vi-sha-va-na-tha-na". Which ones survive is a genuinely hard rule, so
        # this emits the fully-deleted reading as an ADDITIONAL blocking key
        # rather than trying to be right about it.
        return "".join(c for i, c in enumerate(out) if i not in inherent_at)
    return "".join(out)


def romanise(text: str) -> str:
    """Transliterate if there is anything to transliterate; otherwise pass through.

    Cheap enough to call unconditionally - the check is one regex over a short
    string, and it keeps every caller free of script-detection logic.
    """
    return transliterate(text) if is_indic(text) else text


#: How many ambiguous letters get the full combinatorial treatment. Three means
#: at most eight readings before schwa variants double it.
_MAX_AMBIGUOUS = 3


@lru_cache(maxsize=100_000)
def _ambiguous_count(text: str) -> int:
    total = 0
    for char in text:
        located = _locate(char)
        if located and located[1] in SCRIPT_AMBIGUITY.get(located[0], {}):
            total += 1
    return total


def readings(text: str) -> tuple[str, ...]:
    """Every plausible Latin reading of `text`, for indexing.

    Usually one. More when the script merges a distinction another script keeps -
    ब/व is read both ways almost everywhere - so a name indexed from one
    spelling has to be findable from the other.

    Every *combination* of the ambiguous letters is emitted, not just
    all-or-nothing. That matters for real names: वैष्णवी and वेंकटेश्वर्लु each
    contain two `व`, and the all-or-nothing pair produced "vaishnavi"/"baishnabi"
    while the recogniser's actual error is "baishnavi" - one letter, not both.
    Those two words were the last failures in the generated tier and they failed
    for exactly this reason.

    Capped at `_MAX_AMBIGUOUS` positions (8 readings before schwa variants). The
    cap exists because this is a *blocking* function: a bucket that grows without
    limit costs latency on every utterance, and beyond a couple of ambiguous
    letters the comparator is the right tool anyway.

    Blocking may be generous; precision is the comparator's problem.
    """
    if not is_indic(text):
        return (text,)
    positions = min(_ambiguous_count(text), _MAX_AMBIGUOUS)
    out: list[str] = []
    for swap in range(1 << positions):
        for drop_schwa in (False, True):
            reading = transliterate(text, drop_schwa=drop_schwa, swap=swap)
            if reading and reading not in out:
                out.append(reading)
    return tuple(out)
