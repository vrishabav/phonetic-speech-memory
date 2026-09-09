"""The demonstration, as one self-contained page.

No build step, no framework, no CDN. That is a reviewing decision rather than an
aesthetic one: `make serve` has to work on a fresh clone with no network, and a
reviewer should be able to read the whole client in one sitting and satisfy
themselves that the interesting behaviour is in the engine rather than in the
JavaScript.

The page is shaped like the stage of the product this project actually occupies.
Recognition is upstream and not ours: the system's input is text a recogniser
already produced, and its contract is to take that text and the formatter's
version of it and return a memory-aware result with the reasoning attached. So
the page gives you the two inputs and shows three lines in order:

    asr text   what the recogniser produced (given)
    formatted  what the formatting stage made of it
    final      what memory did, with the change highlighted

and underneath, always, why - every policy that had an opinion, its weight, and
the sentence it gave for it.

Two things sit around that. The case explorer is embedded rather than left as a
file on disk - eight prepared examples are an illustration, and all 1,926
evaluation cases are the argument. And every failure is reported with the
server's own words: an earlier version answered a perfectly clear
`no such table: lexeme` with "API unreachable", which described this client's
confusion rather than the server's problem.

There is deliberately no microphone here. An earlier version bundled a local
recogniser so a reviewer could speak into the page, and it was the wrong trade:
a small offline model's accuracy became the thing under evaluation instead of
the memory system, and a bad transcript made a correct abstention look like a
bug. Typing the recogniser output - or clicking a prepared case - puts the
system under test back in the centre, and matches exactly the contract the
evaluation harness uses.
"""

