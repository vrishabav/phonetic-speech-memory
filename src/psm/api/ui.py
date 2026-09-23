"""The demonstration, as one self-contained page.

No build step, no framework, no CDN. That is a reviewing decision rather than an
aesthetic one: `make serve` has to work on a fresh clone with no network, and a
reviewer should be able to read the whole client in one sitting and satisfy
themselves that the interesting behaviour is in the engine rather than in the
JavaScript.

The page is shaped like the product this system sits inside rather than like the
API it sits behind. A person using a dictation tool does not think in terms of
"ASR output" and "formatted output"; they see text appear, and either it is
right or they fix it. So the page leads with the text and one action, and keeps
the machinery a click away:

    dictate      the text as it would arrive, what memory did to it, and why
    dictionary   the words this person expects to see spelled their way
    memory       the same words as state: confidence, evidence, guards
    evaluation   all 1,926 cases, because eight examples are an illustration

**Correcting the whole text is the primary way to teach it.** The result is
editable in place. Edit a word, and the correction is what gets recorded, not
the sentence around it: the learner diffs the two versions and scores only the
span that moved, so a paragraph with one name fixed in it teaches one name. The
answer shows exactly which words were taken, which is the only way to see that
the sentence was not stored.

**Why there is one text box and not two.** The brief names three versions of a
transcript and the API takes two of them, because the evaluation pins the
formatted text so that memory can be measured on its own. But the memory system
reads only the formatted text: the recogniser's raw output changes nothing about
any decision offline, and asking for it up front made the first screen an
exercise in imagining two stages of a pipeline. It is still there, under
`raw recogniser text`, because it is a real input to the live formatting stage
and because the brief asks that new ASR and formatted outputs can both be
provided. It is simply no longer the price of a first look.

There is deliberately no microphone here. An earlier version bundled a local
recogniser so a reviewer could speak into the page, and it was the wrong trade:
a small offline model's accuracy became the thing under evaluation instead of
the memory system, and a bad transcript made a correct abstention look like a
bug.

Every failure is reported with the server's own words. An earlier version
answered a perfectly clear `no such table: lexeme` with "API unreachable", which
described this client's confusion rather than the server's problem.
"""

