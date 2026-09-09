"""Build the case explorer: one self-contained page showing every case.

The brief asks that a reviewer be able to *understand why the system did or did
not intervene*, and that failures be inspectable. A pass rate does not do that.
This does: every case, its inputs, what was expected, what happened, the memory
state at the moment it decided, and every policy's opinion with the sentence it
gave.

Output is a single HTML file with no external dependencies - no CDN, no fonts,
no network. It opens from the filesystem, works offline, and is small enough to
commit.

    python -m lmh.cli explore            # build and report the path
    make explore                         # same
"""

from __future__ import annotations

import json
import unicodedata
from datetime import UTC, datetime
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

VERDICT_CLASS = {"apply": "v-apply", "propose": "v-propose", "abstain": "v-abstain"}
SIGNAL_CLASS = {
    "support": "s-support", "oppose": "s-oppose", "veto": "s-veto", "neutral": "s-neutral",
}


def _combining(ch: str) -> bool:
    """True for a mark that has no standalone shape.

    Devanagari matras, the virama and the anusvara are all category `Mn`/`Mc`.
    A highlight that begins on one of them renders as a box around a floating
    accent, so the boundaries below are widened until they sit on a base
    character. `Mc` (spacing combining) matters here: `ा` is Mc, not Mn.
    """
    return unicodedata.category(ch) in {"Mn", "Mc", "Me"}


def _diff(before: str, after: str) -> str:
    """Mark the changed region so the eye lands on it immediately."""
    if before == after:
        return escape(before) or "<em class=muted>(empty)</em>"
    head = 0
    while head < min(len(before), len(after)) and before[head] == after[head]:
        head += 1
    tail = 0
    while (
        tail < min(len(before), len(after)) - head
        and before[len(before) - 1 - tail] == after[len(after) - 1 - tail]
    ):
        tail += 1
    # Pull the start back onto a base character, and push the end past any
    # marks that belong to the last base character inside the span.
    while head > 0 and head < len(after) and _combining(after[head]):
        head -= 1
    end = len(after) - tail
    while end < len(after) and _combining(after[end]):
        end += 1
    # A pure deletion ("Aadhith" -> "Aadith") leaves nothing to mark in `after`.
    # Widen by one character each way so the join is still visible, rather than
    # emitting an empty <mark> that renders as nothing at all.
    if end <= head:
        head = max(0, head - 1)
        end = min(len(after), end + 1)
        while head > 0 and _combining(after[head]):
            head -= 1
        while end < len(after) and _combining(after[end]):
            end += 1
    return (
        escape(after[:head])
        + "<mark>"
        + escape(after[head:end])
        + "</mark>"
        + escape(after[end:])
    )


def _policy_rows(resolution: dict) -> str:
    rows = []
    for outcome in resolution.get("policies", []):
        signal = outcome.get("signal", "neutral")
        if signal == "neutral" and not outcome.get("rationale"):
            continue
        weight = outcome.get("weight") or 0.0
        rows.append(
            f'<tr class="{SIGNAL_CLASS.get(signal, "s-neutral")}">'
            f'<td class=pol>{escape(outcome.get("policy", ""))}</td>'
            f'<td class=sig>{escape(signal)}</td>'
            f'<td class=num>{weight:+.2f}</td>'
            f'<td>{escape(outcome.get("rationale") or "")}</td></tr>'
        )
    if not rows:
        return ""
    return (
        "<table class=policies><tr><th>policy</th><th>signal</th><th>weight</th>"
        "<th>why</th></tr>" + "".join(rows) + "</table>"
    )