from __future__ import annotations

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>phonetic-speech-memory</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Ctext y='13' font-size='13'%3E%F0%9F%97%A3%3C/text%3E%3C/svg%3E">
<style>
  :root{
    --bg:#f7f7f5; --panel:#fff; --ink:#17181b; --muted:#6b6d75; --line:#e5e5e1;
    --accent:#2f5d50; --accent-soft:#e8f1ed;
    --apply:#12734a; --apply-bg:#e6f4ec;
    --propose:#8a5a06; --propose-bg:#fdf3e2;
    --abstain:#4e4e66; --abstain-bg:#eeeef4;
    --mark:#ffe98a; --code:#f1f1ee; --rec:#c0392b;
  }
  @media (prefers-color-scheme:dark){
    :root{
      --bg:#151619; --panel:#1c1e22; --ink:#e9e9e6; --muted:#9a9ca3; --line:#2c2f35;
      --accent:#7fc0a9; --accent-soft:#1e2b27;
      --apply:#5fca8f; --apply-bg:#16281f;
      --propose:#e0ab4d; --propose-bg:#2a2317;
      --abstain:#a5a5c4; --abstain-bg:#20212b;
      --mark:#6a5c1d; --code:#24262b; --rec:#e06c5f;
    }
  }
  *{box-sizing:border-box}
  [hidden]{display:none!important}
  body{margin:0;background:var(--bg);color:var(--ink);
    font:15px/1.55 ui-sans-serif,system-ui,"Segoe UI",Roboto,"Noto Sans","Noto Sans Devanagari",sans-serif}
  header{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;
    padding:16px 26px;border-bottom:1px solid var(--line);background:var(--panel)}
  header h1{margin:0;font-size:17px;letter-spacing:-.01em}
  .chip{font-size:11.5px;padding:2px 8px;border-radius:20px;background:var(--code);
    color:var(--muted);white-space:nowrap}
  .chip.live{background:var(--accent-soft);color:var(--accent);font-weight:600}
  main{max-width:1240px;margin:0 auto;padding:20px 26px 90px;
    display:grid;grid-template-columns:minmax(0,1.25fr) minmax(0,1fr);gap:20px}
  @media (max-width:980px){main{grid-template-columns:1fr}}
  section{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:16px 18px}
  section.wide{grid-column:1/-1}
  h2{margin:0 0 3px;font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--accent)}
  .hint{margin:0 0 14px;color:var(--muted);font-size:13px}
  label{display:block;font-size:12px;color:var(--muted);margin:12px 0 4px}
  input,textarea,select,button{font:inherit;color:inherit}
  input,textarea,select{width:100%;padding:8px 10px;border:1px solid var(--line);
    border-radius:7px;background:var(--bg)}
  textarea{resize:vertical;min-height:52px}
  button{padding:8px 15px;border:1px solid var(--line);border-radius:8px;
    background:var(--accent);color:#fff;cursor:pointer;font-weight:600}
  button.ghost{background:transparent;color:var(--ink);font-weight:500}
  button:disabled{opacity:.5;cursor:not-allowed}
  button:hover:not(:disabled){filter:brightness(1.07)}
  .row{display:flex;gap:9px;align-items:center;flex-wrap:wrap;margin-top:12px}
  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
  @media (max-width:620px){.grid2{grid-template-columns:1fr}}

  /* ---- the three-line pipeline view ---- */
  .stage{margin-top:16px;border-left:3px solid var(--line);padding:0 0 0 13px}
  .stage.on{border-left-color:var(--accent)}
  .stage .lbl{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted)}
  .stage .val{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:13.5px;
    padding:7px 10px;background:var(--code);border-radius:7px;margin-top:4px;
    white-space:pre-wrap;word-break:break-word;min-height:34px}
  .stage.final .val{background:var(--apply-bg);border:1px solid var(--apply)}
  .stage .note{font-size:12px;color:var(--muted);margin-top:4px}
  mark{background:var(--mark);color:inherit;border-radius:3px;padding:0 2px;font-weight:600}

  .verdict{display:inline-block;font-size:10.5px;font-weight:700;letter-spacing:.07em;
    text-transform:uppercase;padding:2px 8px;border-radius:20px}
  .apply{background:var(--apply-bg);color:var(--apply)}
  .propose{background:var(--propose-bg);color:var(--propose)}
  .abstain{background:var(--abstain-bg);color:var(--abstain)}
  .res{border-left:3px solid var(--line);padding:9px 0 9px 13px;margin:13px 0}
  .res.apply{border-color:var(--apply)} .res.propose{border-color:var(--propose)}
  .res.abstain{border-color:var(--abstain)}
  table{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}
  th{text-align:left;font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;
    color:var(--muted);font-weight:600;padding:4px 8px 4px 0;border-bottom:1px solid var(--line)}
  td{padding:4px 8px 4px 0;border-bottom:1px solid var(--line);vertical-align:top}
  td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
  .mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.5px}
  .muted{color:var(--muted)} .small{font-size:12px}
  .pill{display:inline-block;font-size:11px;padding:1px 6px;border-radius:4px;
    background:var(--code);color:var(--muted);margin:0 4px 3px 0}
  .examples button{background:var(--code);color:var(--ink);font-weight:500;
    font-size:12px;padding:6px 10px;margin:0 5px 5px 0;text-align:left;border:1px solid var(--line)}
  .flash{font-size:12px;min-height:16px;color:var(--apply)}
  .err{color:var(--rec)}
  details summary{cursor:pointer;font-size:12px;color:var(--muted);margin-top:10px}
  pre{background:var(--code);padding:10px;border-radius:7px;overflow-x:auto;font-size:11.5px;margin:6px 0 0}
  kbd{font:inherit;font-size:11px;background:var(--code);border:1px solid var(--line);
    border-radius:4px;padding:0 4px}
  a{color:var(--accent)}
  a.chip{text-decoration:none;background:var(--accent-soft);color:var(--accent);font-weight:600}
  a.chip:hover{filter:brightness(1.07)}

  /* A server-side failure has to arrive as a sentence, not as a blank box. */
  .banner{grid-column:1/-1;padding:11px 14px;border-radius:9px;font-size:13px;
    background:var(--propose-bg);border:1px solid var(--propose);color:var(--propose)}
  .banner b{display:block;margin-bottom:2px}
  .banner code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px}

  iframe{width:100%;height:78vh;border:1px solid var(--line);border-radius:9px;
    background:var(--panel);display:block;margin-top:12px}
</style>
</head>
<body>
<header>
  <h1>phonetic-speech-memory</h1>
  <span class="chip" id="c-mem">…</span>
  <span class="chip" id="c-llm">…</span>
  <a class="chip" href="/explorer" target="_blank" rel="noopener">1,926 evaluation cases ↗</a>
</header>

<main>

<div class="banner" id="banner" hidden></div>