from __future__ import annotations

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>phonetic-speech-memory</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Ccircle cx='8' cy='8' r='6' fill='%237fc08d'/%3E%3C/svg%3E">
<style>
  /* Dark by default, because that is the room this kind of tool lives in.
     Light is a full override rather than an afterthought. */
  :root{
    --bg:#0e1110; --panel:#161a18; --raised:#1d2320; --ink:#e7eae6; --dim:#9aa39c;
    --line:#252c28; --accent:#7fc08d; --accent-ink:#0e1110; --soft:#1a241d;
    --apply:#7fc08d; --apply-bg:#16241b;
    --propose:#e0b45d; --propose-bg:#262016;
    --abstain:#9aa3bb; --abstain-bg:#1b1f26;
    --mark:#2f4a34; --mark-ink:#cdeccf; --bad:#e88374;
    --serif:ui-serif,Georgia,"Iowan Old Style","Times New Roman",serif;
    --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  }
  @media (prefers-color-scheme:light){
    :root{
      --bg:#f6f7f4; --panel:#fff; --raised:#f1f3ee; --ink:#171a18; --dim:#646b65;
      --line:#e3e6df; --accent:#2f6b47; --accent-ink:#fff; --soft:#e9f2ec;
      --apply:#1d7346; --apply-bg:#e7f4ec;
      --propose:#8a5a06; --propose-bg:#fdf3e2;
      --abstain:#4e5266; --abstain-bg:#eef0f5;
      --mark:#cdeccf; --mark-ink:#12331c; --bad:#b93c2b;
    }
  }
  *{box-sizing:border-box}
  [hidden]{display:none!important}
  body{margin:0;background:var(--bg);color:var(--ink);
    font:15px/1.6 ui-sans-serif,system-ui,"Segoe UI",Roboto,"Noto Sans","Noto Sans Devanagari",sans-serif;
    -webkit-font-smoothing:antialiased}

  /* ---------- chrome ---------- */
  header{position:sticky;top:0;z-index:5;background:var(--panel);
    border-bottom:1px solid var(--line);padding:0 22px}
  .bar{max-width:1180px;margin:0 auto;display:flex;align-items:center;gap:18px;
    height:56px;flex-wrap:wrap}
  .brand{font-family:var(--serif);font-size:20px;letter-spacing:-.01em;margin-right:2px}
  .brand i{font-style:normal;color:var(--accent)}
  nav{display:flex;gap:2px;margin-left:auto;order:3;width:100%;
    border-top:1px solid var(--line);padding-top:2px}
  @media (min-width:880px){nav{order:0;width:auto;border-top:0;padding-top:0}}
  nav button{background:none;border:0;color:var(--dim);font:inherit;font-size:13.5px;
    padding:8px 12px;cursor:pointer;border-radius:7px;border-bottom:2px solid transparent}
  nav button:hover{color:var(--ink)}
  nav button[aria-current=page]{color:var(--ink);border-bottom-color:var(--accent);font-weight:600}
  .chips{display:flex;gap:7px;align-items:center;margin-left:auto}
  .chip{font-size:11.5px;padding:2px 9px;border-radius:20px;background:var(--raised);
    color:var(--dim);white-space:nowrap;text-decoration:none}
  a.chip:hover{color:var(--ink)}
  .chip.on{background:var(--soft);color:var(--accent);font-weight:600}

  main{max-width:1180px;margin:0 auto;padding:22px 22px 100px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:14px;
    padding:20px 22px;margin-bottom:16px}
  .display{font-family:var(--serif);font-size:24px;font-weight:400;margin:0 0 4px;
    letter-spacing:-.015em}
  .display em{font-style:italic;color:var(--accent)}
  h3{font-size:11.5px;text-transform:uppercase;letter-spacing:.09em;color:var(--dim);
    margin:0 0 8px;font-weight:600}
  .hint{margin:0 0 16px;color:var(--dim);font-size:13.5px;max-width:74ch}
  .muted{color:var(--dim)} .small{font-size:12.5px}
  .mono{font-family:var(--mono);font-size:12.5px}

  /* ---------- controls ---------- */
  label{display:block;font-size:12px;color:var(--dim);margin:0 0 5px}
  input,textarea,select,button{font:inherit;color:inherit}
  input,textarea,select{width:100%;padding:10px 12px;border:1px solid var(--line);
    border-radius:9px;background:var(--bg)}
  input:focus,textarea:focus,select:focus{outline:2px solid var(--accent);outline-offset:-1px}
  textarea{resize:vertical;min-height:58px;line-height:1.55}
  textarea.big{min-height:92px;font-size:16px}
  button{padding:9px 16px;border:1px solid transparent;border-radius:9px;
    background:var(--accent);color:var(--accent-ink);cursor:pointer;font-weight:600;font-size:14px}
  button.ghost{background:transparent;color:var(--ink);border-color:var(--line);font-weight:500}
  button.ghost:hover{background:var(--raised)}
  button.tiny{padding:5px 10px;font-size:12px}
  button:disabled{opacity:.45;cursor:not-allowed}
  button:hover:not(:disabled){filter:brightness(1.08)}
  .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  .row.top{margin-top:14px}
  .fields{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:14px}
  @media (max-width:660px){.fields{grid-template-columns:1fr}}
  .flash{font-size:12.5px;color:var(--accent)}
  .flash.err{color:var(--bad)}
  kbd{font:inherit;font-size:11px;background:var(--raised);border:1px solid var(--line);
    border-radius:4px;padding:1px 5px}
  details{margin-top:14px}
  details summary{cursor:pointer;font-size:12.5px;color:var(--dim);list-style:none}
  details summary::-webkit-details-marker{display:none}
  details summary:before{content:"+ ";color:var(--accent);font-weight:700}
  details[open] summary:before{content:"- "}
  details summary:hover{color:var(--ink)}
  pre{background:var(--raised);padding:12px;border-radius:9px;overflow-x:auto;
    font-size:11.5px;margin:8px 0 0}

  /* ---------- the result ---------- */
  .result{border-color:var(--line)}
  .result.acted{border-color:var(--apply)}
  .rhead{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:12px}
  .out{font-size:19px;line-height:1.5;font-family:var(--serif);padding:16px 18px;
    background:var(--raised);border-radius:11px;white-space:pre-wrap;word-break:break-word}
  .result.acted .out{background:var(--apply-bg)}
  mark{background:var(--mark);color:var(--mark-ink);border-radius:4px;padding:1px 4px;
    font-weight:600;font-style:normal}
  .was{font-size:12.5px;color:var(--dim);margin-top:9px}
  .was s{opacity:.75}
  .meta{font-size:12px;color:var(--dim);font-family:var(--mono)}

  /* ---------- correcting the text ---------- */
  .fix{margin-top:18px;border-top:1px dashed var(--line);padding-top:16px}
  .fix textarea{font-family:var(--serif);font-size:16px;min-height:76px}
  .learned{margin-top:12px;background:var(--soft);border-radius:10px;padding:12px 14px;
    font-size:13px}
  .learned .pair{font-family:var(--mono);font-size:13px}
  .learned s{color:var(--dim)}
  .arrow{color:var(--accent);padding:0 7px;font-weight:700}

  /* ---------- verdicts and the why panel ---------- */
  .verdict{display:inline-block;font-size:10.5px;font-weight:700;letter-spacing:.08em;
    text-transform:uppercase;padding:3px 9px;border-radius:20px}
  .apply{background:var(--apply-bg);color:var(--apply)}
  .propose{background:var(--propose-bg);color:var(--propose)}
  .abstain{background:var(--abstain-bg);color:var(--abstain)}
  .res{border:1px solid var(--line);border-left-width:3px;border-radius:10px;
    padding:12px 14px;margin:10px 0;background:var(--bg)}
  .res.apply{border-left-color:var(--apply)}
  .res.propose{border-left-color:var(--propose)}
  .res.abstain{border-left-color:var(--abstain)}
  .res summary{list-style:none;font-size:12.5px;color:var(--dim)}
  .sig{font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;font-weight:700}
  .sig.support{color:var(--apply)} .sig.oppose{color:var(--propose)}
  .sig.veto{color:var(--bad)} .sig.neutral{color:var(--dim)}
  table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}
  th{text-align:left;font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;
    color:var(--dim);font-weight:600;padding:5px 10px 5px 0;border-bottom:1px solid var(--line)}
  td{padding:6px 10px 6px 0;border-bottom:1px solid var(--line);vertical-align:top}
  td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap;font-family:var(--mono)}
  .pill{display:inline-block;font-size:11px;padding:2px 7px;border-radius:5px;
    background:var(--raised);color:var(--dim);margin:0 4px 4px 0;font-family:var(--mono)}
  .pill.ok{background:var(--soft);color:var(--accent)}

  /* ---------- examples ---------- */
  .ex{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:9px}
  .ex button{background:var(--raised);color:var(--ink);border:1px solid var(--line);
    font-weight:500;font-size:12.5px;text-align:left;padding:11px 13px;line-height:1.4}
  .ex button:hover{border-color:var(--accent)}
  .ex button b{display:block;font-weight:600;margin-bottom:2px}
  .ex button span{color:var(--dim);font-size:11.5px}

  /* ---------- dictionary entries ---------- */
  .entry{display:flex;gap:16px;align-items:flex-start;padding:13px 0;
    border-bottom:1px solid var(--line);flex-wrap:wrap}
  .entry .term{font-family:var(--serif);font-size:17px;min-width:170px;flex:0 0 auto}
  .entry .term small{display:block;font-family:var(--mono);font-size:11px;color:var(--dim)}
  .entry .forms{flex:1 1 260px}
  .entry .instr{flex:1 1 100%;font-size:12.5px;color:var(--dim);font-style:italic}
  .state{font-size:10.5px;text-transform:uppercase;letter-spacing:.07em;font-weight:700;
    padding:3px 9px;border-radius:20px;white-space:nowrap}
  .state.active{background:var(--apply-bg);color:var(--apply)}
  .state.proposed{background:var(--propose-bg);color:var(--propose)}
  .state.dormant{background:var(--abstain-bg);color:var(--abstain)}
  .state.suppressed,.state.retired{background:var(--raised);color:var(--bad)}

  .banner{padding:13px 16px;border-radius:11px;font-size:13px;margin-bottom:16px;
    background:var(--propose-bg);border:1px solid var(--propose);color:var(--propose)}
  .banner b{display:block;margin-bottom:3px}
  .banner code{font-family:var(--mono);font-size:12px}
  iframe{width:100%;height:76vh;border:1px solid var(--line);border-radius:11px;
    background:var(--panel);display:block;margin-top:14px}