def _resolutions(case: dict) -> str:
    out = []
    for r in case.get("trace", []):
        verdict = r.get("verdict", "abstain")
        span = r.get("span", [0, 0, ""])
        arrow = (
            f'<code>{escape(span[2])}</code> &rarr; <code>{escape(r["replacement"])}</code>'
            if r.get("replacement")
            else f'<code>{escape(span[2])}</code> &rarr; <span class=muted>unchanged</span>'
        )
        out.append(
            f'<div class="res {VERDICT_CLASS.get(verdict, "v-abstain")}">'
            f'<div class=res-head><span class=verdict>{escape(verdict)}</span> {arrow} '
            f'<span class=muted>matched {escape(r.get("canonical", ""))} '
            f'via {escape(r.get("matched_via", ""))}, score {r.get("score", 0):.2f}</span> '
            f'<span class=reason>{escape(str(r.get("reason")))}</span></div>'
            + _policy_rows(r)
            + "</div>"
        )
    if not out:
        return (
            '<p class=muted>No candidate was retrieved. The gate closed or nothing in '
            "memory resembled this text, so the call cost nothing.</p>"
        )
    return "".join(out)


def _memory(case: dict) -> str:
    rows = []
    for lx in case.get("memory_state", []):
        variants = ", ".join(lx.get("variants", [])) or "-"
        guards = ", ".join(lx.get("guards", [])) or "-"
        rows.append(
            f"<tr><td>{escape(lx['canonical'])}</td><td>{escape(lx['state'])}</td>"
            f"<td class=num>{lx['confidence']:.2f}</td><td class=num>{lx['strength']:.2f}</td>"
            f"<td class=small>{variants}</td><td class=small>{guards}</td></tr>"
        )
    return (
        "<table class=memory><tr><th>canonical</th><th>state</th><th>conf</th>"
        "<th>strength</th><th>known forms</th><th>guards</th></tr>"
        + "".join(rows)
        + "</table>"
    )


def _case_block(case: dict) -> str:
    passed = case["passed"]
    given_formatted = case.get("_formatted", "")
    reason_line = (
        f'expected <code>{escape(str(case["expected_reason"]))}</code>, '
        f'got <code>{escape(str(case["actual_reason"]))}</code>'
        if case["expected_reason"] != case["actual_reason"]
        else f'reason <code>{escape(str(case["actual_reason"]))}</code>'
    )
    mismatch = (
        ""
        if case["expected_output"] == case["actual_output"]
        else f'<div class=row><span class=label>expected</span>'
        f'<span class="text want">{escape(case["expected_output"])}</span></div>'
    )
    return f"""
<details class="case {'ok' if passed else 'bad'}" data-cls="{escape(case['cls'])}"
         data-outcome="{escape(case['outcome'])}" data-status="{'pass' if passed else 'fail'}">
  <summary>
    <span class=badge>{'PASS' if passed else 'FAIL'}</span>
    <span class=cid>{escape(case['case_id'])}</span>
    <span class=cls>{escape(case['cls'])}</span>
    <span class=exp>expect {escape(case['expect'])}</span>
    <span class=outcome>{escape(case['outcome'])}</span>
  </summary>
  <div class=body>
    <p class=rationale>{escape(case.get('_rationale', ''))}</p>
    <div class=row><span class=label>ASR</span><span class="text mono">{escape(case.get('_asr', '')) or '<em>-</em>'}</span></div>
    <div class=row><span class=label>formatted</span><span class="text mono">{escape(given_formatted)}</span></div>
    <div class=row><span class=label>output</span><span class="text mono out">{_diff(given_formatted, case['actual_output'])}</span></div>
    {mismatch}
    <div class=row><span class=label>app</span><span class=text>{escape(case.get('_app') or 'any')} &middot; {reason_line} &middot; {case['llm_calls']} model calls &middot; {case['latency_ms']:.2f} ms</span></div>
    <h4>Decision trace</h4>
    {_resolutions(case)}
    <h4>Memory at the moment it decided <span class=muted>({len(case.get('memory_state', []))} terms)</span></h4>
    {_memory(case)}
  </div>
</details>"""


