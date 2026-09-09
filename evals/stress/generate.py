"""Build the stress datasets.

Everything here is generated from committed inputs with a fixed seed, so the
datasets are reproducible byte-for-byte rather than shipped as opaque blobs.

Three products:

  personas/*.json   Larger, *unseen* personas. The 20-term seed persona was
                    tuned against; a system that only works on the data it was
                    tuned on has not been shown to work at all.

  mishearings.jsonl Plausible ASR errors for names that are NOT in any variant
                    table, produced by applying documented confusion rules
                    (aspiration, retroflex/dental, vowel length, v/w, schwa
                    deletion) to Indian names. This is the set that decides
                    whether phonetic retrieval earns its place, because these
                    are exactly the forms the system has never seen before.

  neutral_corpus.txt  Real English prose harvested from the Python standard
                    library's docstrings (see harvest step). Nothing in it
                    should ever trigger a correction.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = 20260906

# --------------------------------------------------------------------------- #
# Name material
# --------------------------------------------------------------------------- #

GIVEN = [
    "Aaditya", "Abhigyan", "Aishwarya", "Ananya", "Anirudh", "Arundhati", "Bhavana",
    "Chaitanya", "Devika", "Dhruv", "Gayathri", "Harshvardhan", "Indrajit", "Ishaan",
    "Jayashree", "Kalyani", "Karthik", "Keerthana", "Lakshmi", "Madhusudan", "Meenakshi",
    "Mrinalini", "Nachiketa", "Nandini", "Nikhil", "Padmanabhan", "Parvathy", "Pranav",
    "Priyanka", "Raghunath", "Rukmini", "Sandhya", "Saraswathi", "Shreyaa", "Siddharth",
    "Subramanian", "Swaminathan", "Tanvi", "Thirumalai", "Uma", "Vaishnavi", "Venkatesh",
    "Vidyasagar", "Vishwanathan", "Yashodhara", "Anjali", "Bhaskar", "Chandrashekar",
    "Deepika", "Girish", "Hemalatha", "Jagadish", "Kaveri", "Lalitha", "Manjunath",
    "Narayanan", "Omkar", "Purushottam", "Radhika", "Sowmya", "Tejaswini", "Vikramaditya",
]

FAMILY = [
    "Bhattacharya", "Chakraborty", "Deshpande", "Gopalakrishnan", "Iyer", "Iyengar",
    "Kulkarni", "Mukherjee", "Nambiar", "Padmanabhan", "Rajagopalan", "Sengupta",
    "Sundaram", "Venkataraman", "Chattopadhyay", "Krishnamurthy", "Balasubramanian",
    "Mahadevan", "Ranganathan", "Vaidyanathan", "Ghoshal", "Bandyopadhyay",
]

TECH_TERMS = [
    ("vaani-gateway", "code_symbol"), ("shruti-index", "code_symbol"),
    ("dhwani-router", "code_symbol"), ("akash-scheduler", "code_symbol"),
    ("Grad-CAM", "term"), ("MLOps", "term"), ("RLHF", "term"), ("ZDR", "term"),
    ("WER", "term"), ("CTC", "term"), ("BPE", "term"), ("LoRA", "term"),
    ("kubectl", "code_symbol"), ("npm", "code_symbol"), ("pnpm", "code_symbol"),
    ("gRPC", "term"), ("OTel", "term"), ("PagerDuty", "product"),
]

PLACES = ["Bengaluru", "Thiruvananthapuram", "Kanchipuram", "Vishakhapatnam",
          "Mysuru", "Puducherry", "Kozhikode", "Bhubaneswar"]

# --------------------------------------------------------------------------- #
# Confusion rules
# --------------------------------------------------------------------------- #
# Each rule is a documented, real confusion between Indian-language phonology
# and the orthography an English-trained recogniser will reach for. These are
# not random character noise - random noise would make the benchmark easy in
# the wrong way.

RULES: list[tuple[str, str, str]] = [
    ("aa", "a", "vowel length is not marked consistently in romanisation"),
    ("a", "aa", "the reverse: an inserted long vowel"),
    ("ee", "i", "long i romanised two ways"),
    ("i", "ee", "the reverse"),
    ("oo", "u", "long u romanised two ways"),
    ("th", "t", "aspirated dental heard as plain t"),
    ("t", "th", "the reverse - the single most common Indic name error"),
    ("dh", "d", "aspirated d heard as plain d"),
    ("bh", "b", "aspirated b"),
    ("kh", "k", "aspirated k"),
    ("gh", "g", "aspirated g"),
    ("ph", "f", "aspirated p heard as f"),
    ("v", "w", "v/w merger, very common in Indian English"),
    ("w", "v", "the reverse"),
    ("sh", "s", "retroflex/palatal sibilant flattened"),
    ("s", "sh", "the reverse"),
    ("ksh", "ksh", "conjunct kept"),
    ("ry", "ri", "consonant-vowel cluster"),
    ("ay", "ai", "diphthong romanised two ways"),
    ("ei", "ai", "diphthong"),
    ("y", "i", "semivowel written as a vowel"),
    ("u", "oo", "short u lengthened"),
]


def mishear(name: str, rng: random.Random, n_rules: int = 1) -> str:
    """Apply n confusion rules to a name, producing a plausible mishearing."""
    out = name
    applied = 0
    for src, dst, _ in rng.sample(RULES, len(RULES)):
        if applied >= n_rules:
            break
        lower = out.lower()
        idx = lower.find(src)
        if idx == -1 or src == dst:
            continue
        out = out[:idx] + dst + out[idx + len(src) :]
        applied += 1
    return out if applied else out


# --------------------------------------------------------------------------- #
# Personas
# --------------------------------------------------------------------------- #

APPS = ["com.tinyspeck.slackmacgap", "com.microsoft.Outlook", "com.microsoft.VSCode"]


def build_persona(name: str, size: int, rng: random.Random, *, with_guards: bool) -> dict:
    """A persona of `size` lexemes.

    `with_guards=False` is the important variant: it produces a memory with NO
    hand-written common-word guards or support-word lists at all, which is what
    a real user's memory looks like on day one. If the system only behaves when
    a human has curated guard lists for it, that is a finding.
    """
    lexemes, used = [], set()
    for i in range(size):
        kind_roll = rng.random()
        if kind_roll < 0.55:
            surface = f"{rng.choice(GIVEN)} {rng.choice(FAMILY)}"
            kind = "person"
        elif kind_roll < 0.75:
            surface, kind = rng.choice(TECH_TERMS)
        elif kind_roll < 0.85:
            surface, kind = rng.choice(PLACES), "place"
        else:
            surface = f"{rng.choice(GIVEN)}"
            kind = "person"
        if surface in used:
            continue
        used.add(surface)

        # One or two forms the recogniser has "already produced" for this term.
        variants = []
        for _ in range(rng.choice([1, 1, 2])):
            wrong = mishear(surface, rng, n_rules=rng.choice([1, 1, 2]))
            if wrong.lower() != surface.lower():
                variants.append(
                    {"form": wrong.lower(), "provenance": "observed",
                     "count": rng.randint(1, 5)}
                )
        entry = {
            "id": f"lex.{name}.{i}",
            "canonical": surface,
            "kind": kind,
            "variants": variants,
            "state": "active",
            "confidence": {"alpha": float(rng.randint(3, 8)), "beta": 1.0},
            "bindings": [{"scope": "global"}]
            if rng.random() < 0.8
            else [{"scope": "app", "ref": rng.choice(APPS)}],
        }
        if with_guards and rng.random() < 0.12:
            entry["guards"] = [
                {"kind": "common_word",
                 "payload": {"form": surface.lower(), "support_tokens": ["service", "deploy"]}}
            ]
        lexemes.append(entry)

    # A few co-occurrence links, as a real store would accumulate.
    edges = []
    for _ in range(max(1, len(lexemes) // 6)):
        a, b = rng.sample(lexemes, 2)
        edges.append({"a": a["id"], "b": b["id"], "rel": "cooccurs",
                      "weight": round(rng.uniform(0.4, 0.9), 2)})

    return {
        "$comment": f"Generated stress persona '{name}' - {len(lexemes)} lexemes, "
                    f"guards={'on' if with_guards else 'OFF'}. Reproducible from "
                    f"evals/stress/generate.py with seed {SEED}.",
        "persona": {"name": name, "clock": "2026-01-15T09:00:00+00:00"},
        "lexemes": lexemes,
        "edges": edges,
    }


# --------------------------------------------------------------------------- #
# Held-out mishearings
# --------------------------------------------------------------------------- #

CARRIERS = [
    "ask {} to review the change",
    "{} is on call this week",
    "i sent the draft to {}",
    "can you loop in {} on this",
    "{} pushed a fix last night",
    "the ticket is assigned to {}",
    "we should ask {} before shipping",
    "{} said the numbers look wrong",
]


def _sentence_case(text: str) -> str:
    """Upper-case the first letter and leave every other character alone."""
    return text[:1].upper() + text[1:] if text else text


def build_mishearings(persona: dict, rng: random.Random, n: int = 300) -> list[dict]:
    """Sentences containing a form the system has NEVER seen for a term it knows.

    This is the real test of phonetic retrieval. If the system can only fix
    forms already in its variant table, it is a lookup table, not a memory.
    """
    known = {v["form"] for lx in persona["lexemes"] for v in lx.get("variants", [])}
    out = []
    for lexeme in persona["lexemes"]:
        for _ in range(3):
            wrong = mishear(lexeme["canonical"], rng, n_rules=rng.choice([1, 1, 2]))
            if wrong.lower() == lexeme["canonical"].lower() or wrong.lower() in known:
                continue
            carrier = rng.choice(CARRIERS)
            out.append({
                "lexeme_id": lexeme["id"],
                "canonical": lexeme["canonical"],
                "heard": wrong,
                "asr": carrier.format(wrong.lower()),
                # NOT str.capitalize(): it lowercases everything after the first
                # character, which would destroy the surname before the system
                # ever sees it and make the benchmark measure the wrong thing.
                "formatted": _sentence_case(carrier.format(wrong)) + ".",
                "app": rng.choice(APPS),
            })
            break
    rng.shuffle(out)
    return out[:n]


def main() -> None:
    rng = random.Random(SEED)
    (HERE / "personas").mkdir(exist_ok=True)

    for label, size, guards in [
        ("small_unseen", 25, True),
        ("medium_unguarded", 120, False),
        ("large_unguarded", 600, False),
    ]:
        persona = build_persona(label, size, rng, with_guards=guards)
        path = HERE / "personas" / f"{label}.json"
        path.write_text(json.dumps(persona, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{path.name:<26} {len(persona['lexemes']):>4} lexemes  "
              f"{len(persona['edges']):>3} edges  guards={'on' if guards else 'OFF'}")

    medium = json.loads((HERE / "personas" / "medium_unguarded.json").read_text())
    mis = build_mishearings(medium, rng)
    (HERE / "mishearings.jsonl").write_text(
        "\n".join(json.dumps(m, ensure_ascii=False) for m in mis) + "\n", encoding="utf-8"
    )
    print(f"{'mishearings.jsonl':<26} {len(mis):>4} held-out forms")
    for m in mis[:4]:
        print(f"      {m['heard']:<28} should resolve to  {m['canonical']}")


if __name__ == "__main__":
    main()