</style>
</head>
<body>

<header>
  <div class="bar">
    <div class="brand">phonetic <i>memory</i></div>
    <nav>
      <button data-tab="dictate" aria-current="page">dictate</button>
      <button data-tab="dictionary">dictionary</button>
      <button data-tab="memory">memory</button>
      <button data-tab="evaluation">evaluation</button>
    </nav>
    <div class="chips">
      <span class="chip" id="c-mem">...</span>
      <span class="chip" id="c-llm">...</span>
      <button class="ghost tiny" id="b-reset" title="back to the seeded persona">reset</button>
    </div>
  </div>
</header>

<main>
<div class="banner" id="banner" hidden></div>

<!-- ============================ dictate ============================ -->
<div class="tab" id="t-dictate">

  <section class="card">
    <h2 class="display">the text, as it would <em>arrive</em></h2>
    <p class="hint">This is what a person sees appear in the app they are typing
      into. Memory reads this text and decides whether any word in it should be
      spelled differently for this person, here. Most of the time it decides
      nothing should change.</p>

    <label for="fmt">what Kivi wrote</label>
    <textarea id="fmt" class="big">Ask Adith Narayanan to review the pull request.</textarea>

    <div class="fields">
      <div>
        <label for="app">dictating into</label>
        <select id="app">
          <option value="com.tinyspeck.slackmacgap">Slack</option>
          <option value="com.microsoft.Outlook">Mail</option>
          <option value="com.microsoft.VSCode">VS Code</option>
          <option value="com.apple.Notes">Notes</option>
          <option value="">no app / global</option>
        </select>
      </div>
      <div>
        <label for="screen">on screen around the cursor (optional)</label>
        <input id="screen" placeholder="e.g. a code review thread">
      </div>
    </div>

    <details id="adv">
      <summary>raw recogniser text (optional)</summary>
      <p class="hint" style="margin:10px 0 8px">The recogniser runs upstream of
        this system and its raw output changes no decision here: offline, every
        policy reads the formatted text above. It matters to the live formatting
        stage, which is given memory and this text and asked to produce the
        line above, and it is kept on the record for every call. Leave it blank
        and the configured formatter runs on the text above instead.</p>
      <label for="asr">what the recogniser produced</label>
      <textarea id="asr">ask adith narayanan to review the pull request</textarea>
    </details>

    <div class="row top">
      <button id="b-run">run it</button>
      <span class="small muted"><kbd>Ctrl</kbd>+<kbd>Enter</kbd></span>
      <span class="flash" id="flash"></span>
    </div>
  </section>

  <section class="card result" id="result" hidden>
    <div class="rhead">
      <span class="verdict" id="r-badge">abstain</span>
      <span class="meta" id="r-meta"></span>
    </div>
    <div class="out" id="r-out"></div>
    <div class="was" id="r-was" hidden></div>
    <div id="r-proposed"></div>

    <div class="fix">
      <label for="fix">not right? edit it here. Kivi keeps only what you change.</label>
      <textarea id="fix"></textarea>
      <div class="row top">
        <button id="b-fix">save my correction</button>
        <button class="ghost" id="b-undo" hidden>undo what memory did</button>
        <span class="flash" id="fixflash"></span>
      </div>
      <div id="learned"></div>
    </div>
  </section>

  <section class="card" id="whycard" hidden>
    <h3>why it did or did not act</h3>
    <div id="why"></div>
  </section>

  <section class="card">
    <h3>or try one of these</h3>
    <p class="hint">Three of them are cases where the right answer is to change
      nothing. Those are the ones a find-and-replace dictionary gets wrong, and
      they are the reason this system is more than a lookup table.</p>
    <div class="ex" id="ex"></div>
  </section>