def _breakdown(title: str, note: str, rows: dict) -> str:
    """One slice of the generated tier, worst first.

    A bar rather than a bare percentage, because the eye finds the short one
    instantly and that is the whole purpose of the table: to say *where* the
    system fails rather than whether.
    """
    if not rows:
        return ""
    body = []
    for name, s in sorted(rows.items(), key=lambda kv: kv[1]["pass_rate"]):
        rate = s["pass_rate"]
        tone = "" if rate >= 0.97 else (" warn" if rate >= 0.85 else " poor")
        harmful = (
            f' <span class=bad-t>&middot; {s["harmful"]} harmful</span>' if s["harmful"] else ""
        )
        body.append(
            f"<tr><td class=grow-cell>{escape(name)}</td>"
            f'<td class=num>{s["n"]}</td>'
            f'<td class=grow><div class="bar{tone}"><i style="width:{rate * 100:.0f}%"></i></div></td>'
            f'<td class=num>{rate:.0%}</td>'
            f"<td class=small>{s['missed']} missed{harmful}</td></tr>"
        )
    return (
        f"<div class=bd><h3>{escape(title)}</h3><p>{escape(note)}</p>"
        f"<table>{''.join(body)}</table></div>"
    )


def _generated_payload(results_dir: Path) -> dict:
    """Load the generated tier if it has been run, else an empty stand-in.

    The explorer must still build when only `make eval` has been run, because
    that is the first thing a reviewer does.
    """
    cases = results_dir / "cases.jsonl"
    summary = results_dir / "summary.json"
    if not (cases.exists() and summary.exists()):
        return {}
    return {
        "summary": json.loads(summary.read_text(encoding="utf-8")),
        "cases": [
            json.loads(line)
            for line in cases.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ],
    }


