/* MedAgent Evidence Desk — vanilla JS, no build step. */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const DESIGNS = [
    ["guideline", "Guideline", 1], ["meta_analysis", "Meta-analysis", 1], ["systematic_review", "Systematic review", 1],
    ["rct", "RCT", 2], ["clinical_trial", "Non-randomised trial", 3], ["cohort", "Cohort / observational", 3],
    ["case_control", "Case-control", 4], ["cross_sectional", "Cross-sectional", 4], ["case_report", "Case report", 4],
    ["narrative_review", "Narrative review", 5], ["opinion", "Editorial / opinion", 5], ["preprint", "Preprint", 5], ["other", "Other", 5],
  ];
  const DESIGN = Object.fromEntries(DESIGNS.map(([k, label, lvl]) => [k, { label, lvl }]));
  const LOE_COLOR = (l) => `var(--loe${l})`;

  const EXAMPLES = {
    evidence: ["SGLT2 inhibitors heart failure preserved ejection fraction", "tranexamic acid postpartum haemorrhage", "semaglutide chronic kidney disease", "early goal-directed therapy sepsis"],
    ask: ["What is first-line therapy for newly diagnosed atrial fibrillation in a 70-year-old with CKD stage 3?", "Does colchicine reduce cardiovascular events after MI?", "What's new this year in the management of Clostridioides difficile infection?"],
    new: ["GLP-1 receptor agonists", "long COVID", "Alzheimer's disease anti-amyloid", "CAR-T lymphoma"],
    trials: ["glioblastoma", "type 1 diabetes teplizumab", "MASH resmetirom", "pancreatic cancer"],
    drug: ["apixaban", "tirzepatide", "amiodarone", "valproate"],
    calc: [],
    library: [],
    settings: [],
  };

  const state = {
    mode: "evidence",
    bundle: null,
    list: [],          // items currently rendered in the result list
    sel: -1,
    designOn: new Set(),
    sort: "score",
    newIds: new Set(),
    library: [],
    watch: [],
    conv: null,
    askSources: new Map(),
    health: null,
  };

  // ---------------------------------------------------------------- utilities
  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
      body: opts.body && typeof opts.body !== "string" ? JSON.stringify(opts.body) : opts.body,
    });
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try { detail = (await res.json()).detail || detail; } catch (_) { /* not json */ }
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    const type = res.headers.get("content-type") || "";
    return type.includes("json") ? res.json() : res.text();
  }

  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => (t.hidden = true), 2200);
  }

  async function copy(text) {
    try { await navigator.clipboard.writeText(text); toast("Copied"); }
    catch (_) { toast("Copy blocked by the browser; select the text instead"); }
  }

  function download(name, text, type = "text/plain") {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type }));
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  const fmtN = (n) => (n == null ? "—" : Number(n).toLocaleString());
  const shortAuthors = (a) => (!a?.length ? "" : a.length > 3 ? `${a[0]}, ${a[1]}, ${a[2]} et al.` : a.join(", "));
  const storeGet = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch (_) { return d; } };
  const storeSet = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (_) { /* private mode */ } };

  // ------------------------------------------------------ user model settings
  // Shape: { active: "server"|"anthropic"|"openai", anthropic: {base_url, api_key, model}, openai: {...} }
  const LLM_KEY = "medagent.llm";
  const LLM_DEFAULT_MODEL = { anthropic: "claude-sonnet-5", openai: "gpt-5" };
  const loadLLM = () => {
    const v = storeGet(LLM_KEY, {});
    return { active: v.active || "server", anthropic: v.anthropic || {}, openai: v.openai || {} };
  };
  function llmConfig(provider, cfg) {
    if (!cfg?.api_key) return null;
    return { provider, api_key: cfg.api_key, base_url: cfg.base_url || null, model: cfg.model || LLM_DEFAULT_MODEL[provider] };
  }
  // The endpoint Ask should use, or null for the server's own .env configuration.
  function activeLLM() {
    const s = loadLLM();
    return s.active === "server" ? null : llmConfig(s.active, s[s.active]);
  }

  function vancouver(a) {
    const parts = [];
    const au = a.authors?.length > 6 ? a.authors.slice(0, 3).join(", ") + ", et al" : (a.authors || []).join(", ");
    if (au) parts.push(au + ".");
    parts.push(a.title.replace(/\.$/, "") + ".");
    if (a.journal) parts.push(a.journal + ".");
    if (a.year) parts.push(a.year + ".");
    if (a.doi) parts.push(`doi:${a.doi}.`);
    if (a.pmid) parts.push(`PMID: ${a.pmid}.`);
    return parts.join(" ");
  }

  // ------------------------------------------------------------- badges/cards
  function loeBadge(a) {
    const d = DESIGN[a.design] || DESIGN.other;
    if (a.is_retracted) return `<span class="badge bad">RETRACTED</span>`;
    return `<span class="badge l${a.evidence_level}" title="Level of evidence ${a.evidence_level} (1 strongest)">LoE ${a.evidence_level} · ${esc(d.label)}</span>`;
  }

  function flags(a) {
    let h = "";
    if (a.is_preprint) h += `<span class="badge pre" title="Not peer reviewed">Preprint</span>`;
    if (a.open_access) h += `<span class="badge oa">Free full text</span>`;
    return h;
  }

  function articleCard(a, i) {
    const bits = [a.journal && esc(a.journal), a.year, a.sample_size && `n≈${fmtN(a.sample_size)}`, a.cited_by != null && `${fmtN(a.cited_by)} citations`].filter(Boolean);
    const isNew = state.newIds.has(a.id);
    return `<article class="card${a.is_retracted ? " retracted" : ""}${isNew ? " new" : ""}" data-i="${i}" tabindex="0">
      <div class="row">${loeBadge(a)}${flags(a)}</div>
      <h4>${esc(a.title)}</h4>
      <div class="row num">${bits.map((b, j) => `<span${j ? ' class="sep"' : ""}>${b}</span>`).join("")}</div>
      ${a.bottom_line ? `<p class="bluf"><b>Conclusion</b>${esc(a.bottom_line)}</p>` : ""}
    </article>`;
  }

  function trialCard(t, i) {
    const phase = t.phases.join(" / ") || (t.study_type || "").toLowerCase();
    return `<article class="card" data-i="${i}" tabindex="0">
      <div class="row"><span class="st ${esc(t.status)}">${esc((t.status || "").replaceAll("_", " ").toLowerCase())}</span>
        ${phase ? `<span class="badge plain">${esc(phase)}</span>` : ""}${t.has_results ? `<span class="badge oa">Results posted</span>` : ""}
        <span class="mono">${esc(t.nct_id)}</span></div>
      <h4>${esc(t.title)}</h4>
      <div class="row num"><span>n=${fmtN(t.enrollment)}</span><span class="sep">${esc(t.sponsor || "")}</span>
        <span class="sep">primary completion ${esc(t.primary_completion_date || "—")}</span><span class="sep">${t.locations.length} sites</span></div>
      ${t.interventions.length ? `<p class="bluf"><b>Arms</b>${esc(t.interventions.slice(0, 3).join("; "))}</p>` : ""}
    </article>`;
  }

  function webCard(w, i) {
    return `<article class="card" data-i="${i}" tabindex="0">
      <div class="row">${w.authority ? `<span class="badge l1">${esc(w.authority)}</span>` : `<span class="badge plain">${esc(w.kind)}</span>`}
        <span>${esc(w.site)}</span>${w.date ? `<span class="sep">${esc(w.date)}</span>` : ""}</div>
      <h4>${esc(w.title)}</h4>
      <p class="bluf">${esc(w.snippet)}</p>
    </article>`;
  }

  function cardFor(item, i) {
    if (item._kind === "trial") return trialCard(item, i);
    if (item._kind === "web") return webCard(item, i);
    return articleCard(item, i);
  }

  // ----------------------------------------------------------------- previews
  function fact(label, value) { return `<div><dt>${label}</dt><dd>${value}</dd></div>`; }

  function articlePreview(a) {
    const d = DESIGN[a.design] || DESIGN.other;
    const pmc = a.pmcid ? `https://pmc.ncbi.nlm.nih.gov/articles/${a.pmcid}/` : null;
    const saved = state.library.some((x) => x.id === a.id);
    const sections = a.sections?.length
      ? a.sections.map((s) => `<div class="section"><h5>${esc(s.label)}</h5><p>${esc(s.text)}</p></div>`).join("")
      : a.abstract ? `<div class="section"><h5>Abstract</h5><p>${esc(a.abstract)}</p></div>` : `<p class="muted">No abstract available.</p>`;
    const readUrl = pmc || a.pdf_url || a.url || (a.doi ? `https://doi.org/${a.doi}` : "");
    return `
      <div class="row">${loeBadge(a)}${flags(a)}${a.also_in?.length ? `<span class="badge plain" title="Also returned by">+${esc(a.also_in.join(", "))}</span>` : ""}</div>
      <h2>${esc(a.title)}</h2>
      <div class="meta">${esc(a.journal || "")}${a.pub_date ? ` · ${esc(a.pub_date)}` : a.year ? ` · ${a.year}` : ""}</div>
      <div class="authors">${esc(shortAuthors(a.authors))}</div>
      ${a.is_retracted ? `<p class="err">This paper is flagged as retracted. Do not rely on its findings.</p>` : ""}
      <dl class="facts">
        ${fact("Design", esc(d.label))}${fact("Evidence", `Level ${a.evidence_level}`)}
        ${fact("Sample", a.sample_size ? "≈" + fmtN(a.sample_size) : "—")}${fact("Cited by", fmtN(a.cited_by))}
        ${fact("Access", a.open_access ? "Free" : "Paywalled?")}
      </dl>
      ${a.bottom_line ? `<div class="bottomline"><h5>Authors' conclusion</h5>${esc(a.bottom_line)}</div>` : ""}
      <div class="actions">
        ${a.url ? `<a class="main" href="${esc(a.url)}" target="_blank" rel="noopener">${a.pmid ? "PubMed" : "Open"}</a>` : ""}
        ${pmc ? `<a href="${pmc}" target="_blank" rel="noopener">PMC full text</a>` : ""}
        ${a.pdf_url ? `<a href="${esc(a.pdf_url)}" target="_blank" rel="noopener">PDF</a>` : ""}
        ${a.doi ? `<a href="https://doi.org/${esc(a.doi)}" target="_blank" rel="noopener">DOI</a>` : ""}
        ${readUrl && state.health?.tinyfish ? `<button data-act="read" data-url="${esc(readUrl)}">Read here</button>` : ""}
        <button data-act="save">${saved ? "Saved ✓" : "Save"}</button>
        <button data-act="cite">Copy citation</button>
        <button data-act="ask">Ask about this</button>
        ${a.abstract ? `<button data-act="appraise">Extract PICO & effects</button>` : ""}
      </div>
      <div id="appraisal"></div>
      ${sections}
      ${a.mesh_terms?.length ? `<div class="section"><h5>MeSH</h5><div class="tags">${a.mesh_terms.slice(0, 16).map((m) => `<span>${esc(m)}</span>`).join("")}</div></div>` : ""}
      ${a.publication_types?.length ? `<div class="section"><h5>Publication type</h5><div class="tags">${a.publication_types.map((m) => `<span>${esc(m)}</span>`).join("")}</div></div>` : ""}
      <div class="section"><h5>Citation</h5><div class="cite">${esc(vancouver(a))}</div></div>
      <div class="reader" id="reader" hidden></div>`;
  }

  function trialPreview(t) {
    const countries = [...new Set(t.locations.map((l) => l.country).filter(Boolean))];
    return `
      <div class="row"><span class="st ${esc(t.status)}">${esc((t.status || "").replaceAll("_", " ").toLowerCase())}</span>
        <span class="mono">${esc(t.nct_id)}</span>${t.has_results ? `<span class="badge oa">Results posted</span>` : ""}</div>
      <h2>${esc(t.title)}</h2>
      ${t.official_title && t.official_title !== t.title ? `<div class="authors">${esc(t.official_title)}</div>` : ""}
      <dl class="facts">
        ${fact("Phase", esc(t.phases.join(" / ") || t.study_type || "—"))}${fact("Enrolment", fmtN(t.enrollment))}
        ${fact("Start", esc(t.start_date || "—"))}${fact("Primary completion", esc(t.primary_completion_date || "—"))}
        ${fact("Updated", esc(t.last_update || "—"))}
      </dl>
      <div class="actions">
        <a class="main" href="${esc(t.url)}" target="_blank" rel="noopener">ClinicalTrials.gov</a>
        <button data-act="cite-trial">Copy NCT</button>
        <button data-act="ask">Ask about this</button>
      </div>
      <div class="section"><h5>Conditions</h5><div class="tags">${t.conditions.map((c) => `<span>${esc(c)}</span>`).join("")}</div></div>
      <div class="section"><h5>Interventions</h5><p>${esc(t.interventions.join("; ") || "—")}</p></div>
      ${t.primary_outcomes.length ? `<div class="section"><h5>Primary outcome</h5><p>${t.primary_outcomes.map(esc).join("<br>")}</p></div>` : ""}
      ${t.summary ? `<div class="section"><h5>Summary</h5><p>${esc(t.summary)}</p></div>` : ""}
      <div class="section"><h5>Sponsor</h5><p>${esc(t.sponsor || "—")}</p></div>
      ${t.eligibility ? `<details class="lbl"><summary>Eligibility · ${esc(t.sex || "all")} · ${esc(t.min_age || "any")}–${esc(t.max_age || "any")}</summary><div>${esc(t.eligibility)}</div></details>` : ""}
      ${t.locations.length ? `<details class="lbl" open><summary>${t.locations.length} sites in ${countries.length} ${countries.length === 1 ? "country" : "countries"}</summary>
        <div class="sites"><table>${t.locations.slice(0, 200).map((l) => `<tr><td>${esc(l.facility || "")}</td><td>${esc([l.city, l.country].filter(Boolean).join(", "))}</td><td>${esc((l.status || "").toLowerCase().replaceAll("_", " "))}</td></tr>`).join("")}</table></div></details>` : ""}`;
  }

  function webPreview(w) {
    return `
      <div class="row">${w.authority ? `<span class="badge l1">${esc(w.authority)}</span>` : ""}<span>${esc(w.site)}</span>${w.date ? `<span class="sep">${esc(w.date)}</span>` : ""}</div>
      <h2>${esc(w.title)}</h2>
      <div class="bottomline"><h5>Snippet</h5>${esc(w.snippet)}</div>
      <div class="actions">
        <a class="main" href="${esc(w.url)}" target="_blank" rel="noopener">Open page</a>
        ${state.health?.tinyfish ? `<button data-act="read" data-url="${esc(w.url)}">Read here</button>` : ""}
        <button data-act="ask">Ask about this</button>
      </div>
      <div class="reader" id="reader" hidden></div>`;
  }

  function showPreview(item) {
    const p = $("#preview");
    if (!item) { p.innerHTML = previewIntro(); return; }
    p.innerHTML = item._kind === "trial" ? trialPreview(item) : item._kind === "web" ? webPreview(item) : articlePreview(item);
    p.scrollTop = 0;
    p.onclick = (e) => onPreviewAction(e, item);
  }

  async function onPreviewAction(e, item) {
    const btn = e.target.closest("[data-act]");
    if (!btn) return;
    const act = btn.dataset.act;
    if (act === "cite") copy(vancouver(item));
    if (act === "cite-trial") copy(item.nct_id);
    if (act === "save") { await saveToLibrary(item); btn.textContent = "Saved ✓"; }
    if (act === "ask") {
      const ref = item._kind === "trial" ? `trial ${item.nct_id} ("${item.title}")` : item.pmid ? `PMID ${item.pmid} ("${item.title}")` : `"${item.title}" (${item.url || item.doi || ""})`;
      setMode("ask");
      $("#askInput").value = `Appraise ${ref}: key methods, effect sizes, limitations, and how it fits with current guidelines.`;
      $("#askInput").focus();
    }
    if (act === "read") readInline(btn.dataset.url, $("#q").value || item.title);
    if (act === "appraise") appraise(item);
  }

  async function readInline(url, focus) {
    const r = $("#reader");
    r.hidden = false;
    r.innerHTML = `<div class="skeleton"></div>`;
    try {
      const page = await api("/api/read", { method: "POST", body: { url, focus } });
      if (page.error) throw new Error(page.error);
      r.innerHTML = `<h5 class="muted">Fetched with TinyFish · ${esc(page.final_url || page.url)}</h5>
        ${page.highlights?.length ? page.highlights.map((h) => `<div class="hl">${esc(h)}</div>`).join("") : ""}
        <pre>${esc(page.text || "No readable text.")}</pre>`;
    } catch (err) {
      r.innerHTML = `<p class="err">Could not read this page: ${esc(err.message)}</p>`;
    }
  }

  async function appraise(a) {
    const box = $("#appraisal");
    box.innerHTML = `<div class="skeleton" style="height:120px"></div>`;
    try {
      const { pico, effects } = await api("/api/appraise", { method: "POST", body: { text: `${a.title}. ${a.abstract || ""}` } });
      const row = (label, items) => `<dt>${label}</dt><dd>${items?.length ? items.map(esc).join("; ") : '<span class="muted">not found</span>'}</dd>`;
      const eff = effects.effects;
      box.innerHTML = `<div class="section"><h5>PICO · ${esc(pico.backend)}</h5><dl class="pico">
          ${row("P", pico.population)}${row("I", pico.intervention)}${row("C", pico.comparator)}${row("O", pico.outcomes)}
          ${pico.sample_size ? `<dt>n</dt><dd class="num">${fmtN(pico.sample_size)}</dd>` : ""}</dl></div>
        <div class="section"><h5>Effect estimates · deterministic extraction</h5>
        ${eff.length ? `<div style="overflow-x:auto"><table class="effects"><thead><tr><th>Measure</th><th>Estimate</th><th>95% CI</th><th>P</th><th></th></tr></thead><tbody>
          ${eff.map((e) => `<tr><td>${esc(e.measure)}</td><td class="num">${e.value}</td><td class="num">${e.ci_low != null ? `${e.ci_low} to ${e.ci_high}` : "—"}</td><td>${esc(e.p_value || "")}</td>
            <td>${e.significant === true ? '<span class="badge oa">significant</span>' : e.significant === false ? '<span class="badge plain">CI crosses null</span>' : ""}</td></tr>`).join("")}
          </tbody></table></div>` : `<p class="muted">No effect estimates in the abstract.</p>`}
        ${effects.arm_percentages.length ? `<p class="muted">Arm event rates: ${effects.arm_percentages.map(esc).join("; ")}</p>` : ""}
        ${effects.nnt.length ? `<p class="muted">${effects.nnt.map(esc).join("; ")}</p>` : ""}</div>`;
    } catch (err) {
      box.innerHTML = `<p class="err">${esc(err.message)}</p>`;
    }
  }

  // ------------------------------------------------------------- calculators
  const LOW_BANDS = /^(low|normal|pe unlikely|perc negative|class a|not high risk|g1|g2|>=60|<10|underweight|normal)$/i;
  const HIGH_BANDS = /(high|severe|class c|markedly|pe likely|perc positive|g4|g5|<15|≥30|obesity class iii|elevated)/i;

  function fieldSpec(name, prop, required) {
    let p = prop;
    if (prop.anyOf) p = { ...prop, ...(prop.anyOf.find((x) => x.type !== "null") || {}) };
    const label = (p.title || name).replace(/_/g, " ");
    return { name, label, type: p.enum ? "enum" : p.type, enumv: p.enum, min: p.minimum ?? p.exclusiveMinimum, max: p.maximum ?? p.exclusiveMaximum, desc: prop.description || p.description, required, def: prop.default };
  }

  async function renderCalcView(selectName) {
    if (!state.calcs) {
      try { state.calcs = await api("/api/calculators"); } catch (err) { $("#calcForm").innerHTML = `<p class="err">${esc(err.message)}</p>`; return; }
    }
    const cats = [...new Set(state.calcs.map((c) => c.category))];
    const cur = selectName || state.calcSel || state.calcs[0].name;
    state.calcSel = cur;
    $("#calcList").innerHTML = cats.map((cat) => `<h4>${esc(cat)}</h4>` + state.calcs.filter((c) => c.category === cat)
      .map((c) => `<button type="button" data-calc="${c.name}" class="${c.name === cur ? "on" : ""}">${esc(c.title)}</button>`).join("")).join("");
    const c = state.calcs.find((x) => x.name === cur);
    const props = c.schema.properties || {};
    const req = new Set(c.schema.required || []);
    const pre = state.prefill?.[cur]?.inputs || {};
    const fields = Object.entries(props).map(([k, v]) => fieldSpec(k, v, req.has(k)));
    $("#calcForm").innerHTML = `<h2>${esc(c.title)}</h2><p class="muted" style="margin:0">${esc(c.description)}</p>
      <form id="calcInputs"><div class="fields">${fields.map((f) => {
        const val = pre[f.name] ?? f.def;
        const filled = pre[f.name] !== undefined ? " filled" : "";
        const hint = f.desc ? `<small>${esc(f.desc)}</small>` : "";
        if (f.type === "boolean") return `<label class="field bool${filled}"><input type="checkbox" name="${f.name}" ${val ? "checked" : ""}><span>${esc(f.label)}${hint ? "<br>" + hint : ""}</span></label>`;
        if (f.type === "enum") return `<label class="field${filled}"><span>${esc(f.label)}${f.required ? "" : " (optional)"}</span><select name="${f.name}">${f.required ? "" : '<option value="">—</option>'}${f.enumv.map((o) => `<option value="${esc(o)}" ${String(val) === String(o) ? "selected" : ""}>${esc(String(o).replace(/_/g, " "))}</option>`).join("")}</select>${hint}</label>`;
        return `<label class="field${filled}"><span>${esc(f.label)}${f.required ? "" : " (optional)"}</span><input type="number" step="any" name="${f.name}" value="${val ?? ""}" ${f.min != null ? `min="${f.min}"` : ""} ${f.max != null ? `max="${f.max}"` : ""} ${f.required ? "required" : ""}>${hint}</label>`;
      }).join("")}</div><button class="primary" type="submit">Calculate</button></form>
      <div id="calcResult"></div>
      <p class="muted" style="font-size:12px;margin-top:14px">${esc(c.reference)}</p>`;
    $("#calcInputs").onsubmit = async (e) => {
      e.preventDefault();
      const inputs = {};
      fields.forEach((f) => {
        const el = e.target.elements[f.name];
        if (f.type === "boolean") inputs[f.name] = el.checked;
        else if (el.value !== "") inputs[f.name] = f.type === "enum" ? (typeof f.enumv[0] === "number" ? Number(el.value) : el.value) : Number(el.value);
      });
      const out = $("#calcResult");
      try {
        const r = await api(`/api/calculators/${cur}`, { method: "POST", body: { inputs } });
        const cls = HIGH_BANDS.test(r.band || "") ? "b-high" : LOW_BANDS.test(r.band || "") ? "b-low" : "b-mid";
        out.innerHTML = `<div class="result ${cls}"><div><span class="big">${r.value}</span><span class="unit">${esc(r.unit || "")}</span>
          ${r.band ? `<span class="badge plain" style="margin-left:8px">${esc(r.band)}</span>` : ""}</div>
          <p style="margin:8px 0 0">${esc(r.interpretation)}</p>
          ${Object.keys(r.details || {}).length ? `<p class="muted" style="margin:6px 0 0">${Object.entries(r.details).map(([k, v]) => `${esc(k.replace(/_/g, " "))}: ${esc(v)}`).join(" · ")}</p>` : ""}
          ${r.caveats.length ? `<ul>${r.caveats.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
          <div class="actions"><button type="button" id="copyCalc">Copy result</button></div></div>`;
        $("#copyCalc").onclick = () => copy(`${r.title}: ${r.value}${r.unit ? " " + r.unit : ""}${r.band ? " (" + r.band + ")" : ""}. ${r.interpretation} Inputs: ${JSON.stringify(r.inputs)}`);
      } catch (err) {
        out.innerHTML = `<p class="err">${esc(err.message)}</p>`;
      }
    };
  }

  async function analyzeCase() {
    const text = $("#caseText").value.trim();
    if (text.length < 3) return;
    const out = $("#caseOut");
    out.innerHTML = `<div class="skeleton"></div>`;
    try {
      const { findings: f, prefill } = await api("/api/analyze", { method: "POST", body: { text } });
      state.prefill = prefill;
      const ents = f.entities.map((e) => `<span class="ent ${e.label}${e.negated ? " neg" : ""}" title="${e.label.toLowerCase()}${e.negated ? ", negated" : ""}">${esc(e.expansion || e.text)}</span>`).join("");
      const labs = f.measurements.map((m) => `${esc(m.name.replace(/_/g, " "))} <b class="num">${m.value}</b>`).join(" · ");
      const calcBtns = Object.entries(prefill).sort((a, b) => a[1].missing.length - b[1].missing.length)
        .filter(([, v]) => v.missing.length <= 3)
        .map(([k, v]) => `<button type="button" class="readycalc${v.missing.length ? "" : " ok"}" data-calc="${k}" title="${v.missing.length ? "Missing: " + esc(v.missing.join(", ")) : "All required inputs found"}">${esc(state.calcs?.find((c) => c.name === k)?.title || k)}</button>`).join("");
      out.innerHTML = `<div class="muted">Model: ${esc(f.backend)}${f.age ? ` · ${f.age} y` : ""}${f.sex ? ` · ${esc(f.sex)}` : ""}</div>
        ${ents ? `<div>${ents}</div><div class="muted" style="font-size:11.5px">Struck-through entities are negated (pertinent negatives).</div>` : ""}
        ${labs ? `<div>${labs}</div>` : ""}
        ${calcBtns ? `<div><div class="muted" style="margin-bottom:4px">Calculators with inputs found (green = ready):</div>${calcBtns}</div>` : ""}`;
      renderCalcView(state.calcSel);
    } catch (err) {
      out.innerHTML = `<p class="err">${esc(err.message)}</p>`;
    }
  }

  function previewIntro() {
    const b = state.bundle;
    if (!b) {
      return `<div class="empty"><h2>Find the evidence, fast</h2>
        <p>One search queries PubMed, Europe PMC (with medRxiv and bioRxiv preprints), OpenAlex, ClinicalTrials.gov and guideline bodies at once. Results are merged, de-duplicated and ranked by level of evidence, recency and citations.</p>
        <ul>
          <li>Each card leads with the authors' conclusion, study design and sample size.</li>
          <li>Filter by level of evidence on the left; pick a result to see its structured abstract here.</li>
          <li><b>Ask</b> runs the research agent: it searches, reads and writes a cited summary.</li>
          <li><b>What's new</b> shows papers indexed in the last days or weeks. Watch a topic to get a digest.</li>
        </ul></div>`;
    }
    return `<div class="empty"><p>Select a result to preview it.</p></div>`;
  }

  // --------------------------------------------------------------- list view
  function sortedArticles(arts) {
    const a = [...arts];
    if (state.sort === "newest") a.sort((x, y) => String(y.pub_date || y.year || "").localeCompare(String(x.pub_date || x.year || "")));
    if (state.sort === "cited") a.sort((x, y) => (y.cited_by || 0) - (x.cited_by || 0));
    if (state.sort === "level") a.sort((x, y) => x.evidence_level - y.evidence_level || y.score - x.score);
    return a;
  }

  function renderFacets() {
    const counts = {};
    (state.bundle?.articles || []).forEach((a) => (counts[a.design] = (counts[a.design] || 0) + 1));
    $("#designFilters").innerHTML = DESIGNS.filter(([k]) => counts[k]).map(([k, label, lvl]) => `
      <label><input type="checkbox" value="${k}" ${state.designOn.has(k) ? "checked" : ""}>
        <span><span class="badge l${lvl}" style="padding:0 5px">${lvl}</span> ${esc(label)}</span><span class="n">${counts[k]}</span></label>`).join("")
      || `<span class="muted">Run a search to see the evidence mix.</span>`;
  }

  function renderProviders() {
    const b = state.bundle;
    $("#providers").innerHTML = b?.providers?.length
      ? `<h3>Sources this search</h3>` + b.providers.map((p) => `<div class="${p.ok ? "" : "bad"}">${p.ok ? "✓" : "✕"} ${esc(p.provider)} ${p.ok ? `· ${p.count} · ${p.ms} ms` : `· ${esc(p.error || "")}`}</div>`).join("")
      : "";
  }

  function evidenceMix(arts) {
    if (!arts.length) return "";
    const byL = [1, 2, 3, 4, 5].map((l) => arts.filter((a) => a.evidence_level === l).length);
    return `<div class="evmix" title="Evidence mix: ${byL.map((n, i) => `LoE${i + 1} ${n}`).join(", ")}">${byL.map((n, i) => n ? `<span style="width:${(n / arts.length) * 100}%;background:${LOE_COLOR(i + 1)}"></span>` : "").join("")}</div>`;
  }

  function renderResults() {
    const b = state.bundle;
    const box = $("#results");
    if (!b) { box.innerHTML = ""; return; }
    let arts = b.articles.map((a) => ({ ...a, _kind: "article" }));
    if (state.designOn.size) arts = arts.filter((a) => state.designOn.has(a.design));
    arts = sortedArticles(arts);
    const web = (b.web || []).map((w) => ({ ...w, _kind: "web" }));
    const trials = (b.trials || []).map((t) => ({ ...t, _kind: "trial" }));
    const mode = state.mode;
    const list = mode === "trials" ? trials : [...web.slice(0, mode === "new" ? 6 : 4), ...arts, ...trials.slice(0, mode === "new" ? 6 : 5)];
    state.list = list;

    const l1 = b.articles.filter((a) => a.evidence_level === 1).length;
    const rct = b.articles.filter((a) => a.design === "rct").length;
    const newCount = state.newIds.size;
    const head = mode === "trials"
      ? `<div class="summary-bar"><strong>${trials.length} trials</strong><span>for “${esc(b.query)}”</span></div>`
      : `<div class="summary-bar"><strong>${arts.length} papers</strong>
          <span>${l1} guideline/SR/MA · ${rct} RCT${rct === 1 ? "" : "s"} · ${web.length} guideline page${web.length === 1 ? "" : "s"} · ${trials.length} trial${trials.length === 1 ? "" : "s"}</span>
          ${newCount ? `<span class="badge l2">${newCount} new since last check</span>` : ""}
          <span class="spacer"></span>
          <label class="muted" for="sortSel">Sort</label>
          <select id="sortSel">
            ${[["score", "Best evidence"], ["level", "Evidence level"], ["newest", "Newest"], ["cited", "Most cited"]].map(([v, l]) => `<option value="${v}" ${state.sort === v ? "selected" : ""}>${l}</option>`).join("")}
          </select>
        </div>${evidenceMix(arts)}`;

    const section = (title, items, offset) => items.length ? `<h3 class="muted" style="margin:8px 0 0;font-size:11px;letter-spacing:.08em;text-transform:uppercase">${title}</h3>` + items.map((it, j) => cardFor(it, offset + j)).join("") : "";
    let body;
    if (mode === "trials") body = list.map(cardFor).join("");
    else {
      const w = list.filter((x) => x._kind === "web"), a = list.filter((x) => x._kind === "article"), t = list.filter((x) => x._kind === "trial");
      body = section(mode === "new" ? "In the news" : "Guidelines & authoritative pages", w, 0)
        + section(mode === "new" ? "Newest papers & preprints" : "Research", a, w.length)
        + section(mode === "new" ? "Recently updated trials" : "Registered trials", t, w.length + a.length);
    }
    box.innerHTML = head + (list.length ? body : `<p class="empty">Nothing matched. Try broader terms or clear filters.</p>`);
    $("#sortSel")?.addEventListener("change", (e) => { state.sort = e.target.value; renderResults(); });
    state.sel = -1;
    showPreview(null);
    if (list.length && window.innerWidth > 760) select(0);
  }

  function select(i) {
    if (i < 0 || i >= state.list.length) return;
    state.sel = i;
    $$(".card", $("#results")).forEach((c) => c.classList.toggle("sel", Number(c.dataset.i) === i));
    const card = $(`.card[data-i="${i}"]`, $("#results"));
    card?.scrollIntoView({ block: "nearest" });
    showPreview(state.list[i]);
  }

  function loading() {
    $("#results").innerHTML = Array.from({ length: 5 }, () => `<div class="skeleton"></div>`).join("");
    $("#preview").innerHTML = `<div class="skeleton" style="height:240px"></div>`;
  }

  // ------------------------------------------------------------------ actions
  function currentFilters() {
    const yf = parseInt($("#yearFrom").value, 10), yt = parseInt($("#yearTo").value, 10);
    return {
      year_from: Number.isFinite(yf) ? yf : null,
      year_to: Number.isFinite(yt) ? yt : null,
      open_access_only: $("#oaOnly").checked,
      include_preprints: $("#preprints").checked,
      max_results: 40,
    };
  }

  async function runSearch() {
    const q = $("#q").value.trim();
    if (q.length < 2) return;
    storeSet("medagent.lastQuery", q);
    const go = $("#goBtn");
    go.disabled = true;
    loading();
    state.newIds = new Set();
    try {
      if (state.mode === "evidence") {
        state.bundle = await api("/api/search", { method: "POST", body: { query: q, filters: currentFilters() } });
      } else if (state.mode === "new") {
        state.bundle = await api(`/api/new?topic=${encodeURIComponent(q)}&days=${$("#days").value}`);
      } else if (state.mode === "trials") {
        const loc = $("#trialLocation").value.trim();
        const trials = await api(`/api/trials?term=${encodeURIComponent(q)}&recruiting=${$("#recruiting").checked}&limit=40${loc ? `&location=${encodeURIComponent(loc)}` : ""}`);
        state.bundle = { query: q, articles: [], trials, web: [], providers: [] };
      } else if (state.mode === "drug") {
        return await runDrug(q);
      }
      state.designOn.clear();
      renderFacets();
      renderProviders();
      renderResults();
    } catch (err) {
      $("#results").innerHTML = `<p class="err">Search failed: ${esc(err.message)}</p>`;
      $("#preview").innerHTML = "";
    } finally {
      go.disabled = false;
    }
  }

  async function runDrug(name) {
    loading();
    const { label, events, providers } = await api(`/api/drug/${encodeURIComponent(name)}`);
    state.bundle = { query: name, articles: [], trials: [], web: [], providers };
    renderProviders();
    const res = $("#results");
    if (!label) {
      res.innerHTML = `<p class="empty">No FDA label found for “${esc(name)}”. Try the generic name.</p>`;
    } else {
      const sec = (title, text, open = false) => text ? `<details class="lbl" ${open ? "open" : ""}><summary>${title}</summary><div>${esc(text)}</div></details>` : "";
      res.innerHTML = `<div class="preview" style="overflow:visible">
        <div class="row"><span class="badge plain">FDA label</span><span>${esc(label.manufacturer || "")}</span><span class="sep">effective ${esc(label.effective_date || "—")}</span></div>
        <h2>${esc(label.generic_names[0] || name)} <span class="muted" style="font-size:15px">${esc(label.brand_names.slice(0, 3).join(", "))}</span></h2>
        <div class="tags">${label.pharm_class.map((c) => `<span>${esc(c)}</span>`).join("")}${label.route.map((c) => `<span>${esc(c.toLowerCase())}</span>`).join("")}</div>
        ${label.boxed_warning ? `<div class="boxed"><h5>Boxed warning</h5><p>${esc(label.boxed_warning.replace(/^\s*(WARNING:?|BOXED WARNING:?)\s*/i, ""))}</p></div>` : ""}
        <div class="actions">${label.url ? `<a class="main" href="${esc(label.url)}" target="_blank" rel="noopener">DailyMed label</a>` : ""}
          <button id="drugEvidence">Search evidence for ${esc(name)}</button></div>
        ${sec("Indications", label.indications, true)}${sec("Dosage & administration", label.dosage, true)}
        ${sec("Contraindications", label.contraindications, true)}${sec("Warnings & precautions", label.warnings)}
        ${sec("Drug interactions", label.interactions)}${sec("Pregnancy / specific populations", label.pregnancy)}
        ${sec("Adverse reactions (label)", label.adverse_reactions)}
      </div>`;
      $("#drugEvidence").onclick = () => { setMode("evidence"); $("#q").value = name; runSearch(); };
    }
    const max = Math.max(1, ...(events?.top_reactions || []).map((r) => r.count));
    $("#preview").innerHTML = events ? `
      <div class="row"><span class="badge plain">FDA FAERS</span></div>
      <h2>Reported adverse events</h2>
      <dl class="facts">${fact("Reports", fmtN(events.total_reports))}${fact("Serious", fmtN(events.serious_reports))}
        ${fact("Serious %", events.total_reports ? Math.round((events.serious_reports / events.total_reports) * 100) + "%" : "—")}</dl>
      <div class="bars">${events.top_reactions.map((r) => `<div class="bar"><span>${esc(r.term)}</span><span class="track"><span class="fill" style="width:${(r.count / max) * 100}%;display:block"></span></span><span class="num">${fmtN(r.count)}</span></div>`).join("")}</div>
      <p class="muted" style="margin-top:12px">${esc(events.caveat)}</p>` : `<p class="muted">FAERS unavailable.</p>`;
  }

  // ------------------------------------------------------------- library/watch
  async function loadLibrary() {
    try { state.library = await api("/api/library"); } catch (_) { state.library = []; }
  }

  async function saveToLibrary(item) {
    if (item._kind && item._kind !== "article") { toast("Only papers can be saved to the library"); return; }
    const { _kind, ...article } = item;
    await api("/api/library", { method: "POST", body: article });
    await loadLibrary();
    toast("Saved to library");
  }

  function renderLibrary() {
    state.bundle = { query: "Library", articles: state.library, trials: [], web: [], providers: [] };
    renderFacets();
    renderProviders();
    renderResults();
    const bar = document.createElement("div");
    bar.className = "actions";
    bar.innerHTML = `<button data-f="ris">Export RIS</button><button data-f="bibtex">Export BibTeX</button><button data-f="vancouver">Copy reference list</button><button data-f="remove">Remove selected</button>`;
    $("#results").prepend(bar);
    if (!state.library.length) $("#results").insertAdjacentHTML("beforeend", `<p class="empty">Saved papers appear here. Use <b>Save</b> on any preview, or press <kbd>s</kbd>.</p>`);
    bar.onclick = async (e) => {
      const f = e.target.dataset.f;
      if (!f) return;
      if (f === "remove") {
        const it = state.list[state.sel];
        if (!it) return;
        await api(`/api/library?id=${encodeURIComponent(it.id)}`, { method: "DELETE" });
        await loadLibrary();
        return renderLibrary();
      }
      const text = await api("/api/export", { method: "POST", body: { articles: state.library, format: f } });
      if (f === "vancouver") copy(text);
      else download(f === "ris" ? "medagent.ris" : "medagent.bib", text);
    };
  }

  async function loadWatch() {
    try { state.watch = await api("/api/watch"); } catch (_) { state.watch = []; }
    const ul = $("#watchList");
    ul.innerHTML = state.watch.length ? state.watch.map((t) => `<li><button class="topic" data-id="${t.id}" title="Last checked ${esc(t.last_checked || "never")}">${esc(t.query)}</button><button class="x" data-del="${t.id}" aria-label="Stop watching">×</button></li>`).join("") : `<li class="muted">None yet</li>`;
  }

  async function openDigest(id) {
    setMode("new");
    loading();
    try {
      const d = await api(`/api/watch/${id}/digest`);
      $("#q").value = d.topic.query;
      state.bundle = d.bundle;
      state.newIds = new Set(d.new_ids);
      state.sort = "newest";
      renderFacets(); renderProviders(); renderResults();
      loadWatch();
    } catch (err) {
      $("#results").innerHTML = `<p class="err">${esc(err.message)}</p>`;
    }
  }

  // ---------------------------------------------------------------- Ask agent
  function mdToHtml(md) {
    const lines = md.replace(/\r/g, "").split("\n");
    const out = [];
    let i = 0;
    const inline = (s) => esc(s)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>")
      .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
      .replace(/\[(\d{1,3}(?:\s*[,–-]\s*\d{1,3})*)\]/g, (_, nums) => nums.split(/\s*,\s*/).map((n) => `<a class="cref" data-n="${n.split(/[–-]/)[0].trim()}">${n.trim()}</a>`).join(""));
    while (i < lines.length) {
      const line = lines[i];
      if (/^\s*\|.*\|\s*$/.test(line) && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1] || "")) {
        const row = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
        const head = row(line);
        i += 2;
        const rows = [];
        while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(row(lines[i++]));
        out.push(`<div class="tbl"><table><thead><tr>${head.map((h) => `<th>${inline(h)}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
        continue;
      }
      let m;
      if ((m = line.match(/^(#{1,4})\s+(.*)/))) { out.push(`<h${Math.min(m[1].length + 1, 4)}>${inline(m[2])}</h${Math.min(m[1].length + 1, 4)}>`); i++; continue; }
      if (/^\s*[-*]\s+/.test(line)) {
        const items = [];
        while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*[-*]\s+/, ""));
        out.push(`<ul>${items.map((t) => `<li>${inline(t)}</li>`).join("")}</ul>`);
        continue;
      }
      if (/^\s*\d+\.\s+/.test(line)) {
        const items = [];
        while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*\d+\.\s+/, ""));
        out.push(`<ol>${items.map((t) => `<li>${inline(t)}</li>`).join("")}</ol>`);
        continue;
      }
      if (!line.trim()) { i++; continue; }
      const para = [];
      while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|\s*[-*]\s|\s*\d+\.\s|\s*\|)/.test(lines[i])) para.push(lines[i++]);
      if (!para.length) { para.push(lines[i++]); }
      out.push(`<p>${inline(para.join(" "))}</p>`);
    }
    return out.join("");
  }

  function sourceTitle(s) { return s.record.title || s.record.generic_names?.[0] || s.record.nct_id || "Source"; }

  function sourceMeta(s) {
    const r = s.record;
    if (s.kind === "article") return `${loeBadge(r)}${flags(r)}<span>${esc(r.journal || "")} ${r.year || ""}</span>`;
    if (s.kind === "trial") return `<span class="st ${esc(r.status)}">${esc((r.status || "").replaceAll("_", " ").toLowerCase())}</span><span class="mono">${esc(r.nct_id)}</span>`;
    if (s.kind === "drug") return `<span class="badge plain">FDA label</span>`;
    return `${r.authority ? `<span class="badge l1">${esc(r.authority)}</span>` : ""}<span>${esc(r.site)}</span>`;
  }

  function addSources(items) {
    items.forEach((s) => state.askSources.set(s.n, s));
    const list = [...state.askSources.values()].sort((a, b) => a.n - b.n);
    $("#srcCount").textContent = list.length ? `(${list.length})` : "";
    $("#srcList").innerHTML = list.map((s) => `<div class="src" data-n="${s.n}" id="src-${s.n}"><span class="n">${s.n}</span><span class="t">${esc(sourceTitle(s))}</span><span class="m">${sourceMeta(s)}</span></div>`).join("");
  }

  function popoverFor(n, anchor) {
    const s = state.askSources.get(Number(n));
    const pop = $("#popover");
    if (!s) { pop.hidden = true; return; }
    const r = s.record;
    const body = s.kind === "article" ? (r.bottom_line || "") : s.kind === "trial" ? `${r.phases.join("/")} · n=${fmtN(r.enrollment)} · ${r.sponsor || ""}` : s.kind === "web" ? r.snippet : (r.indications || "").slice(0, 240);
    pop.innerHTML = `<div class="row">${sourceMeta(s)}</div><h4>[${s.n}] ${esc(sourceTitle(s))}</h4><div class="muted">${esc(body.slice(0, 360))}</div>`;
    pop.hidden = false;
    const rect = anchor.getBoundingClientRect();
    const top = rect.bottom + 6 + pop.offsetHeight > innerHeight ? rect.top - pop.offsetHeight - 6 : rect.bottom + 6;
    pop.style.top = `${Math.max(8, top)}px`;
    pop.style.left = `${Math.max(8, Math.min(rect.left, innerWidth - pop.offsetWidth - 8))}px`;
  }

  function openSource(n) {
    const s = state.askSources.get(Number(n));
    if (!s) return;
    const r = s.record;
    const url = s.kind === "article" ? r.url || (r.doi ? `https://doi.org/${r.doi}` : null) : r.url;
    const el = $(`#src-${n}`);
    el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    el?.classList.add("flash");
    setTimeout(() => el?.classList.remove("flash"), 1200);
    return url;
  }

  const TOOL_LABEL = {
    search_literature: "Searching literature", find_new_research: "Checking newest research", search_clinical_trials: "Searching trials",
    get_trial_details: "Reading trial record", drug_label: "Reading FDA label", drug_adverse_events: "Checking FAERS", get_article: "Reading abstract",
    search_web: "Searching guidelines & web", read_source: "Reading full text",
    analyze_clinical_text: "Clinical NLP on the case", extract_pico: "Extracting PICO", extract_effect_sizes: "Extracting effect sizes",
    list_calculators: "Listing calculators", run_calculator: "Running calculator", diagnostic_probability: "Bayes post-test probability",
    treatment_effect: "Computing ARR / NNT", load_skill: "Loading skill",
  };

  function argSummary(args) {
    if (args.name && args.inputs) return `${args.name} ${JSON.stringify(args.inputs).slice(0, 80)}`;
    const v = args.query || args.topic || args.condition || args.drug || args.nct_id || args.identifier || args.target || args.intervention
      || args.source || args.text || args.name || (args.pretest_probability != null ? `pre-test ${args.pretest_probability}` : "") || "";
    return String(v).slice(0, 90);
  }

  async function ask(question) {
    const thread = $("#thread");
    $("#askEmpty")?.remove();
    const turn = document.createElement("div");
    turn.className = "turn";
    turn.innerHTML = `<p class="q">${esc(question)}</p><div class="activity"></div><div class="answer streaming"></div>`;
    $("#askForm").before(turn);
    const activity = $(".activity", turn), answer = $(".answer", turn);
    let draft = "";
    const btn = $("#askBtn");
    btn.disabled = true;
    try {
      const res = await fetch("/api/ask/stream", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, conversation_id: state.conv, llm: activeLLM() }),
      });
      if (!res.ok || !res.body) throw new Error(`${res.status} ${res.statusText}`);
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let idx;
        while ((idx = buf.search(/\r?\n\r?\n/)) >= 0) {
          const raw = buf.slice(0, idx);
          buf = buf.slice(idx).replace(/^\r?\n\r?\n/, "");
          const data = raw.split(/\r?\n/).filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trimStart()).join("\n");
          if (!data) continue;
          let ev;
          try { ev = JSON.parse(data); } catch (_) { continue; }
          if (ev.type === "status") { state.conv = ev.conversation_id; }
          else if (ev.type === "skills") {
            const ner = ev.ner && ev.ner.backend !== "rules"
              ? `<span>NER: ${ev.ner.conditions.length} conditions, ${ev.ner.medications.length} drugs${ev.ner.negated.length ? `, ${ev.ner.negated.length} negated` : ""}</span>` : "";
            activity.insertAdjacentHTML("beforebegin", `<div class="skillbar">${ev.items.length ? "Skills" : "No specialised skill matched"}
              ${ev.items.map((k) => `<span class="skillchip" title="${esc(k.reasons.join(", "))}">${esc(k.title)}</span>`).join("")}${ner}</div>`);
          }
          else if (ev.type === "token") { draft += ev.text; answer.innerHTML = mdToHtml(draft); }
          else if (ev.type === "tool_start") {
            if (draft.trim()) { activity.insertAdjacentHTML("beforeend", `<div class="step">${esc(draft.trim().slice(0, 200))}</div>`); }
            draft = ""; answer.innerHTML = "";
            activity.insertAdjacentHTML("beforeend", `<div class="step run" data-id="${esc(ev.id)}"><span class="tool">${esc(TOOL_LABEL[ev.name] || ev.name)}</span><span>${esc(argSummary(ev.args || {}))}</span></div>`);
          } else if (ev.type === "tool_end") {
            const step = $(`.step[data-id="${CSS.escape(ev.id)}"]`, activity);
            step?.classList.replace("run", "done");
          } else if (ev.type === "sources") { addSources(ev.items); }
          else if (ev.type === "answer") { if (ev.text) answer.innerHTML = mdToHtml(ev.text); }
          else if (ev.type === "error") { throw new Error(ev.message); }
          thread.scrollTop = thread.scrollHeight;
        }
      }
    } catch (err) {
      answer.innerHTML = `<p class="err">${esc(err.message)}${/api[_ ]key|auth/i.test(err.message) ? "<br>Check the API key and base URL in Settings, or set a provider key in the server's .env." : ""}</p>`;
    } finally {
      answer.classList.remove("streaming");
      btn.disabled = false;
    }
  }

  function renderAskIntro() {
    const t = $("#thread");
    if (t.children.length) return;
    t.innerHTML = `<div class="empty" id="askEmpty"><h2>Ask a clinical question</h2>
      <p>The agent plans its searches, queries PubMed, Europe PMC, guideline bodies, ClinicalTrials.gov and FDA labels, reads what it needs, and answers with a bottom line, an evidence table and numbered citations. Hover a citation to preview the source.</p>
      ${state.health && !state.health.agent_ready && !activeLLM() ? `<p class="err">No model configured. Add your own Anthropic- or OpenAI-compatible key in <a href="#" data-goto="settings">Settings</a> to enable Ask. Search, trials and drug views work without it.</p>` : ""}</div>
      <form class="ask-box" id="askForm"><label class="sr-only" for="askInput">Question</label>
        <textarea id="askInput" placeholder="e.g. Is there RCT evidence for tenecteplase over alteplase in acute ischaemic stroke?"></textarea>
        <button class="primary" id="askBtn">Ask</button></form>`;
    $("#askForm").onsubmit = (e) => {
      e.preventDefault();
      const q = $("#askInput").value.trim();
      if (q.length < 3) return;
      $("#askInput").value = "";
      ask(q);
    };
    $("#askInput").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) $("#askForm").requestSubmit(); });
  }

  // ----------------------------------------------------------------- settings
  function readCard(provider) {
    const f = $(`.llmcard[data-provider="${provider}"]`);
    return { base_url: f.base_url.value.trim(), api_key: f.api_key.value.trim(), model: f.model.value.trim() };
  }

  function markActiveCard() {
    const active = $('input[name="llmActive"]:checked').value;
    $$(".llmcard").forEach((f) => f.classList.toggle("active", f.dataset.provider === active));
  }

  function renderSettings() {
    const s = loadLLM();
    $("#serverModel").textContent = state.health ? `(${state.health.model}${state.health.agent_ready ? "" : ", no key on server"})` : "";
    for (const provider of ["anthropic", "openai"]) {
      const f = $(`.llmcard[data-provider="${provider}"]`);
      f.base_url.value = s[provider].base_url || "";
      f.api_key.value = s[provider].api_key || "";
      f.model.value = s[provider].model || "";
      $(".testmsg", f).textContent = "";
    }
    $$('input[name="llmActive"]').forEach((r) => (r.checked = r.value === s.active));
    markActiveCard();
  }

  function saveSettings() {
    const active = $('input[name="llmActive"]:checked').value;
    const next = { active, anthropic: readCard("anthropic"), openai: readCard("openai") };
    if (active !== "server" && !next[active].api_key) return toast("Add an API key for the selected endpoint first");
    storeSet(LLM_KEY, next);
    if ($("#askEmpty")) $("#thread").innerHTML = "";  // re-render the Ask intro without the stale "no model" notice
    updateAgentStatus();
    toast(active === "server" ? "Using the server's model" : `Saved — Ask now uses your ${active === "openai" ? "OpenAI" : "Anthropic"}-compatible endpoint`);
  }

  async function testCard(provider) {
    const f = $(`.llmcard[data-provider="${provider}"]`);
    const out = $(".testmsg", f);
    const llm = llmConfig(provider, readCard(provider));
    if (!llm) { out.className = "testmsg bad"; out.textContent = "Enter an API key first"; return; }
    out.className = "testmsg"; out.textContent = "Testing…";
    try {
      const r = await api("/api/llm/test", { method: "POST", body: { llm } });
      out.className = `testmsg ${r.ok ? "ok" : "bad"}`;
      out.textContent = r.ok ? `Connected (${llm.model}): ${r.reply}` : r.error;
    } catch (err) { out.className = "testmsg bad"; out.textContent = err.message; }
  }

  function updateAgentStatus() {
    const dot = $("#agentDot");
    if (!dot) return;
    const own = activeLLM();
    dot.classList.toggle("off", !(own || state.health?.agent_ready));
    dot.parentElement.title = own ? `${own.provider}-compatible: ${own.model}` : state.health?.model || "";
  }

  // -------------------------------------------------------------------- modes
  function setMode(mode) {
    state.mode = mode;
    storeSet("medagent.mode", mode);
    $$(".modes button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.mode === mode)));
    const isAsk = mode === "ask", isCalc = mode === "calc", isSettings = mode === "settings";
    $("#askView").hidden = !isAsk;
    $("#calcView").hidden = !isCalc;
    $("#settingsView").hidden = !isSettings;
    $("#desk").hidden = isAsk || isCalc || isSettings;
    $("#searchForm").hidden = isAsk || isCalc || isSettings || mode === "library";
    $("#desk").classList.toggle("no-rail", mode === "drug" || mode === "trials");
    $("#days").hidden = mode !== "new";
    $("#watchBtn").hidden = mode !== "new";
    $("#trialLocation").hidden = mode !== "trials";
    $("#recruitingWrap").hidden = mode !== "trials";
    $("#goBtn").textContent = { evidence: "Search", new: "Show new", trials: "Find trials", drug: "Look up" }[mode] || "Search";
    $("#q").placeholder = { evidence: "e.g. SGLT2 inhibitors in HFpEF", new: "Topic to scan for new research", trials: "Condition or intervention", drug: "Generic or brand name" }[mode] || "";
    $("#examples").innerHTML = (EXAMPLES[mode] || []).map((e) => `<button type="button">${esc(e)}</button>`).join("");
    if (isAsk) { renderAskIntro(); return; }
    if (isCalc) { renderCalcView(); return; }
    if (isSettings) { renderSettings(); return; }
    if (mode === "library") { loadLibrary().then(renderLibrary); return; }
    state.bundle = null;
    $("#results").innerHTML = "";
    renderFacets(); renderProviders(); showPreview(null);
  }

  // ------------------------------------------------------------------- wiring
  async function init() {
    try {
      state.health = await api("/api/health");
      const h = state.health;
      $("#status").innerHTML = ["PubMed", "Europe PMC", "OpenAlex", "ClinicalTrials.gov", "openFDA"].map((s) => `<span><span class="dot"></span>${s}</span>`).join("")
        + `<span title="Web search and page reading"><span class="dot ${h.tinyfish ? "" : "off"}"></span>TinyFish</span>`
        + `<span title="${esc(h.model)}"><span id="agentDot" class="dot ${h.agent_ready ? "" : "off"}"></span>Agent</span>`
        + `<span title="${esc((h.ml || []).map((m) => `${m.component}: ${m.backend}`).join("\n"))}"><span class="dot"></span>ML models</span>`;
      updateAgentStatus();
    } catch (_) { $("#status").textContent = "Server unreachable"; }

    $$(".modes button").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
    $("#searchForm").addEventListener("submit", (e) => { e.preventDefault(); runSearch(); });
    $("#examples").addEventListener("click", (e) => {
      if (e.target.tagName !== "BUTTON") return;
      if (state.mode === "ask") { $("#askInput").value = e.target.textContent; return; }
      $("#q").value = e.target.textContent; runSearch();
    });
    $("#results").addEventListener("click", (e) => { const c = e.target.closest(".card"); if (c) select(Number(c.dataset.i)); });
    $("#designFilters").addEventListener("change", (e) => {
      if (e.target.checked) state.designOn.add(e.target.value); else state.designOn.delete(e.target.value);
      renderResults();
    });
    $("#yearChips").addEventListener("click", (e) => {
      const y = e.target.dataset.years;
      if (y === undefined) return;
      $$("#yearChips button").forEach((b) => b.classList.toggle("on", b === e.target));
      $("#yearFrom").value = Number(y) ? new Date().getFullYear() - Number(y) : "";
      $("#yearTo").value = "";
      if (state.bundle && state.mode === "evidence") runSearch();
    });
    ["#oaOnly", "#preprints"].forEach((id) => $(id).addEventListener("change", () => state.bundle && state.mode === "evidence" && runSearch()));
    $("#watchBtn").addEventListener("click", async () => {
      const q = $("#q").value.trim();
      if (q.length < 2) return toast("Type a topic first");
      await api("/api/watch", { method: "POST", body: { query: q, days: Number($("#days").value) } });
      await loadWatch();
      toast(`Watching “${q}”`);
    });
    $("#watchList").addEventListener("click", async (e) => {
      if (e.target.dataset.del) { await api(`/api/watch/${e.target.dataset.del}`, { method: "DELETE" }); return loadWatch(); }
      if (e.target.dataset.id) openDigest(e.target.dataset.id);
    });
    $("#askView").addEventListener("mouseover", (e) => { const c = e.target.closest(".cref"); if (c) popoverFor(c.dataset.n, c); });
    $("#askView").addEventListener("mouseout", (e) => { if (e.target.closest(".cref")) $("#popover").hidden = true; });
    $("#askView").addEventListener("click", (e) => {
      const c = e.target.closest(".cref, .src");
      if (!c) return;
      const url = openSource(c.dataset.n);
      if (c.classList.contains("src") && url) window.open(url, "_blank", "noopener");
    });

    $("#calcList").addEventListener("click", (e) => { const b = e.target.closest("[data-calc]"); if (b) renderCalcView(b.dataset.calc); });
    $("#caseOut").addEventListener("click", (e) => { const b = e.target.closest("[data-calc]"); if (b) renderCalcView(b.dataset.calc); });
    $("#analyzeBtn").addEventListener("click", analyzeCase);

    $("#settingsView").addEventListener("change", (e) => { if (e.target.name === "llmActive") markActiveCard(); });
    $("#settingsView").addEventListener("click", (e) => {
      const b = e.target.closest('[data-act="test"]');
      if (b) testCard(b.closest(".llmcard").dataset.provider);
    });
    $("#llmSave").addEventListener("click", saveSettings);
    $("#llmClear").addEventListener("click", () => {
      try { localStorage.removeItem(LLM_KEY); } catch (_) { /* private mode */ }
      if ($("#askEmpty")) $("#thread").innerHTML = "";
      renderSettings(); updateAgentStatus();
      toast("Saved keys cleared");
    });
    document.addEventListener("click", (e) => {
      const g = e.target.closest("[data-goto]");
      if (g) { e.preventDefault(); setMode(g.dataset.goto); }
    });

    document.addEventListener("keydown", (e) => {
      const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName);
      if (e.key === "/" && !typing) { e.preventDefault(); (state.mode === "ask" ? $("#askInput") : $("#q"))?.focus(); return; }
      if (typing || state.mode === "ask" || state.mode === "calc" || state.mode === "settings") return;
      if (e.key === "j") select(Math.min(state.sel + 1, state.list.length - 1));
      if (e.key === "k") select(Math.max(state.sel - 1, 0));
      const cur = state.list[state.sel];
      if (e.key === "s" && cur) saveToLibrary(cur);
      if (e.key === "o" && cur) { const u = cur.url || (cur.doi && `https://doi.org/${cur.doi}`); if (u) window.open(u, "_blank", "noopener"); }
      if (e.key === "Enter" && document.activeElement?.classList.contains("card")) select(Number(document.activeElement.dataset.i));
    });

    await Promise.all([loadLibrary(), loadWatch()]);
    const last = storeGet("medagent.lastQuery", "");
    const savedMode = storeGet("medagent.mode", "evidence");
    setMode(["ask", "calc", "settings"].includes(savedMode) ? savedMode : "evidence");
    if (last) $("#q").value = last;
  }

  init();
})();