</div>

<!-- ============================ dictionary ============================ -->
<div class="tab" id="t-dictionary" hidden>

  <section class="card">
    <h2 class="display">words Kivi never <em>misspells</em></h2>
    <p class="hint">Two ways in. Tell it a spelling, or tell it a rule in your own
      words. A spelling you give it yourself counts immediately: you are the
      authority on your colleague's name, and making you say it twice would be
      the product arguing with you.</p>

    <h3 style="margin-top:20px">teach it a term</h3>
    <div class="fields" style="margin-top:0">
      <div><label for="d-heard">you say</label>
        <input id="d-heard" placeholder="shreya bhattacharya"></div>
      <div><label for="d-write">Kivi writes</label>
        <input id="d-write" placeholder="Shreyaa Bhattacharya"></div>
    </div>
    <div class="row top">
      <button id="b-teach">add to dictionary</button>
      <span class="flash" id="dflash"></span>
    </div>

    <h3 style="margin-top:26px">or tell it a rule</h3>
    <label for="d-rule">say it the way you would say it to a person</label>
    <input id="d-rule" placeholder="always write it Aadith with two a's">
    <div class="row top">
      <button class="ghost" id="b-rule">tell Kivi</button>
      <span class="flash" id="rflash"></span>
    </div>
    <p class="hint" style="margin:12px 0 0">A rule is kept in your words rather
      than compiled into a substitution, because it travels into the formatting
      prompt where a model can act on it in context. That is the class of thing
      no replace table can do.</p>

    <div id="dchanges"></div>
  </section>

  <section class="card">
    <h3>everything it knows</h3>
    <div class="row" style="margin-bottom:6px">
      <input id="dq" placeholder="search terms and heard-as forms" style="flex:1 1 240px">
    </div>
    <div id="dict"></div>
  </section>
</div>

<!-- ============================ memory ============================ -->
<div class="tab" id="t-memory" hidden>
  <section class="card">
    <h2 class="display">the same words, as <em>state</em></h2>
    <p class="hint">Nothing here is stored. Every row is recomputed from the
      observation log each time it is read: confidence is the mean of a Beta
      posterior, strength is how much decayed evidence stands behind it, and the
      state follows from the two. Both have to pass threshold before a term is
      applied, which is why one sighting proposes rather than acts.</p>
    <div class="row">
      <input id="mq" placeholder="filter by term or heard-form" style="flex:1 1 220px">
      <select id="mstate" style="flex:0 0 160px">
        <option value="">every state</option><option value="active">active</option>
        <option value="proposed">proposed</option><option value="dormant">dormant</option>
        <option value="suppressed">suppressed</option><option value="retired">retired</option>
      </select>
      <button class="ghost" id="b-refresh">refresh</button>
      <span class="flash" id="mflash"></span>
    </div>
    <div id="memory"></div>
    <details>
      <summary>what the states mean</summary>
      <p class="small muted" style="margin-top:8px">A term is <b>proposed</b> when
      it is known but not yet trusted enough to apply. It becomes <b>active</b>
      once both belief and evidence mass pass threshold. It decays to
      <b>dormant</b> through disuse and then applies only with contextual
      support. Two reverts in one scope make it <b>suppressed</b>. A deleted or
      renamed term is <b>retired</b> and keeps a tombstone, so a later sighting
      does not silently recreate what you removed.</p>
    </details>
  </section>
</div>

<!-- ============================ evaluation ============================ -->
<div class="tab" id="t-evaluation" hidden>
  <section class="card">
    <h2 class="display">eight examples are an illustration. <em>1,926 cases</em> are the argument.</h2>
    <p class="hint">Every case with the decision it got, the reason code it
      asserted, and the memory that produced it: 69 hand-written specification
      cases written before the engine existed, 15 learning cases, and 1,842
      derived cases filterable by family, script and confusion rule.
      <span class="muted">Set the filter to <b>failing only</b>. There are three,
      and they are all the same shape.</span></p>
    <div class="row">
      <button id="ex-load">open the case explorer here</button>
      <a class="chip" href="/explorer" target="_blank" rel="noopener">new tab</a>
      <span class="flash" id="ex-flash"></span>
    </div>
    <iframe id="ex-frame" title="the case explorer" hidden></iframe>
  </section>
</div>

</main>

<script>
const $ = id => document.getElementById(id);
const esc = s => (s==null?'':String(s)).replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

/* Highlight the changed region. Boundaries are pushed off combining marks so a
   Devanagari matra is never highlighted alone: the same problem, and the same
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
   with what actually went wrong. An earlier version said "API unreachable" for
   a server that was running fine and answering with a perfectly clear error,
   which described this client's confusion rather than the server's problem. */