<!-- =================== dictate =================== -->
<section>
  <h2>Dictate</h2>
  <p class="hint">Recognition happens upstream of this system. Give it what a
     recogniser produced - a colleague's name it has never heard, a product name
     it turned into a common word - and, if you want, what the formatter made of
     that. You will see what memory did about it, and why.</p>

  <label for="asr">ASR text - what the recogniser produced</label>
  <textarea id="asr">ask adith narayanan to review the pull request</textarea>
  <label for="fmt">Formatted text - leave blank to run the formatting stage too</label>
  <textarea id="fmt">Ask Adith Narayanan to review the pull request.</textarea>

  <div class="grid2" style="margin-top:12px">
    <div>
      <label for="app">Dictating into</label>
      <select id="app">
        <option value="com.tinyspeck.slackmacgap">Slack</option>
        <option value="com.microsoft.Outlook">Mail (Outlook)</option>
        <option value="com.microsoft.VSCode">VS Code</option>
        <option value="com.apple.Notes">Notes</option>
        <option value="">no app / global</option>
      </select>
    </div>
    <div>
      <label for="screen">On screen around the cursor (optional)</label>
      <input id="screen" placeholder="e.g. a code review thread">
    </div>
  </div>

  <div class="row">
    <button onclick="run()">Run</button>
    <span class="small muted">or <kbd>Ctrl</kbd>+<kbd>Enter</kbd> in either box</span>
    <span class="flash" id="flash"></span>
  </div>

  <div class="stage" id="s-heard"><div class="lbl">1 · what the recogniser produced</div>
    <div class="val" id="v-heard">-</div><div class="note" id="n-heard"></div></div>
  <div class="stage" id="s-fmt"><div class="lbl">2 · after formatting</div>
    <div class="val" id="v-fmt">-</div></div>
  <div class="stage final" id="s-final"><div class="lbl">3 · after memory</div>
    <div class="val" id="v-final">-</div><div class="note" id="n-final"></div></div>

  <div id="why"></div>

  <div class="examples" style="margin-top:18px">
    <div class="small muted" style="margin-bottom:6px">Or run a prepared case.
      Three of these are ones where the right answer is to change nothing -
      those are what a find-and-replace dictionary gets wrong:</div>
    <div id="ex"></div>
  </div>
</section>

<!-- =================== teach =================== -->
<section>
  <h2>Teach it</h2>
  <p class="hint">Give it one piece of evidence and watch memory move. The response
     reports what actually changed, not just that it was accepted.</p>
  <div class="grid2">
    <div><label for="obefore">Heard as</label>
      <input id="obefore" placeholder="Shreya Bhattacharya"></div>
    <div><label for="oafter">Should be</label>
      <input id="oafter" placeholder="Shreyaa Bhattacharya"></div>
  </div>
  <div class="grid2">
    <div><label for="osource">Kind of evidence</label>
      <select id="osource">
        <option value="post_edit">post_edit - the user fixed inserted text</option>
        <option value="declared">declared - the user added the term</option>
        <option value="instruction">instruction - a rule, in words</option>
        <option value="ambient">ambient - only seen on screen</option>
        <option value="revert">revert - the user undid our change</option>
        <option value="dismissal">dismissal - the user declined a proposal</option>
      </select></div>
    <div><label for="oapp">Scope</label>
      <select id="oapp"><option value="">global</option>
        <option value="com.tinyspeck.slackmacgap">Slack only</option>
        <option value="com.microsoft.Outlook">Mail only</option></select></div>
  </div>
  <label for="onote">Standing instruction, in the user's own words (optional)</label>
  <input id="onote" placeholder="always spell it with two a's">
  <div class="row"><button onclick="observe()">Record evidence</button>
    <span class="flash" id="oflash"></span></div>
  <div id="ochanges"></div>

  <details><summary>What the states mean</summary>
    <p class="small muted">A term is <b>proposed</b> when it is known but not yet
    trusted enough to apply - one sighting is not evidence. It becomes
    <b>active</b> once both belief (confidence) and evidence mass (strength) pass
    threshold. It decays to <b>dormant</b> through disuse, and applies again only
    with contextual support. Two reverts make it <b>suppressed</b>. None of these
    is stored: all four are recomputed from the observation log every time.</p>
  </details>
</section>

<!-- =================== memory =================== -->
<section class="wide">
  <h2>Memory</h2>
  <p class="hint">Everything the system believes, and the evidence behind it.
    <span class="muted">Confidence is the mean of a Beta posterior; strength is how much
    decayed evidence stands behind it. Both must pass threshold before a term is applied -
    which is why a single sighting proposes rather than acts.</span></p>
  <div class="row">
    <input id="mq" placeholder="filter by term or heard-form" style="flex:1 1 220px;min-width:170px">
    <select id="mstate" style="flex:0 0 150px">
      <option value="">every state</option><option value="active">active</option>
      <option value="proposed">proposed</option><option value="dormant">dormant</option>
      <option value="suppressed">suppressed</option><option value="retired">retired</option>
    </select>
    <button class="ghost" onclick="loadMemory()">Refresh</button>
    <button class="ghost" onclick="reset()">Reset to the seeded persona</button>
    <span class="flash" id="mflash"></span>
  </div>
  <div id="memory"></div>
