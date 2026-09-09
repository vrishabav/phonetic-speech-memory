"""The fixtures are a deliverable, so they are tested like one.

This suite runs before any engine exists and keeps running after. It asserts
things about the *evaluation* rather than about the system: that every case is
well-formed, that the suite covers the taxonomy, that it contains enough
negative cases to be worth trusting, and that nobody has quietly renumbered a
case id and broken comparability with an earlier result.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "evals" / "data"
SCHEMA_PATH = ROOT / "evals" / "schema" / "case.schema.json"
TAXONOMY = ROOT / "REPORT.md"

APPLICATION = DATA / "tier_c_application.jsonl"
LEARNING = DATA / "tier_c_learning.jsonl"
SEED = DATA / "persona_seed.json"


def _load(path: Path) -> list[dict]:
    cases = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            cases.append(json.loads(line))
        except json.JSONDecodeError as exc:  # pragma: no cover - failure path
            pytest.fail(f"{path.name}:{lineno} is not valid JSON: {exc}")
    return cases


@pytest.fixture(scope="module")
def application_cases() -> list[dict]:
    return _load(APPLICATION)


@pytest.fixture(scope="module")
def learning_cases() -> list[dict]:
    return _load(LEARNING)


@pytest.fixture(scope="module")
def seed() -> dict:
    return json.loads(SEED.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Well-formedness
# --------------------------------------------------------------------------- #


def test_cases_validate_against_schema(application_cases, learning_cases):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for case in application_cases + learning_cases:
        errors = sorted(validator.iter_errors(case), key=lambda e: e.path)
        assert not errors, f"{case['case_id']}: " + "; ".join(e.message for e in errors)


def test_case_ids_are_unique(application_cases, learning_cases):
    ids = [c["case_id"] for c in application_cases + learning_cases]
    duplicates = [cid for cid, n in Counter(ids).items() if n > 1]
    assert not duplicates, f"duplicate case ids: {duplicates}"


def test_every_case_has_a_real_rationale(application_cases, learning_cases):
    """A case nobody can justify is a case nobody should trust."""
    for case in application_cases + learning_cases:
        rationale = case.get("rationale", "")
        assert len(rationale.split()) >= 8, f"{case['case_id']}: rationale too thin"


# --------------------------------------------------------------------------- #
# Internal consistency - expectations must match themselves
# --------------------------------------------------------------------------- #


def test_abstain_cases_do_not_change_text(application_cases):
    for case in application_cases:
        if case["expect"] not in {"abstain", "propose", "noop"}:
            continue
        given, then = case["given"], case["then"]
        assert then["output"] == given["formatted"], (
            f"{case['case_id']} expects {case['expect']} but its expected output "
            f"differs from the formatted input"
        )
        assert not then.get("changes"), f"{case['case_id']} abstains but lists changes"


def test_apply_cases_do_change_text(application_cases):
    for case in application_cases:
        if case["expect"] != "apply":
            continue
        given, then = case["given"], case["then"]
        assert then["output"] != given["formatted"], (
            f"{case['case_id']} expects apply but its expected output is unchanged"
        )
        assert then.get("changes"), f"{case['case_id']} applies but lists no changes"


def test_declared_changes_are_present_in_expected_output(application_cases):
    for case in application_cases:
        for change in case["then"].get("changes", []):
            assert change["to"] in case["then"]["output"], (
                f"{case['case_id']}: expected replacement {change['to']!r} does not "
                f"appear in the expected output"
            )


def test_referenced_lexemes_exist_in_seed(application_cases, seed):
    known = {lx["id"] for lx in seed["lexemes"]}
    for case in application_cases:
        for change in case["then"].get("changes", []):
            lexeme_id = change.get("lexeme_id")
            if lexeme_id:
                assert lexeme_id in known, f"{case['case_id']}: unknown lexeme {lexeme_id}"
        overrides = (case["given"] or {}).get("memory_overrides") or {}
        for lexeme_id in overrides:
            assert lexeme_id in known, f"{case['case_id']}: override for unknown {lexeme_id}"


def test_seed_edges_reference_known_lexemes(seed):
    known = {lx["id"] for lx in seed["lexemes"]}
    for edge in seed["edges"]:
        assert edge["a"] in known and edge["b"] in known, f"dangling edge {edge}"


# --------------------------------------------------------------------------- #
# Suite quality - properties of the evaluation, not of the system
# --------------------------------------------------------------------------- #


def test_negative_cases_are_at_least_forty_percent(application_cases):
    """The brief scores 'where it should deliberately do nothing'. A suite that is
    mostly happy-path cannot demonstrate that, however well it scores."""
    negative = sum(1 for c in application_cases if c["expect"] in {"abstain", "propose"})
    ratio = negative / len(application_cases)
    assert ratio >= 0.40, f"only {ratio:.0%} of application cases are negative"


def test_every_taxonomy_class_is_covered(application_cases, learning_cases):
    """Each class id declared in the report's taxonomy must appear in at least one case."""
    import re

    text = TAXONOMY.read_text(encoding="utf-8")
    # Rows look like: | A1 | `homophone_spelling` | ... - the class is the
    # backticked identifier in the second column. The table lives in REPORT.md
    # §14.1; parsing it there rather than restating it here is what keeps the
    # document and the fixtures from drifting apart.
    declared = set()
    for line in text.splitlines():
        match = re.match(r"^\|\s*[ABC]\d+\s*\|\s*`([a-z_]+)`", line)
        if match:
            declared.add(match.group(1))
    assert declared, "no taxonomy classes parsed - the table format changed"
    used = {c["class"] for c in application_cases + learning_cases}
    missing = declared - used
    assert not missing, f"taxonomy classes with no case: {sorted(missing)}"