function banner(title, detail){
  const el = $('banner');
  el.hidden = false;
  el.innerHTML = '<b>' + esc(title) + '</b><code>' + esc(detail) + '</code>';
  return new Error(detail || title);
}
function clearBanner(){ $('banner').hidden = true; }

async function api(path, opts){
  let r;
  try{
    r = await fetch(path, opts);
  }catch(err){
    throw banner('The server is not answering.',
      ((opts && opts.method) || 'GET') + ' ' + path + ' - ' + err.message
      + '. It may have stopped; restart it with `make serve`.');
  }
  const raw = await r.text();
  let body = null;
  try{ body = raw ? JSON.parse(raw) : null; }catch(e){ /* handled below */ }
  if(!r.ok){
    const detail = body && body.detail != null
      ? (typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail))
      : (raw.slice(0, 400) || 'no body');
    throw banner(((opts && opts.method) || 'GET') + ' ' + path
      + ' failed with HTTP ' + r.status + '.', detail);
  }
  if(body === null){
    throw banner(path + ' answered with something that is not JSON.', raw.slice(0, 400));
  }
  clearBanner();
  return body;
}
const post = (path, body) => api(path, {method:'POST',
  headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});

function say(id, msg, bad){
  const el = $(id);
  el.textContent = msg || '';
  el.className = 'flash' + (bad ? ' err' : '');
}

/* ========================= tabs ========================= */

const TABS = ['dictate','dictionary','memory','evaluation'];
function show(name){
  TABS.forEach(t => { $('t-' + t).hidden = (t !== name); });
  document.querySelectorAll('nav button').forEach(b => {
    if(b.dataset.tab === name) b.setAttribute('aria-current','page');
    else b.removeAttribute('aria-current');
  });
  if(name === 'dictionary') loadDictionary();
  if(name === 'memory') loadMemory();
  window.scrollTo({top:0, behavior:'smooth'});
}
document.querySelectorAll('nav button').forEach(b => {
  b.onclick = () => show(b.dataset.tab);
});

/* ========================= dictate ========================= */

/* The last answer, kept so that a correction knows what it is correcting and
   so that "run it again" can replay the same input after memory has moved. */
let last = null;

async function runDictation(){
  const formatted = $('fmt').value;
  if(!formatted.trim()){ say('flash','Type something, or pick one of the examples.', true); return; }
  const rawAsr = $('asr').value.trim();
  say('flash','');

  let d;
  try{
    d = await post('/dictate', {
      /* The recogniser line is optional. When it is blank the text above is
         both what we were given and what we pass on, and `formatted_text: null`
         asks the server to run the configured formatter over it. */
      asr_text: rawAsr || formatted,
      formatted_text: rawAsr ? formatted : null,
      app: $('app').value || null,
      surrounding_text: $('screen').value || null,
    });
  }catch(err){ say('flash', err.message, true); return; }

  last = d;
  renderResult(d);
  renderWhy(d);
  loadMemory().catch(() => {});
}

function renderResult(d){
  const acted = d.output_text !== d.formatted_text;
  const proposed = d.resolutions.filter(r => r.verdict === 'propose');
  $('result').hidden = false;
  $('result').className = 'card result' + (acted ? ' acted' : '');

  const badge = $('r-badge');
  badge.className = 'verdict ' + (acted ? 'apply' : (proposed.length ? 'propose' : 'abstain'));
  badge.textContent = acted ? 'changed' : (proposed.length ? 'proposed' : 'left alone');

  $('r-meta').textContent =
    d.cost.llm_calls + ' model call' + (d.cost.llm_calls === 1 ? '' : 's')
    + '  ·  ' + d.cost.latency_ms.toFixed(2) + ' ms'
    + '  ·  gate ' + (d.gate_passed ? 'opened' : 'stayed shut');

  $('r-out').innerHTML = diff(d.formatted_text, d.output_text);
  $('r-was').hidden = !acted;
  if(acted) $('r-was').innerHTML = 'was: <s>' + esc(d.formatted_text) + '</s>';

  /* A proposal is a verdict, not a near miss, and leaving it invisible would
     collapse a three-valued decision into "changed or not". One correction
     earns a proposal; confirming it is what makes the term act on its own. */
  $('r-proposed').innerHTML = proposed.length ? '<div class="learned">'
    + '<b>Memory has something to say here, and is not confident enough to do it.</b>'
    + proposed.map(r => '<div class="row" style="margin-top:8px">'
        + '<span class="pair mono"><s>' + esc(r.span.text) + '</s>'
        + '<span class="arrow">&rarr;</span>' + esc(r.replacement || r.canonical) + '</span>'
        + '<button class="tiny" data-accept="' + esc(r.span.text) + '" data-to="'
        + esc(r.replacement || r.canonical) + '">yes, write that</button>'
        + '<span class="pill">' + esc(r.reason) + '</span></div>').join('')
    + '</div>' : '';

  $('fix').value = d.output_text;
  $('learned').innerHTML = '';
  say('fixflash','');
  /* Undoing is only meaningful when something was actually done. */
  $('b-undo').hidden = !acted;
}

