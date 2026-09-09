"""Grapheme-based phonetic encoding.

Double metaphone gives us two keys per token (a primary and an alternate for
plausible alternative pronunciations), which is exactly what we want for
*blocking*: cheap, high-recall bucketing so the scorer only ever looks at a
handful of candidates.

Scoring is a separate job and uses a weighted blend, because no single measure
survives contact with Indian names:

  - metaphone key agreement catches "Aadith"/"Adith" and "Kivi"/"kiwi"
  - Jaro-Winkler catches transpositions and shared prefixes, which matters
    because a mishearing usually gets the start of a name right
  - a normalised indel distance catches inserted or dropped vowels, the single
    most common difference between two romanisations of the same name

The blend weights live here rather than in config on purpose: they are a
property of *this* encoder. Swapping in an IPA or learned-embedding encoder
replaces the whole thing, weights included.
"""

from __future__ import annotations

import re

import jellyfish
from rapidfuzz.distance import Indel, JaroWinkler

from .indic import fold
from .indic_script import is_indic, readings

_NON_WORD = re.compile(r"[^\w\s'\-\u0900-\u0D7F]+", re.UNICODE)
_WS = re.compile(r"\s+")
#: Latin-script test. Native Indic text is transliterated first (see
#: `indic_script`), so by the time anything reaches metaphone it is ASCII. This
#: remains as a last-resort guard for scripts we do not handle at all - Arabic,
#: Han, Cyrillic - where abstaining is the right answer.
_LATIN = re.compile(r"^[\x00-\x7f'’\-\s]*$")

#: Minimum blocking-key length. Two is deliberate and was tuned against the
#: fixtures: soundex was the real source of gate noise (a fixed 4-character code
#: that collides across most of English), not short metaphone codes. Raising
#: this to three makes short product names like "Kivi" (metaphone "KF")
#: unindexable, so the near-miss cases the taxonomy exists to test would never
#: even be looked at.
_MIN_KEY_LEN = 2

#: Vowels stripped to form the consonant-skeleton key.
_VOWELS = re.compile(r"[aeiou]")


def romanise_for_compare(text: str) -> str:
    """The single Latin reading used for scoring (indexing uses all of them)."""
    if not is_indic(text):
        return text
    return readings(text)[0]


def normalise(text: str) -> str:
    """Casefold, strip surrounding punctuation, collapse whitespace.

    Used for exact variant lookup, so it must be stable and cheap. Internal
    hyphens and apostrophes are preserved because they distinguish real forms
    ("vaani-gateway", "Sarah's").
    """
    return _WS.sub(" ", _NON_WORD.sub(" ", text)).strip().casefold()


def is_latin(text: str) -> bool:
    return bool(_LATIN.match(text))


class DoubleMetaphoneEncoder:
    """Index keys. High recall, low precision - the scorer does the rest."""

    name = "dmetaphone"

    def encode(self, text: str) -> tuple[str, ...]:
        """Every blocking key for this form.

        Native Indic text yields several plausible Latin readings (script
        mergers, schwa deletion); romanised text yields exactly one. All of them
        go through the same fold and the same metaphone, which is what lets a
        name stored in Devanagari be found from a romanised spelling and the
        other way round.
        """
        keys: list[str] = []
        for reading in readings(text):
            norm = normalise(reading)
            if not norm or not is_latin(norm):
                continue
            for key in self._keys_for(norm):
                if key not in keys:
                    keys.append(key)
        return tuple(keys)

    def _keys_for(self, norm: str) -> list[str]:
        # Collapse romanisation variation BEFORE keying, so every spelling of
        # one Indic name lands in the same bucket. Measured: blocking recall on
        # held-out mishearings 86.2% -> 98.9%. See adapters/phonetics/indic.py.
        tokens = fold(norm.replace("-", " ")).split()
        # Key the whole phrase (so "vani gateway" blocks with "vaani-gateway")
        # and each token (so a single mis-segmented token still retrieves).
        chunks = (["".join(tokens)] if len(tokens) > 1 else []) + tokens
        # A consonant skeleton as an extra key. Scripts disagree about which
        # inherent vowels survive - Punjabi writes some that Hindi drops - so a
        # vowel-free key is what makes one name findable across all of them.
        # Cost, measured against 3,000 words of English prose: four collisions,
        # every one a common word the guard already protects.
        for chunk in list(chunks):
            skeleton = _VOWELS.sub("", chunk)
            if len(skeleton) >= 3 and skeleton != chunk:
                chunks.append(skeleton)

        keys: list[str] = []
        for chunk in chunks:
            try:
                key = jellyfish.metaphone(chunk)
            except (UnicodeDecodeError, ValueError):  # pragma: no cover
                continue
            # Keys shorter than two characters are near-useless as blocks:
            # soundex and very short metaphone codes collide across most of
            # English, which makes the gate pass on ordinary sentences and turns
            # the cheapest stage in the pipeline into the most expensive one.
            if len(key) >= _MIN_KEY_LEN and key not in keys:
                keys.append(key)
        return keys