def test_cases_assert_a_reason_not_only_an_output(application_cases):
    """Asserting the reason code as well as the text is what stops a case passing
    for the wrong cause - the classic way a green suite hides a broken system."""
    for case in application_cases:
        assert case["then"].get("reason"), f"{case['case_id']} asserts no reason code"


def test_zero_cost_cases_declare_a_call_budget(application_cases):
    """Every case whose point is that nothing should be spent must say so."""
    for case in application_cases:
        if case["class"] in {"no_candidate", "already_canonical", "not_phonetic"}:
            assert case["then"].get("max_llm_calls") == 0, (
                f"{case['case_id']} is a zero-cost case but declares no budget"
            )


def test_all_cases_predate_the_engine(application_cases, learning_cases):
    """Cases added after seeing engine behaviour are legitimate but must be
    flagged, and reported separately. This test records how many there are."""
    post_hoc = [
        c["case_id"]
        for c in application_cases + learning_cases
        if not c.get("authored_before_engine", True)
    ]
    ratio = len(post_hoc) / (len(application_cases) + len(learning_cases))
    assert ratio <= 0.20, f"{ratio:.0%} of cases were authored after the engine: {post_hoc}"


# --------------------------------------------------------------------------- #
# Wiring integrity
#
# These exist because the opposite was true for a while and nothing caught it:
# `Settings.index` named "index.sqlite_fts", a module that had never been
# written, while the engine quietly hardcoded the in-memory index. Every eval
# result recorded a component that had not run. A config field that does not
# resolve is worse than no config field, and a config field the engine ignores
# is worse still, so both are now asserted.
# --------------------------------------------------------------------------- #


def test_every_registry_alias_resolves():
    from psm.registry import _ALIASES, resolve

    for alias in sorted(_ALIASES):
        if alias == "llm.sarvam":
            continue  # constructor demands a key; import-checked below instead
        resolve(alias)


def test_sarvam_adapter_is_importable_without_a_key():
    """Importing must never require credentials, or the offline suite could not
    even load the module that the live suite swaps in."""
    from psm.registry import resolve

    assert resolve("llm.sarvam").__name__ == "SarvamModel"


def test_default_settings_name_components_that_exist():
    from psm.config import Settings
    from psm.registry import resolve

    settings = Settings()
    for field_name in ("clock", "phonetics", "store", "index", "llm", "formatter"):
        resolve(getattr(settings, field_name))