function renderWhy(d){
  $('whycard').hidden = false;
  if(!d.resolutions.length){
    $('why').innerHTML = '<p class="small muted">Nothing in memory resembled this '
      + 'text, so the gate closed before retrieval and the call cost nothing. '
      + 'This is the majority of real dictation, and it is the reason the system '
      + 'is cheap enough to sit in the path of every utterance.</p>';
    return;
  }
  let html = '<p class="small muted">' + esc(d.summary) + '</p>';
  for(const r of d.resolutions){
    const rows = r.policies.filter(p => p.signal !== 'neutral' || p.rationale).map(p =>
      '<tr><td class="mono">' + esc(p.policy) + '</td>'
      + '<td><span class="sig ' + esc(p.signal) + '">' + esc(p.signal) + '</span></td>'
      + '<td class="num">' + (p.signal === 'veto' ? 'stop'
          : (p.weight >= 0 ? '+' : '') + p.weight.toFixed(2)) + '</td>'
      + '<td class="small">' + esc(p.rationale) + '</td></tr>').join('');
    html += '<div class="res ' + esc(r.verdict) + '">'
      + '<div><span class="verdict ' + esc(r.verdict) + '">' + esc(r.verdict) + '</span> '
      + '<span class="mono">' + esc(r.span.text) + '</span> '
      + '<span class="arrow">&rarr;</span> '
      + (r.replacement ? '<span class="mono">' + esc(r.replacement) + '</span>'
                       : '<span class="muted">unchanged</span>')
      + ' <span class="pill">' + esc(r.reason) + '</span></div>'
      + '<div class="small muted">matched ' + esc(r.canonical) + ' via '
      + esc(r.matched_via) + ', retrieval ' + r.retrieval_score.toFixed(2)
      + ', combined score ' + r.score.toFixed(2) + '</div>'
      + (rows ? '<table><tr><th>policy</th><th>signal</th><th>weight</th><th>reasoning</th></tr>'
                + rows + '</table>' : '')
      + '</div>';
  }
  html += '<details><summary>raw API response</summary><pre>'
       + esc(JSON.stringify(d, null, 2)) + '</pre></details>';
  $('why').innerHTML = html;
}

/* ---- correcting the whole text ----
   The point of this box is that the sentence is not what gets learned. The
   server diffs the two versions and scores only the span that moved, then
   answers with the span it took, so the claim is visible rather than asserted. */
async function saveCorrection(){
  if(!last){ return; }
  const before = last.output_text;
  const after = $('fix').value;
  if(before === after){ say('fixflash','Nothing changed in that box yet.', true); return; }
  say('fixflash','');

  let d;
  try{
    d = await post('/observations', {
      before: before, after: after, source: 'post_edit',
      app: $('app').value || null,
      /* The two texts are whole versions of a passage, not two forms of a
         term. Saying so is what makes the server record the words that moved
         rather than the sentence around them. */
      extent: 'utterance',
    });
  }catch(err){ say('fixflash', err.message, true); return; }

  renderLearned(d, 'learned');
  if(d.observation.accepted !== false){
    /* Run the same input again so the effect is visible in one motion: this is
       the whole product claim, and describing it is weaker than showing it. */
    const learned = d;
    await runDictation();
    renderLearned(learned, 'learned');
    const acted = last && last.output_text !== last.formatted_text;
    const proposed = last && last.resolutions.some(r => r.verdict === 'propose');
    say('fixflash', acted
      ? 'saved. The same text, run again, now comes out right.'
      : (proposed
         ? 'saved. One inferred correction earns a proposal, not a rule. Confirm it and it acts on its own.'
         : 'saved.'));
  }
  loadDictionary().catch(() => {});
}

async function undoChange(){
  if(!last) return;
  const applied = last.resolutions.filter(r => r.verdict === 'apply' && r.replacement);
  if(!applied.length){ return; }
  say('fixflash','');
  try{
    /* A revert is negative evidence about a specific term: what we wrote, and
       what the user put back in its place. Two of them in one app create a
       suppression guard rather than deleting the term, because the term is
       still real; it is this context the user does not want it in. */
    for(const r of applied){
      await post('/observations', {
        before: r.replacement, after: r.span.text, source: 'revert',
        app: $('app').value || null,
      });
    }
  }catch(err){ say('fixflash', err.message, true); return; }
  await runDictation();
  say('fixflash','recorded as a revert. Two in one app and the term is suppressed there.');
  loadDictionary().catch(() => {});
}

function renderLearned(d, target){
  const o = d.observation;
  let html = '<div class="learned">';
  if(o.accepted === false){
    html += '<b>Nothing was learned from that, and that is a decision.</b>'
      + '<div class="small" style="margin-top:6px">' + esc(o.note || '')
      + '</div><div class="small muted" style="margin-top:6px">The observation is '
      + 'still on the log. An edit that rewrites rather than respells is not '
      + 'evidence about a spelling, and treating it as one is how a memory fills '
      + 'with noise inside a day.</div>';
  }else if(d.learned_from && d.learned_from.length){
    html += '<b>Kept only this:</b>';
    for(const seg of d.learned_from){
      html += '<div class="pair" style="margin-top:6px"><s>' + esc(seg.before) + '</s>'
        + '<span class="arrow">&rarr;</span>' + esc(seg.after) + '</div>';
    }
    if(o.phonetic_distance != null){
      html += '<div class="small muted" style="margin-top:6px">phonetic distance '
        + o.phonetic_distance.toFixed(2) + ', which is close enough to be a '
        + 'respelling rather than a different word.</div>';
    }
  }else{
    html += '<b>Recorded as ' + esc(o.source) + '.</b>';
  }
  if(d.memory_changes && d.memory_changes.length){
    html += '<table><tr><th>term</th><th>what moved</th></tr>'
      + d.memory_changes.map(c => '<tr><td>' + esc(c.canonical) + '</td>'
        + '<td class="small">' + esc(c.change) + '</td></tr>').join('')
      + '</table>';
  }else if(o.accepted !== false){
    html += '<div class="small muted" style="margin-top:6px">No term moved.</div>';
  }
  $(target).innerHTML = html + '</div>';
}