def build(results_dir: Path, cases_file: Path, out: Path) -> Path:
    rows = [
        json.loads(line)
        for line in (results_dir / "cases.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    summary = json.loads((results_dir / "summary.json").read_text(encoding="utf-8"))
    source = {
        c["case_id"]: c
        for c in (
            json.loads(line)
            for line in cases_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }
    for row in rows:
        given = source.get(row["case_id"], {}).get("given", {})
        row["_asr"] = given.get("asr", "")
        row["_formatted"] = given.get("formatted", "")
        row["_app"] = given.get("app")
        row["_rationale"] = source.get(row["case_id"], {}).get("rationale", "")

    rows.sort(key=lambda r: (r["passed"], r["case_id"]))
    classes = sorted({r["cls"] for r in rows})
    t = summary["totals"]
    n = summary["negative_cases"]

    body = "".join(_case_block(r) for r in rows)

    gen = _generated_payload(results_dir.parent / "generated")
    if gen:
        gs = gen["summary"]
        gt, gn = gs["totals"], gs["negative_cases"]
        breakdowns = (
            _breakdown("By family", "what kind of input is it wrong about?", gs["by_family"])
            + _breakdown("By memory size", "does it hold as memory grows from 24 to 367 terms?",
                         gs["by_persona"])
            + _breakdown("By script", "nine Indic blocks, one code path - one result?",
                         gs["by_language"])
            + _breakdown("By confusion rule", "which phonological confusions the fold survives",
                         gs["by_confusion_rule"])
        )
        # Only what the client renders. Traces and rationales for 1,800 cases
        # would quadruple the file for something nobody scrolls to.
        slim = [
            {
                "i": c["case_id"], "f": c["generator"], "p": c["persona"],
                "l": c["language"], "r": c["rule"], "e": c["expect"],
                "o": c["outcome"], "k": 1 if c["passed"] else 0,
                "t": c["formatted"], "w": c["expected_output"], "a": c["actual_output"],
                "n": c["actual_reason"],
            }
            for c in gen["cases"]
        ]
        gen_fields = {
            "gen_total": gt["cases"], "gen_passed": gt["passed"],
            "gen_rate": f"{gt['pass_rate']:.1%}",
            "gen_false": gn["false_intervention"], "gen_negatives": gn["n"],
            "gen_calls": gs["cost"]["llm_calls_total"], "gen_p50": gs["latency_ms"]["p50"],
            "breakdowns": breakdowns,
            "gen_families": "".join(
                f'<option value="{escape(k)}">{escape(k)}</option>' for k in sorted(gs["by_family"])
            ),
            "gen_langs": "".join(
                f'<option value="{escape(k)}">{escape(k)}</option>'
                for k in sorted(gs["by_language"])
            ),
            "gen_json": json.dumps(slim, ensure_ascii=False).replace("</", "<\\/"),
        }
    else:
        gen_fields = {
            "gen_total": 0, "gen_passed": 0, "gen_rate": "-", "gen_false": 0,
            "gen_negatives": 0, "gen_calls": 0, "gen_p50": 0,
            "breakdowns": "<p class=muted style='padding:0 32px'>Run "
                          "<code>make eval-generated</code> to populate this tab.</p>",
            "gen_families": "", "gen_langs": "", "gen_json": "[]",
        }

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_PAGE.format(
        generated=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        passed=t["passed"], total=t["cases"], rate=f"{t['pass_rate']:.0%}",
        negatives=n["n"], false_rate=f"{n['false_intervention_rate']:.1%}",
        calls=summary["cost"]["llm_calls_total"],
        p50=summary["latency_ms"]["p50"],
        options="".join(f'<option value="{escape(c)}">{escape(c)}</option>' for c in classes),
        cases=body,
        **gen_fields,
    ), encoding="utf-8")
    return out


_PAGE = """<!doctype html><meta charset=utf-8>
<title>language-memory-handler - every case</title>
<style>
:root{{--ink:#16161d;--muted:#6b6b76;--rule:#e3e3e8;--paper:#fbfbfc;--card:#fff;
--good:#136c4f;--goodbg:#e7f4ef;--bad:#a3271c;--badbg:#fcecea;--warn:#8a5a06;--warnbg:#fdf3e2;
--accent:#4b3fbe;--accentbg:#eeecfb}}
*{{box-sizing:border-box}}
/* `display:flex` on .controls beats the default [hidden] rule, so the
   specification tab's toolbar stayed on screen over the generated tab. */
[hidden]{{display:none!important}}
body{{margin:0;background:var(--paper);color:var(--ink);
font:14px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans Devanagari",sans-serif}}
header{{padding:26px 32px 18px;border-bottom:1px solid var(--rule);background:var(--card)}}
h1{{margin:0 0 4px;font-size:19px;letter-spacing:-.01em}}
.sub{{color:var(--muted);margin:0}}
.stats{{display:flex;flex-wrap:wrap;gap:26px;margin-top:16px}}
.stat b{{display:block;font-size:20px;font-variant-numeric:tabular-nums}}
.stat span{{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.07em}}
.controls{{position:sticky;top:0;z-index:5;background:var(--card);border-bottom:1px solid var(--rule);
padding:10px 32px;display:flex;gap:10px;flex-wrap:wrap;align-items:center}}
select,input,button{{font:inherit;padding:5px 9px;border:1px solid var(--rule);border-radius:6px;background:var(--card)}}
input{{min-width:260px}}
button{{cursor:pointer}}
.tabs{{display:flex;gap:8px;margin-top:16px}}
.tab{{padding:7px 14px;border-radius:7px 7px 0 0;border:1px solid var(--rule);border-bottom:none;
background:var(--paper);color:var(--muted);font-weight:600}}
.tab.on{{background:var(--card);color:var(--ink);box-shadow:inset 0 2px 0 var(--accent)}}
.genhead{{padding:22px 32px 6px}}
.breakdowns{{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));
gap:18px;padding:12px 32px 20px}}
.bd{{background:var(--card);border:1px solid var(--rule);border-radius:9px;padding:12px 14px}}
.bd h3{{margin:0 0 2px;font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:var(--accent)}}
.bd p{{margin:0 0 8px;color:var(--muted);font-size:12px}}
.bar{{position:relative;background:var(--rule);border-radius:3px;height:6px;width:100%}}
.bar i{{position:absolute;left:0;top:0;bottom:0;border-radius:3px;background:var(--good)}}
.bar.warn i{{background:var(--warn)}} .bar.poor i{{background:var(--bad)}}
.bd table{{margin-top:2px}} .bd td{{padding:3px 6px 3px 0;border:none}}
.grow{{width:100%}}
.grow-cell{{width:38%}}
.gcase{{background:var(--card);border:1px solid var(--rule);border-left-width:3px;border-radius:8px;
padding:9px 13px;margin:0 32px 7px}}
.gcase.bad{{border-left-color:var(--bad)}} .gcase.ok{{border-left-color:var(--good)}}
.gcase .line{{display:flex;gap:10px;flex-wrap:wrap;align-items:baseline}}
.gcase .why{{color:var(--muted);font-size:12px;margin-top:3px}}
#genlist{{padding-bottom:60px}}
main{{padding:18px 32px 60px;max-width:1180px}}
.case{{background:var(--card);border:1px solid var(--rule);border-radius:8px;margin-bottom:8px;overflow:hidden}}
.case.bad{{border-color:#f0c8c2}}
summary{{cursor:pointer;padding:10px 14px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}}
summary::-webkit-details-marker{{display:none}}
.badge{{font-size:10px;font-weight:700;letter-spacing:.06em;padding:2px 7px;border-radius:4px;
background:var(--goodbg);color:var(--good)}}
.case.bad .badge{{background:var(--badbg);color:var(--bad)}}
.cid{{font-family:ui-monospace,monospace;font-size:12.5px;font-weight:600;min-width:78px}}
.cls{{color:var(--accent);background:var(--accentbg);padding:1px 7px;border-radius:4px;font-size:11.5px}}
.exp,.outcome{{color:var(--muted);font-size:12px}}
.body{{padding:4px 16px 18px;border-top:1px solid var(--rule)}}
.rationale{{color:var(--muted);max-width:76ch;margin:12px 0 14px;font-size:13px}}
.row{{display:flex;gap:10px;margin:4px 0;align-items:baseline}}
.label{{flex:0 0 82px;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.06em;text-align:right}}
.text{{flex:1;min-width:0;word-break:break-word}}
.mono{{font-family:ui-monospace,"Noto Sans Devanagari",monospace;font-size:12.5px}}
.out{{background:#f6f6fa;padding:3px 7px;border-radius:4px}}
.want{{background:var(--warnbg);padding:3px 7px;border-radius:4px;font-family:ui-monospace,monospace;font-size:12.5px}}
mark{{background:#fde68a;padding:0 2px;border-radius:2px}}
h4{{margin:18px 0 6px;font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted)}}
.res{{border:1px solid var(--rule);border-left-width:3px;border-radius:6px;padding:8px 11px;margin-bottom:7px}}
.v-apply{{border-left-color:var(--good)}} .v-propose{{border-left-color:var(--warn)}}
.v-abstain{{border-left-color:#b9b9c2}}
.res-head{{display:flex;gap:9px;flex-wrap:wrap;align-items:baseline;font-size:12.5px}}
.verdict{{font-weight:700;font-size:10.5px;letter-spacing:.05em;text-transform:uppercase}}
.reason{{font-family:ui-monospace,monospace;font-size:11px;background:#f1f1f5;padding:1px 6px;border-radius:4px}}
table{{border-collapse:collapse;width:100%;margin-top:7px;font-size:12px}}
th{{text-align:left;color:var(--muted);font-weight:500;font-size:10px;text-transform:uppercase;
letter-spacing:.06em;padding:3px 7px;border-bottom:1px solid var(--rule)}}
td{{padding:3px 7px;border-bottom:1px solid #f1f1f4;vertical-align:top}}
.pol{{font-family:ui-monospace,monospace;white-space:nowrap}}
.num{{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}}
.sig{{font-size:10.5px;text-transform:uppercase;letter-spacing:.04em}}
.s-support .sig{{color:var(--good)}} .s-oppose .sig{{color:var(--warn)}}
.s-veto .sig{{color:var(--bad);font-weight:700}} .s-neutral .sig{{color:#a2a2ac}}
.small{{font-size:11px;color:var(--muted)}}
.muted{{color:var(--muted)}}
code{{font-family:ui-monospace,"Noto Sans Devanagari",monospace;background:#f1f1f5;padding:1px 4px;border-radius:3px}}
.hidden{{display:none}}
@media (prefers-color-scheme:dark){{
:root{{--ink:#e9e9f0;--muted:#9a9aa6;--rule:#2c2c36;--paper:#101016;--card:#191921;
--good:#5cc79f;--goodbg:#12281f;--bad:#e5837a;--badbg:#2c1917;--warn:#d7a750;--warnbg:#2a2113;
--accent:#9b8dff;--accentbg:#221f38}}
.out{{background:#20202a}} .reason{{background:#24242e}} code{{background:#24242e}}
td{{border-bottom-color:#232330}} mark{{background:#5c4a12;color:#f6e5b0}}
.case.bad{{border-color:#4a2a26}}
}}
</style>
<header>
  <h1>language-memory-handler - every evaluation case</h1>
  <p class=sub>Each case shows its inputs, the expected result, the actual result, the memory
     state at the moment it decided, and every policy's opinion. Generated {generated}.</p>
  <div class=stats>
    <div class=stat><b>{passed}/{total}</b><span>cases passed ({rate})</span></div>
    <div class=stat><b>{false_rate}</b><span>false intervention, {negatives} negatives</span></div>
    <div class=stat><b>{calls}</b><span>model calls</span></div>
    <div class=stat><b>{p50} ms</b><span>median latency</span></div>
  </div>
  <div class=tabs>
    <button class="tab on" data-tab=spec>Specification - {total} hand-written</button>
    <button class=tab data-tab=gen>Derived - {gen_total} generated</button>
  </div>
</header>
<div class=controls id=speccontrols>
  <input id=q type=search placeholder="Search text, case id, reason, term...">
  <select id=cls><option value="">every class</option>{options}</select>
  <select id=st><option value="">pass and fail</option><option value=fail>failing only</option>
    <option value=pass>passing only</option></select>
  <button id=expand>Expand all</button><button id=collapse>Collapse all</button>
  <span class=muted id=count></span>
</div>
<main id=specmain>{cases}</main>

<section id=genmain hidden>
  <div class=genhead>
    <p class=sub>{gen_total} cases derived mechanically from committed inputs. Every expected
      outcome comes from the construction, never from what the engine did. Two families are
      <em>meant</em> to be hard - they ask the system to fix spellings that are in no
      variant table anywhere - so the useful reading is the breakdown, not the total.</p>
    <div class=stats>
      <div class=stat><b>{gen_passed}/{gen_total}</b><span>cases passed ({gen_rate})</span></div>
      <div class=stat><b>{gen_false}</b><span>false intervention, {gen_negatives} negatives</span></div>
      <div class=stat><b>{gen_calls}</b><span>model calls</span></div>
      <div class=stat><b>{gen_p50} ms</b><span>median latency</span></div>
    </div>
  </div>
  <div class=breakdowns>{breakdowns}</div>
  <div class=controls>
    <input id=gq type=search placeholder="Search generated cases...">
    <select id=gfam><option value="">every family</option>{gen_families}</select>
    <select id=glang><option value="">every script</option>{gen_langs}</select>
    <select id=gst><option value="">pass and fail</option><option value=fail>failing only</option>
      <option value=pass>passing only</option></select>
    <span class=muted id=gcount></span>
  </div>
  <div id=genlist></div>
</section>

<script id=gendata type="application/json">{gen_json}</script>
<script>
const cases=[...document.querySelectorAll('.case')];
const q=document.getElementById('q'),cls=document.getElementById('cls'),st=document.getElementById('st');
const count=document.getElementById('count');
function apply(){{
  const term=q.value.toLowerCase(), c=cls.value, s=st.value; let n=0;
  for(const el of cases){{
    const ok=(!c||el.dataset.cls===c)&&(!s||el.dataset.status===s)
      &&(!term||el.textContent.toLowerCase().includes(term));
    el.classList.toggle('hidden',!ok); if(ok)n++;
  }}
  count.textContent=n+' of '+cases.length+' shown';
}}
q.oninput=cls.onchange=st.onchange=apply;
document.getElementById('expand').onclick=()=>cases.forEach(c=>{{if(!c.classList.contains('hidden'))c.open=true}});
document.getElementById('collapse').onclick=()=>cases.forEach(c=>c.open=false);
apply();

/* ---- tabs ------------------------------------------------------------- */
const specMain=document.getElementById('specmain'),
      specCtl=document.getElementById('speccontrols'),
      genMain=document.getElementById('genmain');
document.querySelectorAll('.tab').forEach(btn=>btn.onclick=()=>{{
  document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('on',b===btn));
  const spec=btn.dataset.tab==='spec';
  specMain.hidden=!spec; specCtl.hidden=!spec; genMain.hidden=spec;
  if(!spec) renderGen();
}});

/* ---- generated tier ---------------------------------------------------- */
/* Rendered from JSON on demand rather than baked into the HTML: eighteen
   hundred pre-rendered case blocks would be a 13MB file, and the reader only
   ever looks at a screenful. Capped at 400 rows per view for the same reason -
   the filters are how you find the case you want, not scrolling. */
const GEN=JSON.parse(document.getElementById('gendata').textContent);
const gq=document.getElementById('gq'), gfam=document.getElementById('gfam'),
      glang=document.getElementById('glang'), gst=document.getElementById('gst'),
      gcount=document.getElementById('gcount'), genlist=document.getElementById('genlist');
const esc=t=>(t??'').replace(/[&<>"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]));

function renderGen(){{
  if(!GEN.length){{ gcount.textContent=''; return; }}
  const term=gq.value.toLowerCase(), fam=gfam.value, lang=glang.value, st=gst.value;
  const hit=GEN.filter(c=>{{
    if(fam&&c.f!==fam) return false;
    if(lang&&c.l!==lang) return false;
    if(st==='fail'&&c.k) return false;
    if(st==='pass'&&!c.k) return false;
    if(term&&!(c.i+' '+c.t+' '+c.a+' '+c.n+' '+c.r+' '+c.f).toLowerCase().includes(term)) return false;
    return true;
  }});
  /* Failures first: they are the reason to open this tab. */
  hit.sort((a,b)=>a.k-b.k || a.i.localeCompare(b.i));
  const shown=hit.slice(0,400);
  gcount.textContent=hit.length+' of '+GEN.length+' shown'+
    (hit.length>400?' (first 400 rendered - narrow the filters)':'');
  genlist.innerHTML=shown.map(c=>{{
    const changed=c.a!==c.t;
    return `<div class="gcase ${{c.k?'ok':'bad'}}">
      <div class=line>
        <span class="badge ${{c.k?'':'fail'}}">${{c.k?'PASS':'FAIL'}}</span>
        <span class=cid>${{esc(c.i)}}</span>
        <span class=cls>${{esc(c.f)}}</span>
        ${{c.l&&c.l!=='latin'?`<span class=cls>${{esc(c.l)}}</span>`:''}}
        ${{c.r?`<span class=cls>${{esc(c.r)}}</span>`:''}}
        <span class=muted>expect ${{esc(c.e)}} &middot; ${{esc(c.o)}} &middot; ${{esc(c.n)}}</span>
      </div>
      <div class=why><span class=mono>${{esc(c.t)}}</span></div>
      <div class=why>&rarr; <span class="mono ${{changed?'out':''}}">${{esc(c.a)}}</span>
        ${{c.k?'':`<br>want <span class=mono>${{esc(c.w)}}</span>`}}</div>
    </div>`;
  }}).join('');
}}
gq.oninput=gfam.onchange=glang.onchange=gst.onchange=renderGen;
</script>
"""


def main(results: str = "evals/results/baseline", out: str = "evals/results/explorer.html") -> int:
    path = build(
        ROOT / results,
        ROOT / "evals" / "data" / "tier_c_application.jsonl",
        ROOT / out,
    )
    print(f"case explorer written to {path}")
    print("open it in a browser - no server, no network, no dependencies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