def test_engine_honours_the_configured_components():
    """A swap in Settings must reach the built object. Asserting the *name*
    rather than the type is deliberate: it is the thing written into every eval
    result, so this test also pins the provenance of the numbers."""
    from psm.config import Settings
    from psm.engine.engine import Engine

    engine = Engine.build(Settings(store="store.memory"))
    assert engine.index.name == "inmemory"
    assert engine.formatter.name == "passthrough"
    assert engine.llm.name == "stub"

    swapped = Engine.build(Settings(store="store.memory", formatter="formatter.llm"))
    assert swapped.formatter.name == "llm_formatter"


# --------------------------------------------------------------------------- #
# The learning tier
#
# `tier_c_learning.jsonl` asserts what evidence does to *memory*, which the
# application tier never touches. For a while it had no runner at all: fifteen
# cases were schema-checked and never executed, so every assertion in them was
# decorative. This test is what makes that impossible to repeat quietly.
# --------------------------------------------------------------------------- #


def test_every_learning_case_passes():
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from evals.harness import load_jsonl
    from evals.learning import run_learning_cases

    from psm.config import Settings

    cases = load_jsonl(root / "evals" / "data" / "tier_c_learning.jsonl")
    assert cases, "the learning tier is empty"
    results = run_learning_cases(cases, Settings(store="store.memory"))
    failures = {r.case_id: r.failures for r in results if not r.passed}
    assert not failures, f"learning cases failing: {failures}"


def test_learning_fixtures_assert_something_a_check_reads():
    """A `memory_delta` key with no implementation behind it passes silently and
    proves nothing. The runner rejects unknown keys; this asserts that the
    fixtures do not contain any."""
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from evals.harness import load_jsonl
    from evals.learning import KNOWN_DELTAS

    cases = load_jsonl(root / "evals" / "data" / "tier_c_learning.jsonl")
    for case in cases:
        unknown = set(case["then"].get("memory_delta", {})) - KNOWN_DELTAS
        assert not unknown, f"{case['case_id']} asserts unread key(s) {sorted(unknown)}"
        assert case["then"].get("memory_delta"), (
            f"{case['case_id']} asserts no memory change at all"
        )


# --------------------------------------------------------------------------- #
# The live path
#
# `--live` and `--replay` were declared on both the CLI and the harness and then
# never read, so `make eval-live` ran the offline stub and wrote a result file
# labelled `live` that reported zero model calls. These pin the switch.
# --------------------------------------------------------------------------- #


def test_live_and_replay_actually_change_the_components():
    """The flags select components rather than decorating the label."""
    import argparse

    from evals.harness import main as harness_main

    seen = {}

    def fake(argv):
        parser = argparse.ArgumentParser()
        parser.add_argument("--out")
        parser.add_argument("--live", action="store_true")
        parser.add_argument("--replay", action="store_true")
        seen.update(vars(parser.parse_known_args(argv)[0]))
        return 0

    assert callable(harness_main)

    import evals.harness as harness

    from psm.cli import main as cli_main

    original = harness.main
    harness.main = fake
    try:
        cli_main(["eval", "--live", "--out", "/tmp/psm-flagcheck"])
        assert seen["live"] is True and seen["replay"] is False
        seen.clear()
        cli_main(["eval", "--replay", "--out", "/tmp/psm-flagcheck"])
        assert seen["replay"] is True and seen["live"] is False
        seen.clear()
        cli_main(["eval", "--out", "/tmp/psm-flagcheck"])
        assert seen["live"] is False and seen["replay"] is False
    finally:
        harness.main = original


def test_a_live_run_without_credentials_fails_instead_of_degrading(monkeypatch, tmp_path):
    """The worst outcome is a `live` result file produced with no model calls.
    The adapter refuses to construct rather than silently falling back."""
    from psm.adapters.llm.sarvam import SarvamCredentialsMissing, SarvamModel

    for var in ("SARVAM_API_KEY", "PSM_SARVAM_BASE_URL", "PSM_SARVAM_MODEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PSM_DOTENV", str(tmp_path / "absent.env"))
    with pytest.raises(SarvamCredentialsMissing) as exc:
        SarvamModel()
    assert "SARVAM_API_KEY" in str(exc.value)
    assert "make eval" in str(exc.value), "the error has to name the offline way out"