/* ========================= prepared examples ========================= */

const EXAMPLES = [
  {t:'a homophone only memory can settle', asr:'ask adith narayanan to review the pull request',
   fmt:'Ask Adith Narayanan to review the pull request.', app:'com.tinyspeck.slackmacgap',
   note:'a colleague who spells it their own way'},
  {t:'a product heard as a common word', asr:'the sarvam kiwi service is dropping requests',
   fmt:'The Sarvam Kiwi service is dropping requests.', app:'com.tinyspeck.slackmacgap',
   note:'context says product, so it acts'},
  {t:'the same word, ordinary sense - must NOT change', asr:'i ate a kiwi for breakfast',
   fmt:'I ate a kiwi for breakfast.', app:'com.microsoft.Outlook',
   note:'the fruit. A replace table corrupts this'},
  {t:'a Slack handle, in Slack', asr:'i posted the trace in hash eng asr',
   fmt:'I posted the trace in hash eng asr.', app:'com.tinyspeck.slackmacgap',
   note:'a channel, where the channel exists'},
  {t:'the same handle, in Mail - must NOT change', asr:'i posted the trace in hash eng asr',
   fmt:'I posted the trace in hash eng asr.', app:'com.microsoft.Outlook',
   note:'a channel name in an email is not a spelling to fix'},
  {t:'a mishearing never seen before', asr:'ask aadhith narayanan to review the change',
   fmt:'Ask Aadhith Narayanan to review the change.', app:'com.tinyspeck.slackmacgap',
   note:'no variant table has this form. Phonetics finds it'},
  {t:'Devanagari in, Devanagari out', asr:'मिरा शर्मा को भेज दो',
   fmt:'मिरा शर्मा को भेज दो।', app:'com.tinyspeck.slackmacgap',
   note:'spelling is corrected, the alphabet is never swapped'},
  {t:'nothing known here - the gate stays shut, 0 cost',
   asr:'i went through the whole document last night and the only thing i would change is the ordering of the last two sections',
   fmt:'I went through the whole document last night, and the only thing I would change is the ordering of the last two sections.',
   app:'com.microsoft.Outlook',
   note:'ordinary prose. About 71% of real traffic exits here'},
];

$('ex').innerHTML = EXAMPLES.map((e,i) =>
  '<button data-ex="' + i + '"><b>' + esc(e.t) + '</b><span>' + esc(e.note) + '</span></button>'
).join('');
$('ex').addEventListener('click', ev => {
  const btn = ev.target.closest('button[data-ex]');
  if(!btn) return;
  const e = EXAMPLES[+btn.dataset.ex];
  $('app').value = e.app; $('asr').value = e.asr; $('fmt').value = e.fmt;
  $('screen').value = '';
  runDictation();
});

/* Accepting a proposal is the user speaking directly about the term, so it is
   `declared` rather than another inferred edit: the same thing as typing it
   into the dictionary, reached from where the question was asked. */
$('r-proposed').addEventListener('click', async ev => {
  const btn = ev.target.closest('button[data-accept]');
  if(!btn) return;
  say('fixflash','');
  try{
    await post('/observations', {before: btn.dataset.accept, after: btn.dataset.to,
      source: 'declared', app: $('app').value || null});
  }catch(err){ say('fixflash', err.message, true); return; }
  await runDictation();
  say('fixflash','confirmed, so it acts on its own from here');
  loadDictionary().catch(() => {});
});

$('b-run').onclick = runDictation;
$('b-fix').onclick = saveCorrection;
$('b-undo').onclick = undoChange;
['fmt','asr','fix'].forEach(id => $(id).addEventListener('keydown', ev => {
  if(ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)){
    ev.preventDefault();
    if(id === 'fix') saveCorrection(); else runDictation();
  }
}));

/* ========================= dictionary ========================= */

/* No "kind of evidence" selector. The two things a person actually does are
   distinct enough to be two actions, and each maps to exactly one source:
   giving a spelling is `declared`, and saying a rule is `instruction`, whose
   term is read from the sentence. Asking the user to classify their own
   keystroke was an implementation detail wearing a label. */

async function teachTerm(){
  const write = $('d-write').value.trim();
  const heard = $('d-heard').value.trim();
  if(!write){ say('dflash','Type the spelling you want to see.', true); return; }
  say('dflash','');
  try{
    const d = await post('/observations',
      {after: write, before: heard || null, source: 'declared', app: null});
    renderLearned(d, 'dchanges');
    say('dflash','added, and usable straight away');
    $('d-write').value = ''; $('d-heard').value = '';
    loadDictionary(); loadMemory().catch(() => {});
  }catch(err){ say('dflash', err.message, true); }
}