</section>

<!-- =================== the evidence =================== -->
<section class="wide">
  <h2>The evidence</h2>
  <p class="hint">The demo shows you eight cases. The evaluation is 1,926, and it is
    the part worth judging: every case, the decision it got, and the memory that
    produced it - the 69 hand-written specification cases in full detail, and all
    1,842 derived cases filterable by family, script, confusion rule and pass/fail.
    <span class="muted">Set the filter to <b>failing only</b>: there are three, and
    they are all the same shape.</span></p>
  <div class="row">
    <button id="ex-load">Open the case explorer here</button>
    <a href="/explorer" target="_blank" rel="noopener">or in a new tab ↗</a>
    <span class="flash" id="ex-flash"></span>
  </div>
  <iframe id="ex-frame" title="the case explorer" hidden></iframe>
</section>

</main>

<script>
const $ = id => document.getElementById(id);
const esc = s => (s??'').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

/* Highlight the changed region. Boundaries are pushed off combining marks so a
   Devanagari matra is never highlighted alone - the same problem, and the same
   fix, as in evals/explorer.py. */
const combining = ch => /\p{M}/u.test(ch);
function diff(before, after){
  if(before === after) return esc(after);
  let h = 0;
  while(h < Math.min(before.length, after.length) && before[h] === after[h]) h++;
  let t = 0;
  while(t < Math.min(before.length, after.length) - h &&
        before[before.length-1-t] === after[after.length-1-t]) t++;
  let end = after.length - t;
  while(h > 0 && h < after.length && combining(after[h])) h--;
  while(end < after.length && combining(after[end])) end++;
  if(end <= h){ h = Math.max(0, h-1); end = Math.min(after.length, end+1); }
  return esc(after.slice(0,h)) + '<mark>' + esc(after.slice(h,end)) + '</mark>' + esc(after.slice(end));
}

/* Every call goes through here, so every failure gets reported the same way:
   with what actually went wrong. An earlier version said "API unreachable" and
   "unreadable response" for a server that was running fine and answering with a
   perfectly clear error - those strings described the client's confusion rather
   than the server's problem, which is the opposite of what this whole project
   is about. */
function banner(title, detail){
  const el = $('banner');
  el.hidden = false;
  el.innerHTML = `<b>${esc(title)}</b><code>${esc(detail)}</code>`;
  return new Error(detail || title);
}
function clearBanner(){ $('banner').hidden = true; }

async function api(path, opts){
  let r;
  try{
    r = await fetch(path, opts);
  }catch(err){
    throw banner('The server is not answering.',
      `${opts && opts.method || 'GET'} ${path} - ${err.message}. `
      + 'It may have stopped; restart it with `make serve`.');
  }
  const raw = await r.text();
  let body = null;
  try{ body = raw ? JSON.parse(raw) : null; }catch(e){ /* handled below */ }
  if(!r.ok){
    const detail = body && body.detail != null
      ? (typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail))
      : (raw.slice(0, 400) || `no body`);
    throw banner(`${opts && opts.method || 'GET'} ${path} failed with HTTP ${r.status}.`, detail);
  }
  if(body === null){
    throw banner(`${path} answered with something that is not JSON.`, raw.slice(0, 400));
  }
  clearBanner();
  return body;
}

function flash(msg, bad){
  $('flash').textContent = msg || '';
  $('flash').className = 'flash' + (bad ? ' err' : '');
}

/* ================= the pipeline view ================= */

async function runPipeline(asrText, formatted, note){
  $('v-heard').textContent = asrText;
  $('s-heard').classList.add('on');
  $('n-heard').textContent = note || '';

  let d;
  try{
    d = await api('/dictate', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        asr_text: asrText,
        formatted_text: formatted,
        app: $('app').value || null,
        surrounding_text: $('screen').value || null,
      })});
  }catch(err){ $('why').innerHTML = `<p class="err small">${esc(err.message)}</p>`; return; }

  $('v-fmt').textContent = d.formatted_text;
  $('s-fmt').classList.add('on');
  $('v-final').innerHTML = diff(d.formatted_text, d.output_text);
  $('n-final').textContent =
    `${d.summary}  ·  ${d.cost.llm_calls} model call${d.cost.llm_calls===1?'':'s'}`
    + `  ·  ${d.cost.latency_ms.toFixed(2)} ms  ·  gate ${d.gate_passed?'opened':'stayed shut'}`;

  renderWhy(d);
  loadMemory();
}

