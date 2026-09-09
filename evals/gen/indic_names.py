"""Names in native Indic scripts, and the confusion rules that apply to them.

Two things live here, and the second is the interesting one.

**The names** are written in their own scripts rather than transliterated from
Latin. A generator that romanised and then back-transliterated would be testing
the transliterator, and would produce spellings no person actually writes.

There are 42 of them, four to eight per script, and they are chosen rather than
sampled: each script's set is picked to contain the features that script's own
rules can act on - aspirate pairs, retroflex/dental contrasts, long vowels,
conjuncts, and the b/v letters where the script has both. A random sample of
Indian names would leave several rules with nothing to fire on and would make
the per-script breakdown meaningless. The selection is therefore a stated bias
towards *coverage of the confusion rules*, not towards frequency; what it buys
is that every rule below is exercised in every script that can express it, and
what it costs is that these numbers say nothing about how common each name is.

**The rules are expressed as offsets from a block base, not as characters.**
The nine Unicode blocks this system supports are ISCII-aligned: the same
consonant sits at the same offset in Devanagari (0x0900), Bengali (0x0980),
Gujarati (0x0A80) and so on. So "an aspirated consonant is heard as its plain
counterpart" is one rule - `+1` at the aspirate offsets - and it holds in every
script at once. That is the same observation the *encoder* is built on
(`adapters/phonetics/indic_script.py` maps nine blocks through one table), so
the generator and the system under test share a premise, and if the premise is
wrong both are wrong together and the tests say so.

Scripts differ in what they contain, and the rules degrade accordingly: Tamil has
no aspirate series at all, so aspirate rules simply do not fire on Tamil names
and that script's cases exercise vowel length and sibilants instead. That is a
property of Tamil, not a gap in the generator.
"""

from __future__ import annotations

import unicodedata

# Offsets are from each block's base. See indic_script.BLOCK_BASES.
BLOCK_BASES = {
    "devanagari": 0x0900,
    "bengali": 0x0980,
    "gurmukhi": 0x0A00,
    "gujarati": 0x0A80,
    "odia": 0x0B00,
    "tamil": 0x0B80,
    "telugu": 0x0C00,
    "kannada": 0x0C80,
    "malayalam": 0x0D00,
}

#: (offset_a, offset_b, why). Applied in both directions.
#: Every pair is a real confusion between Indic phonology and what a recogniser
#: trained mostly on English will reach for.
CONSONANT_PAIRS: tuple[tuple[int, int, str], ...] = (
    (0x15, 0x16, "ka/kha - aspiration is not heard"),
    (0x17, 0x18, "ga/gha - aspiration is not heard"),
    (0x1A, 0x1B, "ca/cha - aspiration is not heard"),
    (0x1C, 0x1D, "ja/jha - aspiration is not heard"),
    (0x1F, 0x20, "tta/ttha - retroflex aspiration"),
    (0x21, 0x22, "dda/ddha - retroflex aspiration"),
    (0x24, 0x25, "ta/tha - the single most common Indic name error"),
    (0x26, 0x27, "da/dha - aspiration is not heard"),
    (0x2A, 0x2B, "pa/pha - aspiration is not heard"),
    (0x2C, 0x2D, "ba/bha - aspiration is not heard"),
    (0x1F, 0x24, "retroflex tta heard as dental ta"),
    (0x21, 0x26, "retroflex dda heard as dental da"),
    (0x23, 0x28, "retroflex nna heard as dental na"),
    (0x36, 0x38, "sha heard as sa - palatal sibilant flattened"),
    (0x37, 0x38, "ssa heard as sa - retroflex sibilant flattened"),
    (0x2C, 0x35, "ba/va - the Bengali merger, and common elsewhere"),
)

#: Vowel signs (matras). Length is the thing casual dictation does not respect.
VOWEL_PAIRS: tuple[tuple[int, int, str], ...] = (
    (0x3F, 0x40, "short i / long ii"),
    (0x41, 0x42, "short u / long uu"),
    (0x47, 0x48, "e / ai"),
    (0x4B, 0x4C, "o / au"),
)