async function teachRule(){
  const rule = $('d-rule').value.trim();
  if(!rule){ say('rflash','Say the rule the way you would say it to a person.', true); return; }
  say('rflash','');
  try{
    const d = await post('/observations',
      {after: rule, source: 'instruction', app: $('app').value || null});
    renderLearned(d, 'dchanges');
    say('rflash', d.observation.attributed_to
      ? 'kept in your words, against the term it names'
      : 'recorded, but no term could be read out of that sentence');
    $('d-rule').value = '';
    loadDictionary(); loadMemory().catch(() => {});
  }catch(err){ say('rflash', err.message, true); }
}
$('b-teach').onclick = teachTerm;
$('b-rule').onclick = teachRule;
$('d-rule').addEventListener('keydown', ev => { if(ev.key === 'Enter') teachRule(); });
$('d-write').addEventListener('keydown', ev => { if(ev.key === 'Enter') teachTerm(); });

async function loadDictionary(){
  const p = new URLSearchParams();
  if($('dq').value) p.set('q', $('dq').value);
  const d = await api('/memory?' + p);
  $('dict').innerHTML = d.lexemes.map(l => {
    const forms = l.variants.map(v =>
      '<span class="pill' + (v.provenance === 'observed' ? ' ok' : '') + '">'
      + esc(v.form) + '</span>').join('') || '<span class="muted small">no heard-as forms yet</span>';
    return '<div class="entry">'
      + '<div class="term">' + esc(l.canonical) + '<small>' + esc(l.kind) + '</small></div>'
      + '<div class="forms">' + forms + '</div>'
      + '<span class="state ' + esc(l.state) + '">' + esc(l.state) + '</span>'
      + (l.instruction ? '<div class="instr">rule: ' + esc(l.instruction) + '</div>' : '')
      + '</div>';
  }).join('') || '<p class="small muted">Nothing matches that.</p>';
}
$('dq').oninput = () => loadDictionary().catch(() => {});

/* ========================= memory ========================= */

async function loadMemory(){
  const p = new URLSearchParams();
  if($('mq').value) p.set('q', $('mq').value);
  if($('mstate').value) p.set('state', $('mstate').value);
  const d = await api('/memory?' + p);
  $('c-mem').textContent = d.count + ' terms';
  $('memory').innerHTML = '<table>'
    + '<tr><th>term</th><th>state</th><th>conf</th><th>strength</th>'
    + '<th>heard as</th><th>guards</th><th>standing rule</th></tr>'
    + d.lexemes.map(l => '<tr>'
      + '<td>' + esc(l.canonical) + '<div class="small muted">' + esc(l.kind) + '</div></td>'
      + '<td><span class="state ' + esc(l.state) + '">' + esc(l.state) + '</span></td>'
      + '<td class="num">' + l.confidence.toFixed(2) + '</td>'
      + '<td class="num">' + l.strength.toFixed(2) + '</td>'
      + '<td class="small">' + (l.variants.map(v => '<span class="pill">' + esc(v.form)
          + ' · ' + esc(v.provenance) + (v.count ? ' · ' + v.count + 'x' : '')
          + '</span>').join('') || '<span class="muted">-</span>') + '</td>'
      + '<td class="small">' + (l.guards.map(g => '<span class="pill">' + esc(g.kind)
          + '</span>').join('') || '<span class="muted">-</span>') + '</td>'
      + '<td class="small">' + (l.instruction ? esc(l.instruction)
          : '<span class="muted">-</span>') + '</td>'
      + '</tr>').join('')
    + '</table><p class="small muted">' + d.count + ' term' + (d.count === 1 ? '' : 's') + '</p>';
}
$('mq').oninput = () => loadMemory().catch(() => {});
$('mstate').onchange = () => loadMemory().catch(() => {});
$('b-refresh').onclick = () => loadMemory().catch(() => {});

async function reset(){
  await post('/reset', {});
  say('mflash','back to the seeded persona');
  setTimeout(() => say('mflash',''), 2500);
  last = null;
  $('result').hidden = true; $('whycard').hidden = true;
  $('learned').innerHTML = ''; $('dchanges').innerHTML = '';
  say('flash',''); say('fixflash',''); say('dflash',''); say('rflash','');
  loadMemory().catch(() => {});
  loadDictionary().catch(() => {});
}
$('b-reset').onclick = reset;

/* ========================= the case explorer ========================= */

$('ex-load').onclick = () => {
  const frame = $('ex-frame'), btn = $('ex-load');
  if(!frame.hidden){
    frame.hidden = true; btn.textContent = 'open the case explorer here';
    say('ex-flash',''); return;
  }
  btn.textContent = 'hide the case explorer';
  frame.hidden = false;
  if(!frame.src){
    say('ex-flash','loading. If it has never been built, the server builds it now, '
      + 'which takes a second or two');
    frame.onload = () => say('ex-flash','');
    frame.src = '/explorer';
  }
};

/* ========================= boot ========================= */

api('/health').then(h => {
  $('c-llm').textContent = h.components.policies.length + ' policies · ' + h.components.llm;
  $('c-llm').className = 'chip on';
}).catch(() => { $('c-llm').textContent = 'API unreachable'; });

loadMemory().catch(() => { $('c-mem').textContent = 'memory unreadable'; });
</script>
</body>
</html>
"""