function renderWhy(d){
  if(!d.resolutions.length){
    $('why').innerHTML = '<p class="small muted" style="margin-top:14px">'
      + 'Nothing in memory resembled this text, so the gate closed before retrieval '
      + 'and the call cost nothing. This is the majority of real dictation.</p>';
    return;
  }
  let html = '<h2 style="margin-top:20px">Why</h2>';
  for(const r of d.resolutions){
    const rows = r.policies.filter(p => p.signal !== 'neutral' || p.rationale).map(p =>
      `<tr><td class="mono">${esc(p.policy)}</td><td class="small">${esc(p.signal)}</td>
           <td class="num">${p.weight>=0?'+':''}${p.weight.toFixed(2)}</td>
           <td class="small">${esc(p.rationale)}</td></tr>`).join('');
    html += `<div class="res ${r.verdict}">
      <div><span class="verdict ${r.verdict}">${r.verdict}</span>
        <span class="mono">${esc(r.span.text)}</span> →
        ${r.replacement ? `<span class="mono">${esc(r.replacement)}</span>`
                        : '<span class="muted">unchanged</span>'}
        <span class="pill">${esc(r.reason)}</span></div>
      <div class="small muted">matched ${esc(r.canonical)} via ${esc(r.matched_via)},
        retrieval ${r.retrieval_score.toFixed(2)}, combined ${r.score.toFixed(2)}</div>
      ${rows?`<table><tr><th>policy</th><th>signal</th><th>weight</th><th>why</th></tr>${rows}</table>`:''}
    </div>`;
  }
  html += `<details><summary>Raw API response</summary><pre>${esc(JSON.stringify(d,null,2))}</pre></details>`;
  $('why').innerHTML = html;
}

/* ================= prepared examples ================= */

const EXAMPLES = [
  {t:'a homophone only memory can settle', asr:'ask adith narayanan to review the pull request',
   fmt:'Ask Adith Narayanan to review the pull request.', app:'com.tinyspeck.slackmacgap'},
  {t:'a product heard as a common word', asr:'the sarvam kiwi service is dropping requests',
   fmt:'The Sarvam Kiwi service is dropping requests.', app:'com.tinyspeck.slackmacgap'},
  {t:'the same word, ordinary sense - must NOT change', asr:'i ate a kiwi for breakfast',
   fmt:'I ate a kiwi for breakfast.', app:'com.microsoft.Outlook'},
  {t:'a Slack handle, in Slack', asr:'i posted the trace in hash eng asr',
   fmt:'I posted the trace in hash eng asr.', app:'com.tinyspeck.slackmacgap'},
  {t:'the same handle, in Mail - must NOT change', asr:'i posted the trace in hash eng asr',
   fmt:'I posted the trace in hash eng asr.', app:'com.microsoft.Outlook'},
  {t:'a mishearing never seen before', asr:'ask aadhith narayanan to review the change',
   fmt:'Ask Aadhith Narayanan to review the change.', app:'com.tinyspeck.slackmacgap'},
  {t:'Devanagari in, Devanagari out', asr:'मिरा शर्मा को भेज दो',
   fmt:'मिरा शर्मा को भेज दो।', app:'com.tinyspeck.slackmacgap'},
  {t:'nothing known here - the gate stays shut, 0 cost',
   asr:'i went through the whole document last night and the only thing i would change is the ordering of the last two sections',
   fmt:'I went through the whole document last night, and the only thing I would change is the ordering of the last two sections.',
   app:'com.microsoft.Outlook'},
];

$('ex').innerHTML = EXAMPLES.map((e,i)=>`<button onclick="runExample(${i})">${e.t}</button>`).join('');
function runExample(i){
  const e = EXAMPLES[i];
  $('app').value = e.app; $('asr').value = e.asr; $('fmt').value = e.fmt;
  flash('');
  runPipeline(e.asr, e.fmt, 'prepared case - the boxes above now hold it, edit and re-run');
}
function run(){
  const asr = $('asr').value.trim();
  if(!asr){ flash('Type what the recogniser produced, or click a prepared case.', true); return; }
  flash('');
  runPipeline(asr, $('fmt').value.trim() === '' ? null : $('fmt').value,
              $('fmt').value.trim() === '' ? 'the formatting stage will run too' : '');
}
['asr','fmt'].forEach(id => $(id).addEventListener('keydown', e => {
  if(e.key === 'Enter' && (e.ctrlKey || e.metaKey)){ e.preventDefault(); run(); }
}));