#: The long-a matra, which is often simply dropped.
MATRA_AA = 0x3E

#: Names, in their own scripts. Kept short and real: these are the kinds of
#: names a colleague list actually contains. `latin` is documentation for a
#: reader who does not read the script - the system never sees it.
NAMES: dict[str, tuple[tuple[str, str], ...]] = {
    "devanagari": (
        ("मीरा शर्मा", "Meera Sharma"),
        ("अनिरुद्ध देशपांडे", "Anirudh Deshpande"),
        ("भावना कुलकर्णी", "Bhavana Kulkarni"),
        ("प्रणव जोशी", "Pranav Joshi"),
        ("ऋतुजा गोखले", "Rutuja Gokhale"),
        ("शार्दूल पाटील", "Shardul Patil"),
        ("वैष्णवी राणे", "Vaishnavi Rane"),
        ("धैर्यशील मोरे", "Dhairyasheel More"),
    ),
    "bengali": (
        ("সুদীপ্ত মুখার্জি", "Sudipta Mukherjee"),
        ("অনিন্দিতা ঘোষাল", "Anindita Ghoshal"),
        ("দেবজ্যোতি সেনগুপ্ত", "Debojyoti Sengupta"),
        ("রূপসা চক্রবর্তী", "Rupsa Chakraborty"),
        ("শুভঙ্কর বন্দ্যোপাধ্যায়", "Shubhankar Bandyopadhyay"),
        ("তিতাস ভট্টাচার্য", "Titas Bhattacharya"),
    ),
    "gurmukhi": (
        ("ਹਰਪ੍ਰੀਤ ਸਿੰਘ", "Harpreet Singh"),
        ("ਜਸਲੀਨ ਕੌਰ", "Jasleen Kaur"),
        ("ਮਨਦੀਪ ਗਿੱਲ", "Mandeep Gill"),
        ("ਸਿਮਰਨਜੀਤ ਸੰਧੂ", "Simranjit Sandhu"),
    ),
    "gujarati": (
        ("પ્રિયંકા મહેતા", "Priyanka Mehta"),
        ("હાર્દિક પટેલ", "Hardik Patel"),
        ("નિશા દેસાઈ", "Nisha Desai"),
        ("કૃણાલ ઠક્કર", "Krunal Thakkar"),
    ),
    "odia": (
        ("ସୁବ୍ରତ ମହାପାତ୍ର", "Subrata Mohapatra"),
        ("ଅନ୍ୱେଷା ସାହୁ", "Anwesha Sahu"),
        ("ଦେବାଶିଷ ପଣ୍ଡା", "Debashish Panda"),
    ),
    "tamil": (
        ("கார்த்திகேயன்", "Karthikeyan"),
        ("மீனாட்சி சுந்தரம்", "Meenakshi Sundaram"),
        ("இளங்கோ ராமன்", "Ilango Raman"),
        ("தமிழ்செல்வி", "Tamilselvi"),
        ("வெங்கடேசன்", "Venkatesan"),
    ),
    "telugu": (
        ("శ్రీనివాస్ రెడ్డి", "Srinivas Reddy"),
        ("పద్మజ రావు", "Padmaja Rao"),
        ("వెంకటేశ్వర్లు", "Venkateswarlu"),
        ("అనూష చౌదరి", "Anusha Chowdary"),
    ),
    "kannada": (
        ("ಮಂಜುನಾಥ ಶೆಟ್ಟಿ", "Manjunath Shetty"),
        ("ಶ್ವೇತಾ ಗೌಡ", "Shwetha Gowda"),
        ("ಪ್ರಶಾಂತ ಹೆಗಡೆ", "Prashanth Hegde"),
        ("ಚಂದ್ರಶೇಖರ", "Chandrashekar"),
    ),
    "malayalam": (
        ("അനഘ നായർ", "Anagha Nair"),
        ("വിഷ്ണു മേനോൻ", "Vishnu Menon"),
        ("ലക്ഷ്മി പിള്ള", "Lakshmi Pillai"),
        ("ദേവദത്ത് കുറുപ്പ്", "Devadatt Kurup"),
    ),
}