class NullEncoder:
    """Ablation: no phonetics at all. Retrieval falls back to exact and fuzzy
    string matching only, which is precisely the comparison we want to publish."""

    name = "null"

    def encode(self, text: str) -> tuple[str, ...]:
        return ()


class BlendedComparator:
    """Distance in [0, 1]. 0.0 = indistinguishable."""

    name = "blended"

    #: metaphone agreement, prefix/transposition similarity, vowel-drift
    WEIGHTS = (0.40, 0.35, 0.25)

    def _keys(self, text: str) -> set[str]:
        tokens = fold(normalise(romanise_for_compare(text)).replace("-", " ")).split()
        joined = "".join(tokens)
        out = set()
        for chunk in (joined, *tokens):
            if chunk:
                out.add(jellyfish.metaphone(chunk))
        return {k for k in out if k}

    def distance(self, a: str, b: str) -> float:
        """Best distance over every plausible reading of each side.

        Native script is romanised first, so a Devanagari lexeme and a romanised
        query are scored on one alphabet. Where a script is ambiguous - Bengali
        writes /b/ and /v/ with one letter - both readings are tried and the
        closest wins. Taking the first reading instead scored a correct Bengali
        match at 0.52 and lost it.
        """
        return min(
            self._distance(x, y) for x in readings(a) for y in readings(b)
        )

    def _distance(self, a: str, b: str) -> float:
        na, nb = normalise(a), normalise(b)
        if not na or not nb:
            return 1.0
        if na == nb:
            return 0.0
        if not (is_latin(na) and is_latin(nb)):
            return 1.0

        ka, kb = self._keys(a), self._keys(b)
        if ka and kb:
            key_sim = len(ka & kb) / len(ka | kb)
        else:
            key_sim = 0.0

        # Compare with spaces and hyphens removed, so segmentation differences
        # ("grad cam" vs "Grad-CAM") cost nothing at the string level - that is
        # the whole point of the segmentation class.
        flat_a = na.replace("-", "").replace(" ", "")
        flat_b = nb.replace("-", "").replace(" ", "")
        if flat_a == flat_b:
            return 0.0

        jw = JaroWinkler.similarity(flat_a, flat_b)
        indel = 1.0 - Indel.normalized_distance(flat_a, flat_b)

        w1, w2, w3 = self.WEIGHTS
        similarity = w1 * key_sim + w2 * jw + w3 * indel
        return max(0.0, min(1.0, 1.0 - similarity))

    def similarity(self, a: str, b: str) -> float:
        return 1.0 - self.distance(a, b)


class PhoneticStack:
    """A named encoder plus a comparator, resolved from config.

    Exists so `PSM_PHONETICS=phonetics.null` is a complete ablation
    rather than a branch inside the retriever.
    """

    def __init__(self, encoder=None, comparator=None) -> None:
        self.encoder = encoder or DoubleMetaphoneEncoder()
        self.comparator = comparator or BlendedComparator()

    @property
    def name(self) -> str:
        return f"{self.encoder.name}+{self.comparator.name}"

    def keys(self, text: str) -> tuple[str, ...]:
        return self.encoder.encode(text)

    def distance(self, a: str, b: str) -> float:
        return self.comparator.distance(a, b)