/* ================= teach ================= */

async function observe(){
  const body = {
    after: $('oafter').value || $('oafter').placeholder,
    before: $('obefore').value || $('obefore').placeholder || null,
    source: $('osource').value,
    app: $('oapp').value || null,
    note: $('onote').value || null,
  };
  try{
    const d = await api('/observations', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
    $('oflash').textContent = 'recorded as ' + d.observation.source;
    $('oflash').className = 'flash';
    $('ochanges').innerHTML = d.memory_changes.length
      ? '<table><tr><th>term</th><th>what changed</th></tr>' + d.memory_changes.map(c =>
          `<tr><td>${esc(c.canonical)}</td><td class="small">${esc(c.change)}</td></tr>`).join('') + '</table>'
      : '<p class="small muted">No memory changed. That is a real answer: evidence the '
        + 'learner judges non-phonetic - a rewrite rather than a correction - is logged and ignored.</p>';
    loadMemory();
  }catch(err){ $('oflash').textContent = err.message; $('oflash').className = 'flash err'; }
}

/* ================= memory ================= */

async function loadMemory(){
  const p = new URLSearchParams();
  if($('mq').value) p.set('q', $('mq').value);
  if($('mstate').value) p.set('state', $('mstate').value);
  const d = await api('/memory?' + p);
  $('c-mem').textContent = d.count + ' terms in memory';
  $('memory').innerHTML = `<table>
    <tr><th>term</th><th>state</th><th>conf</th><th>strength</th>
        <th>heard as</th><th>guards</th><th>standing instruction</th></tr>
    ${d.lexemes.map(l => `<tr>
        <td>${esc(l.canonical)}<div class="small muted">${esc(l.kind)}</div></td>
        <td class="small">${esc(l.state)}</td>
        <td class="num">${l.confidence.toFixed(2)}</td>
        <td class="num">${l.strength.toFixed(2)}</td>
        <td class="small">${l.variants.map(v =>
            `<span class="pill">${esc(v.form)} · ${esc(v.provenance)}${v.count?' · '+v.count+'×':''}</span>`
          ).join('') || '<span class="muted">-</span>'}</td>
        <td class="small">${l.guards.map(g=>`<span class="pill">${esc(g.kind)}</span>`).join('')
          || '<span class="muted">-</span>'}</td>
        <td class="small">${l.instruction ? esc(l.instruction) : '<span class="muted">-</span>'}</td>
      </tr>`).join('')}</table>
    <p class="small muted">${d.count} term${d.count===1?'':'s'}</p>`;
}

async function reset(){
  await api('/reset', {method:'POST'});
  $('mflash').textContent = 'back to the seeded persona';
  setTimeout(() => $('mflash').textContent = '', 2500);
  $('ochanges').innerHTML = ''; $('why').innerHTML = ''; flash('');
  ['v-heard','v-fmt','v-final'].forEach(id => $(id).textContent = '-');
  ['s-heard','s-fmt'].forEach(id => $(id).classList.remove('on'));
  loadMemory();
}

$('mq').oninput = loadMemory;
$('mstate').onchange = loadMemory;

/* ================= the case explorer ================= */

$('ex-load').onclick = () => {
  const frame = $('ex-frame'), btn = $('ex-load');
  if(!frame.hidden){
    frame.hidden = true; btn.textContent = 'Open the case explorer here';
    $('ex-flash').textContent = ''; return;
  }
  btn.textContent = 'Hide the case explorer';
  frame.hidden = false;
  if(!frame.src){
    $('ex-flash').textContent = 'loading - if it has never been built, the server '
      + 'builds it now, which takes a second or two';
    frame.onload = () => { $('ex-flash').textContent = ''; };
    frame.src = '/explorer';
  }
  frame.scrollIntoView({behavior:'smooth', block:'start'});
};

/* ================= boot ================= */

api('/health').then(h => {
  $('c-llm').textContent = h.components.policies.length + ' policies · llm: ' + h.components.llm;
  $('c-llm').className = 'chip live';
}).catch(() => { $('c-llm').textContent = 'API unreachable'; });

loadMemory().catch(() => { $('c-mem').textContent = 'memory unreadable'; });
</script>
</body>
</html>
"""