#: Carrier sentences, per script, so a generated case is a sentence rather than
#: a bare name. `{}` is where the name goes. Written by hand in each script;
#: none of them contains anything the system should touch except the name.
CARRIERS: dict[str, tuple[str, ...]] = {
    "devanagari": ("{} को यह भेज दो।", "{} ने कल यह ठीक किया।", "क्या {} इसे देख सकते हैं?"),
    "bengali": ("{} কে এটা পাঠিয়ে দাও।", "{} কাল এটা ঠিক করেছে।"),
    "gurmukhi": ("{} ਨੂੰ ਇਹ ਭੇਜ ਦਿਓ।", "{} ਨੇ ਕੱਲ੍ਹ ਇਹ ਠੀਕ ਕੀਤਾ।"),
    "gujarati": ("{} ને આ મોકલી દો.", "{} એ ગઈકાલે આ સુધાર્યું."),
    "odia": ("{} ଙ୍କୁ ଏହା ପଠାଇ ଦିଅ।", "{} ଏହା କାଲି ଠିକ୍ କଲେ।"),
    "tamil": ("{} இதை பாருங்கள்.", "{} நேற்று இதை சரி செய்தார்."),
    "telugu": ("{} కి ఇది పంపండి.", "{} నిన్న దీన్ని సరిచేశారు."),
    "kannada": ("{} ಗೆ ಇದನ್ನು ಕಳುಹಿಸಿ.", "{} ನಿನ್ನೆ ಇದನ್ನು ಸರಿಪಡಿಸಿದರು."),
    "malayalam": ("{} ന് ഇത് അയക്കൂ.", "{} ഇന്നലെ ഇത് ശരിയാക്കി."),
}


def _offset(char: str, base: int) -> int | None:
    point = ord(char) - base
    return point if 0 <= point <= 0x7F else None


def _assigned(base: int, offset: int) -> bool:
    """Is this code point a real letter in this script?

    The blocks are aligned but they are not identical: Tamil has no aspirate
    series, so the offsets that hold `kha` and `tha` in Devanagari are simply
    unassigned there. Without this check the generator produces code points
    that no font renders and no person could ever have typed - a benchmark made
    of characters that do not exist, which would be worse than no benchmark.
    """
    try:
        unicodedata.name(chr(base + offset))
    except ValueError:
        return False
    return True


def perturb(name: str, script: str, rule_index: int) -> tuple[str, str] | None:
    """Apply one confusion rule to `name`, deterministically.

    `rule_index` selects the rule and the occurrence, so the same index always
    produces the same mishearing - which is what makes the generated suite
    reproducible without storing it as an opaque blob.

    Returns `(misheard, why)`, or None when the rule does not apply to this
    name in this script (Tamil has no aspirates; a name may contain neither
    member of a pair). A rule that cannot fire is skipped, never faked.
    """
    base = BLOCK_BASES[script]
    rules = [(a, b, why) for a, b, why in CONSONANT_PAIRS] + [
        (a, b, why) for a, b, why in VOWEL_PAIRS
    ] + [(MATRA_AA, None, "the long-a matra is dropped")]

    rule = rules[rule_index % len(rules)]
    left, right, why = rule

    positions = []
    for index, char in enumerate(name):
        offset = _offset(char, base)
        if offset is None:
            continue
        if offset == left:
            positions.append((index, right))
        elif right is not None and offset == right:
            positions.append((index, left))
    if not positions:
        return None

    positions = [
        (index, replacement)
        for index, replacement in positions
        if replacement is None or _assigned(base, replacement)
    ]
    if not positions:
        return None

    index, replacement = positions[(rule_index // len(rules)) % len(positions)]
    if replacement is None:
        out = name[:index] + name[index + 1 :]
    else:
        out = name[:index] + chr(base + replacement) + name[index + 1 :]
    return (out, why) if out != name else None


def every_name() -> list[tuple[str, str, str]]:
    """(script, native form, latin gloss) for every committed name."""
    return [
        (script, native, latin)
        for script, entries in NAMES.items()
        for native, latin in entries
    ]
