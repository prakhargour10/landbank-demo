/* LANDBANK MSME Lending · Agent Data Console (vanilla JS, no build step).
   Human actions use the selected role's key. "Agent" buttons simulate an AgenticOrg agent step
   with that agent's key, so the demo works before AgenticOrg is connected. */
(() => {
  const S = { cfg: null, role: null, agents: {} };
  const $ = (sel, el = document) => el.querySelector(sel);
  const main = () => $("#main");
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const peso = (v) => {
    const a = Number(v || 0);
    if (Math.abs(a) >= 1e6) return "₱" + (a / 1e6).toFixed(2) + "M";
    if (Math.abs(a) >= 1e5) return "₱" + (a / 1e3).toFixed(0) + "K";
    return "₱" + a.toLocaleString("en-PH", { maximumFractionDigits: 0 });
  };
  const pct = (v) => (v === null || v === undefined ? "—" : (v > 0 ? "+" : "") + v + "%");
  const badge = (s) => `<span class="badge b-${esc(s)}">${esc(String(s ?? "").replaceAll("_", " "))}</span>`;
  const dt = (s) => (s ? String(s).replace("T", " ").slice(0, 16) : "—");
  const d10 = (s) => (s ? String(s).slice(0, 10) : "—");

  function toast(msg, err) {
    const t = $("#toast");
    t.textContent = msg;
    t.className = "toast show" + (err ? " err" : "");
    clearTimeout(t._h);
    t._h = setTimeout(() => (t.className = "toast"), 3800);
  }

  async function api(path, { method = "GET", body, key, form } = {}) {
    const headers = { "X-API-Key": key || S.role.key };
    const opts = { method, headers };
    if (form) opts.body = form;
    else if (body !== undefined) { headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    const r = await fetch("/api/v1" + path, opts);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      const msg = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data);
      throw new Error(`${r.status}: ${msg}`);
    }
    return data;
  }
  const agentKey = (name) => S.agents[name];
  async function act(fn, okMsg, reload = true) {
    try { const res = await fn(); if (okMsg) toast(okMsg); if (reload) route(); return res; }
    catch (e) { toast(e.message, true); }
  }
  const can = (...roles) => roles.includes(S.role.role) || S.role.role === "admin";

  function modal(html, onSubmit) {
    const m = $("#modal");
    $("#modal-card").innerHTML = html + `<div class="btn-row" style="margin-top:16px"><button class="btn" id="m-ok">Save</button><button class="btn secondary" id="m-cancel">Cancel</button></div>`;
    m.classList.remove("hidden");
    $("#m-cancel").onclick = () => m.classList.add("hidden");
    $("#m-ok").onclick = async () => { const v = {}; m.querySelectorAll("[name]").forEach((i) => (v[i.name] = i.value)); m.classList.add("hidden"); await onSubmit(v); };
  }

  // ------------------------------------------------------------------ small chart helpers
  function cashChart(months) {
    if (!months || !months.length) return '<div class="empty">No data</div>';
    const W = 560, H = 170, pad = 28, bw = (W - pad * 2) / months.length;
    const max = Math.max(...months.map((m) => Math.max(m.inflow || 0, m.outflow || 0))) || 1;
    let bars = "";
    months.forEach((m, i) => {
      const x = pad + i * bw;
      const hi = ((m.inflow || 0) / max) * (H - 40), ho = ((m.outflow || 0) / max) * (H - 40);
      bars += `<rect x="${x + 3}" y="${H - 20 - hi}" width="${bw / 2 - 4}" height="${hi}" rx="2" fill="#00733c"><title>${m.month} inflow ${peso(m.inflow)}</title></rect>`;
      bars += `<rect x="${x + bw / 2}" y="${H - 20 - ho}" width="${bw / 2 - 4}" height="${ho}" rx="2" fill="#f2b705"><title>${m.month} outflow ${peso(m.outflow)}</title></rect>`;
      bars += `<text x="${x + bw / 2}" y="${H - 6}" text-anchor="middle">${m.month.slice(2)}</text>`;
    });
    return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Monthly inflow and outflow">${bars}</svg>
      <div class="legend"><span><span class="dot" style="background:#00733c"></span>Inflow</span><span><span class="dot" style="background:#f2b705"></span>Outflow</span></div>`;
  }
  function healthStack(byHealth) {
    const tot = byHealth.reduce((a, b) => a + b.customers, 0) || 1;
    const col = { HEALTHY: "#00733c", WATCH: "#e0a100", HIGH_ATTENTION: "#c0392b" };
    const order = ["HEALTHY", "WATCH", "HIGH_ATTENTION"];
    const rows = order.map((k) => byHealth.find((b) => b.health_status === k) || { health_status: k, customers: 0, exposure: 0 });
    return `<div class="stack">${rows.map((r) => `<span style="width:${(r.customers / tot) * 100}%;background:${col[r.health_status]}"></span>`).join("")}</div>
      <div class="legend">${rows.map((r) => `<span><span class="dot" style="background:${col[r.health_status]}"></span>${r.health_status.replace("_", " ")} · ${r.customers} · ${peso(r.exposure)}</span>`).join("")}</div>`;
  }

  // ------------------------------------------------------------------ views
  const views = {};

  views.dashboard = async () => {
    const [s, ev] = await Promise.all([api("/portfolio/summary"), api("/events?limit=12")]);
    const hc = (k) => (s.by_health.find((b) => b.health_status === k) || { customers: 0 }).customers;
    const maxReg = Math.max(...s.by_region.map((r) => r.exposure)) || 1;
    const appCount = (st) => (s.applications_by_status.find((a) => a.status === st) || { n: 0 }).n;
    main().innerHTML = `
      <div class="page-head"><div><h1>Portfolio dashboard</h1><div class="muted">MSME book as of ${esc(s.as_of)} · all figures synthetic</div></div>
        <div class="btn-row">${S.agents.portfolio ? `<button class="btn agent" id="run-mon">▶ Portfolio agent: run monitoring</button>` : ""}</div></div>
      <div class="grid g4">
        <div class="card kpi accent"><div class="label">MSME customers</div><div class="value">${s.customers}</div><div class="sub">${s.active_loans} active loans</div></div>
        <div class="card kpi gold"><div class="label">Total exposure</div><div class="value">${peso(s.total_exposure)}</div><div class="sub">outstanding</div></div>
        <div class="card kpi warn"><div class="label">Watch / High attention</div><div class="value">${hc("WATCH")} / ${hc("HIGH_ATTENTION")}</div><div class="sub">${s.open_alerts} open alerts</div></div>
        <div class="card kpi accent"><div class="label">Growth opportunities</div><div class="value">${s.open_opportunities}</div><div class="sub">${peso(s.opportunity_value)} potential</div></div>
      </div>
      <div class="grid g2 section">
        <div class="card"><h2>Health mix</h2>${healthStack(s.by_health)}
          <div class="grid g3 section">
            <div><div class="muted small">Pending credit reviews</div><div style="font-size:20px;font-weight:700">${s.pending_credit_reviews}</div></div>
            <div><div class="muted small">Open RM tasks</div><div style="font-size:20px;font-weight:700">${s.open_rm_tasks}</div></div>
            <div><div class="muted small">Open leads</div><div style="font-size:20px;font-weight:700">${s.open_leads}</div></div>
          </div></div>
        <div class="card"><h2>Exposure by region</h2>${s.by_region.map((r) => `<div class="row-bar"><div>${esc(r.region)}</div><div class="bar"><span style="width:${(r.exposure / maxReg) * 100}%"></span></div><div class="num small">${peso(r.exposure)}</div></div>`).join("")}</div>
      </div>
      <div class="grid g2 section">
        <div class="card"><h2>Application funnel</h2>
          ${["DRAFT", "WAITING_FOR_DOCUMENTS", "DOCUMENTS_COMPLETE", "IN_ASSESSMENT", "CREDIT_CASE_READY", "SUBMITTED_FOR_REVIEW", "UNDER_REVIEW", "APPROVED", "ACTIVE"].map((st) => `<div class="row-bar"><div>${badge(st)}</div><div class="bar"><span style="width:${appCount(st) * 25}%"></span></div><div class="num">${appCount(st)}</div></div>`).join("")}
        </div>
        <div class="card"><h2>Latest events</h2><ul class="timeline">${ev.map((e) => `<li>${badge(e.actor_type)} <b>${esc(e.event_type)}</b> <span class="muted small">${esc(e.actor_name)} · ${dt(e.occurred_at)}${e.customer_id ? " · " + esc(e.customer_id) : ""}</span></li>`).join("") || '<div class="empty">No events yet</div>'}</ul></div>
      </div>`;
    const b = $("#run-mon");
    if (b) b.onclick = () => act(async () => { const r = await api("/portfolio/monitoring-run", { method: "POST", key: agentKey("portfolio") }); toast(`${r.customers_checked} checked · ${r.needs_attention.length} need attention`); });
  };

  views.customers = async (params) => {
    const q = new URLSearchParams(params || {});
    const rows = await api("/customers?" + q.toString());
    main().innerHTML = `
      <div class="page-head"><div><h1>Customers</h1><div class="muted">${rows.length} synthetic MSMEs</div></div></div>
      <div class="filters">
        <input id="f-q" placeholder="Search name or ID" value="${esc(q.get("search") || "")}">
        <select id="f-h"><option value="">All health</option>${["HEALTHY", "WATCH", "HIGH_ATTENTION"].map((h) => `<option ${q.get("health_status") === h ? "selected" : ""}>${h}</option>`).join("")}</select>
        <button class="btn secondary" id="f-go">Filter</button>
      </div>
      <div class="card table-wrap"><table><thead><tr><th>Customer</th><th>Sector · Region</th><th>RM</th><th class="num">Outstanding</th><th class="num">DPD</th><th>Health</th></tr></thead><tbody>
      ${rows.map((c) => `<tr class="clickable" data-id="${esc(c.customer_id)}"><td><b>${esc(c.business_name)}</b><div class="muted small">${esc(c.customer_id)} · ${esc(c.owner_name)}</div></td><td>${esc(c.sector)}<div class="muted small">${esc(c.region)}</div></td><td>${esc(c.rm_name)}</td><td class="num">${peso(c.total_outstanding)}</td><td class="num">${c.max_days_past_due ?? 0}</td><td>${badge(c.health_status)}</td></tr>`).join("")}
      </tbody></table></div>`;
    main().querySelectorAll("tr[data-id]").forEach((tr) => (tr.onclick = () => (location.hash = "#/customer/" + tr.dataset.id)));
    $("#f-go").onclick = () => {
      const p = new URLSearchParams();
      if ($("#f-q").value) p.set("search", $("#f-q").value);
      if ($("#f-h").value) p.set("health_status", $("#f-h").value);
      location.hash = "#/customers?" + p.toString();
    };
  };

  views.customer = async (id) => {
    const x = await api(`/customers/${id}/360`);
    const p = x.profile, h = x.health, m = h.metrics;
    let opps = { opportunities: [] };
    try { opps = await api(`/customers/${id}/opportunities`, { key: agentKey("growth") || S.role.key }); } catch (e) { /* ignore */ }
    main().innerHTML = `
      <div class="page-head"><div><a href="#/customers" class="small">← Customers</a><h1>${esc(p.business_name)} ${badge(h.status)}</h1>
        <div class="muted">${esc(p.customer_id)} · ${esc(p.sector)} · ${esc(p.city)}, ${esc(p.province)} · RM ${esc(p.rm_name)}</div></div>
        <div class="btn-row">
          ${S.agents.portfolio ? `<button class="btn agent" id="c-sig">▶ Portfolio agent: recalculate signals</button>` : ""}
          ${can("admin") ? `<button class="btn danger" id="c-stress">Demo: apply stress</button>` : ""}
        </div></div>
      <div class="callout gold small"><b>Scenario (synthetic):</b> ${esc(p.scenario)} — ${esc(p.scenario_note)}</div>
      <div class="grid g4 section">
        <div class="card kpi accent"><div class="label">Receipts last 2 months</div><div class="value">${pct(m.inflow_change_pct)}</div><div class="sub">${peso(m.avg_monthly_receipts_last2)}/month vs prior 3</div></div>
        <div class="card kpi ${m.days_past_due >= 30 ? "bad" : m.days_past_due ? "warn" : "accent"}"><div class="label">Days past due</div><div class="value">${m.days_past_due}</div><div class="sub">max across loans</div></div>
        <div class="card kpi ${m.utilisation_pct >= 95 ? "bad" : m.utilisation_pct >= 85 ? "warn" : "accent"}"><div class="label">WC line utilisation</div><div class="value">${m.utilisation_pct ?? "—"}${m.utilisation_pct ? "%" : ""}</div><div class="sub">working-capital lines</div></div>
        <div class="card kpi gold"><div class="label">Credit score (CIC, synthetic)</div><div class="value">${x.credit_report.score}</div><div class="sub">${esc(x.credit_report.score_band)}</div></div>
      </div>
      <div class="grid g2 section">
        <div class="card"><h2>Early-warning signals</h2>${h.signals.length ? h.signals.map((s) => `<div class="signal ${s.level}"><b>${esc(s.name)}</b> ${badge(s.level)}<div>${esc(s.explanation)}</div></div>`).join("") : '<div class="callout">No early-warning signals. Cash margin ' + pct(m.cash_margin_pct) + ", balances " + pct(m.avg_balance_change_pct) + ".</div>"}
          <div class="muted small" style="margin-top:8px">Windows: last 2 months ${esc(m.window_last2)} vs ${esc(m.window_prior3)}</div></div>
        <div class="card"><h2>Monthly cash flow (6 months)</h2>${cashChart(x.monthly_cashflow)}</div>
      </div>
      <div class="grid g2 section">
        <div class="card"><h2>Profile</h2><div class="kv">
          <div>Owner</div><div>${esc(p.owner_name)}</div><div>Legal form</div><div>${esc(p.legal_form)} · ${esc(p.registration_body)} ${esc(p.registration_no)}</div>
          <div>TIN (synthetic)</div><div>${esc(p.tin)}</div><div>In business</div><div>${p.business_vintage_years} years · ${p.employees} employees</div>
          <div>With LANDBANK</div><div>${p.relationship_years} years (since ${d10(p.customer_since)})</div><div>KYC</div><div>${badge(p.kyc_status)}</div>
          <div>Products held</div><div>${x.products.map((pp) => esc(pp.name)).join(", ")}</div></div></div>
        <div class="card"><h2>Loans</h2><div class="table-wrap"><table><thead><tr><th>Loan</th><th class="num">Limit</th><th class="num">Outstanding</th><th class="num">Monthly</th><th class="num">DPD</th></tr></thead><tbody>
          ${x.loans.map((l) => `<tr><td>${esc(l.product_name)}<div class="muted small">${esc(l.loan_id)}</div></td><td class="num">${peso(l.sanctioned_amount)}</td><td class="num">${peso(l.outstanding)}</td><td class="num">${peso(l.monthly_amortization)}</td><td class="num">${l.days_past_due}</td></tr>`).join("") || '<tr><td colspan="5" class="empty">No loans</td></tr>'}
          </tbody></table></div></div>
      </div>
      <div class="grid g2 section">
        <div class="card"><h2>Next-best opportunities</h2>${opps.opportunities.length ? opps.opportunities.map((o) => `<div class="callout" style="margin-bottom:8px"><b>${esc(o.product_name)}</b> · ${Math.round(o.confidence * 100)}% confidence · ${peso(o.estimated_value)} <span class="muted small">(${esc(o.value_basis)})</span><ul class="small">${o.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>${can("rm") || S.agents.growth ? `<button class="btn secondary" data-lead="${esc(o.product_code)}" data-opp="${esc(o.opportunity_id)}">Create RM lead</button>` : ""}</div>`).join("") : `<div class="empty">${esc(opps.note || "No opportunities")}</div>`}</div>
        <div class="card"><h2>Open work</h2>
          ${x.open_alerts.map((a) => `<div class="signal HIGH"><b>${esc(a.alert_id)}</b> ${badge(a.severity)} ${badge(a.status)}<div>${esc(a.summary)}</div></div>`).join("")}
          ${x.open_tasks.map((t) => `<div class="callout" style="margin-bottom:6px">${badge(t.priority)} <b>${esc(t.title)}</b> · due ${d10(t.due_date)} ${badge(t.status)}</div>`).join("")}
          ${x.open_leads.map((l) => `<div class="callout gold" style="margin-bottom:6px">Lead ${esc(l.lead_id)} · ${esc(l.product_code)} ${badge(l.status)}</div>`).join("")}
          ${x.applications.map((a) => `<div style="margin:6px 0"><a href="#/application/${esc(a.application_id)}">${esc(a.application_id)}</a> · ${esc(a.product_code)} · ${peso(a.amount_requested)} ${badge(a.status)}</div>`).join("")}
          ${!x.open_alerts.length && !x.open_tasks.length && !x.open_leads.length && !x.applications.length ? '<div class="empty">Nothing open</div>' : ""}
        </div>
      </div>
      <div class="card section"><h2>Recent events</h2><ul class="timeline">${x.recent_events.map((e) => `<li>${badge(e.actor_type)} <b>${esc(e.event_type)}</b> <span class="muted small">${esc(e.actor_name)} · ${dt(e.occurred_at)}</span></li>`).join("") || '<div class="empty">No events</div>'}</ul></div>`;
    const sig = $("#c-sig");
    if (sig) sig.onclick = () => act(() => api(`/customers/${id}/signals`, { method: "POST", key: agentKey("portfolio") }), "Signals recalculated");
    const st = $("#c-stress");
    if (st) st.onclick = () => act(() => api(`/admin/customers/${id}/apply-stress`, { method: "POST", body: { severity: "HIGH" } }), "Stress applied — recalculate signals to see the effect");
    main().querySelectorAll("[data-lead]").forEach((b) => (b.onclick = () => act(() => api("/leads", { method: "POST", key: can("rm") ? S.role.key : agentKey("growth"), body: { customer_id: id, product_code: b.dataset.lead, opportunity_id: b.dataset.opp, reason: "Evidence-backed opportunity from the RM & Growth agent" } }), "Lead created in the RM work queue")));
  };

  views.applications = async () => {
    const rows = await api("/applications");
    main().innerHTML = `<div class="page-head"><div><h1>Applications</h1><div class="muted">AI-prepared files · people decide</div></div>
      ${S.agents.application ? '<button class="btn agent" id="new-app">▶ Application agent: start application</button>' : ""}</div>
      <div class="card table-wrap"><table><thead><tr><th>Application</th><th>Customer</th><th>Product</th><th class="num">Amount</th><th class="num">Readiness</th><th>Status</th><th>Updated</th></tr></thead><tbody>
      ${rows.map((a) => `<tr class="clickable" data-id="${esc(a.application_id)}"><td><b>${esc(a.application_id)}</b></td><td>${esc(a.business_name)}<div class="muted small">${esc(a.customer_id)}</div></td><td>${esc(a.product_name)}<div class="muted small">${a.tenure_months} months</div></td><td class="num">${peso(a.amount_requested)}</td><td class="num">${a.readiness_score ?? "—"}</td><td>${badge(a.status)}</td><td class="small">${dt(a.updated_at)}</td></tr>`).join("")}
      </tbody></table></div>`;
    main().querySelectorAll("tr[data-id]").forEach((tr) => (tr.onclick = () => (location.hash = "#/application/" + tr.dataset.id)));
    const n = $("#new-app");
    if (n) n.onclick = () => modal(`<h2>Start application (simulated agent step)</h2>
        <label>Customer ID</label><input name="customer_id" value="LB-MSME-0009">
        <label>Product</label><select name="product_code"><option>WORKING_CAPITAL</option><option>TERM_LOAN</option><option>EQUIPMENT_FINANCING</option><option>AGRI_PRODUCTION_LOAN</option><option>INVOICE_FINANCING</option></select>
        <label>Amount (PHP)</label><input name="amount" value="3000000"><label>Tenure (months)</label><input name="tenure_months" value="12">
        <label>Purpose</label><input name="purpose" value="Copra procurement for peak season">`,
      (v) => act(async () => { const a = await api("/applications", { method: "POST", key: agentKey("application"), body: { ...v, amount: Number(v.amount), tenure_months: Number(v.tenure_months) } }); location.hash = "#/application/" + a.application_id; }, "Application started", false));
  };

  const FLOW = ["DRAFT", "WAITING_FOR_DOCUMENTS", "DOCUMENTS_COMPLETE", "IN_ASSESSMENT", "CREDIT_CASE_READY", "SUBMITTED_FOR_REVIEW", "UNDER_REVIEW", "RECOMMENDED_APPROVAL", "APPROVED", "ACTIVE"];

  views.application = async (id) => {
    const a = await api(`/applications/${id}`);
    let fa = null, cc = null;
    try { fa = await api(`/applications/${id}/financial-analysis`); } catch (e) { /* none yet */ }
    try { cc = await api(`/applications/${id}/credit-case`); } catch (e) { /* none yet */ }
    const idx = FLOW.indexOf(a.status);
    const st = a.status;
    const agentBtn = (label, fn, enabled = true) => (S.agents.application ? `<button class="btn agent" data-agent="${fn}" ${enabled ? "" : "disabled"}>▶ ${label}</button>` : "");
    const humanBtn = (label, fn, roles, enabled = true, cls = "") => (can(...roles) ? `<button class="btn ${cls}" data-human="${fn}" ${enabled ? "" : "disabled"}>${label}</button>` : "");
    const review = ["SUBMITTED_FOR_REVIEW", "UNDER_REVIEW"].includes(st);
    main().innerHTML = `
      <div class="page-head"><div><a href="#/applications" class="small">← Applications</a><h1>${esc(a.application_id)} ${badge(st)}</h1>
        <div class="muted"><a href="#/customer/${esc(a.customer_id)}">${esc(a.business_name)}</a> · ${esc(a.product_name)} · ${peso(a.amount_requested)} · ${a.tenure_months} months · ${esc(a.purpose)}</div></div></div>
      <div class="stepper">${FLOW.map((f, i) => `<span class="step ${i < idx ? "done" : i === idx ? "current" : ""}">${f.replaceAll("_", " ")}</span>`).join("")}</div>
      ${!FLOW.includes(st) ? `<div class="callout gold">Current status: <b>${esc(st)}</b>${a.decision_reason ? " — " + esc(a.decision_reason) : ""}</div>` : ""}
      <div class="grid g2 section">
        <div class="card"><h2>1 · Consent &amp; documents <span class="muted small">MSME Application Agent</span></h2>
          <div class="kv" style="margin-bottom:10px"><div>Consent</div><div>${a.consent ? `${badge(a.consent.status)} <span class="small muted">${esc(a.consent.consent_id)} · ${esc((a.consent.data_scopes || []).join(", "))}</span>` : '<span class="muted">Not requested</span>'}</div></div>
          <div class="btn-row" style="margin-bottom:10px">
            ${agentBtn("Request consent", "consent", !a.consent || a.consent.status !== "GRANTED")}
            ${a.consent && a.consent.status === "REQUESTED" ? humanBtn("MSME: grant consent", "grant", ["applicant"]) : ""}
            ${agentBtn("Fetch documents", "fetch", a.consent && a.consent.status === "GRANTED")}
            ${agentBtn("Validate documents", "validate")}
          </div>
          <div class="table-wrap"><table><thead><tr><th>Document</th><th>Status</th><th></th></tr></thead><tbody>
          ${a.documents.map((d) => `<tr><td>${esc(d.doc_name)}<div class="muted small">${esc(d.source || "")}${d.pages_expected ? ` · ${d.pages_received ?? 0}/${d.pages_expected} pages` : ""}</div>
            ${(d.issues || []).map((i) => `<div class="small" style="color:${i.severity === "BLOCKING" ? "var(--red)" : "var(--amber)"}">${esc(i.severity)}: ${esc(i.message)}</div>`).join("")}
            ${d.requested_reason ? `<div class="small muted">Requested: ${esc(d.requested_reason)}</div>` : ""}</td>
            <td>${badge(d.status)}</td>
            <td class="btn-row">${d.document_id && d.status !== "REQUESTED" ? `<a class="small" target="_blank" href="#" data-pdf="${esc(d.document_id)}">PDF</a>` : ""}
              ${["NOT_PROVIDED", "REQUESTED", "ISSUE_FOUND"].includes(d.status) && can("applicant") ? `<button class="btn secondary" data-upload="${esc(d.doc_type)}">Upload</button>` : ""}
              ${["NOT_PROVIDED", "ISSUE_FOUND"].includes(d.status) && S.agents.application ? `<button class="btn agent" data-request="${esc(d.doc_type)}">Request</button>` : ""}</td></tr>`).join("")}
          </tbody></table></div></div>
        <div class="card"><h2>2 · Financial analysis <span class="muted small">Financial Analysis Agent</span></h2>
          ${S.agents.financial ? `<button class="btn agent" data-agent="fa" ${["DOCUMENTS_COMPLETE", "IN_ASSESSMENT", "CREDIT_CASE_READY", "MORE_INFO_REQUESTED"].includes(st) ? "" : "disabled"}>▶ Run financial analysis</button>` : ""}
          ${fa ? `<div class="grid g2 section">
              <div><div class="muted small">Annual customer receipts</div><b>${peso(fa.metrics.annual_customer_receipts)}</b> <span class="small">${pct(fa.metrics.receipts_growth_last6_vs_first6_pct)}</span></div>
              <div><div class="muted small">Avg monthly surplus</div><b>${peso(fa.metrics.avg_monthly_surplus)}</b> <span class="small">${fa.metrics.surplus_pct_of_inflow}% of inflow</span></div>
              <div><div class="muted small">DSCR now → with new loan</div><b>${fa.metrics.dscr_current ?? "—"}x → ${fa.metrics.dscr_pro_forma}x</b></div>
              <div><div class="muted small">New monthly amortization</div><b>${peso(fa.metrics.proposed_monthly_amortization)}</b></div></div>
            <ul class="small">${fa.insights.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>
            <div class="callout small"><b>Product fit:</b> ${esc(fa.product_fit.product_code)} — ${esc(fa.product_fit.reason)} <i>${esc(fa.product_fit.note)}</i></div>
            ${cashChart(fa.monthly.slice(-12))}` : '<div class="empty">Not run yet</div>'}
        </div>
      </div>
      <div class="grid g2 section">
        <div class="card"><h2>3 · Credit case <span class="muted small">Credit Case Agent</span></h2>
          <div class="btn-row">${S.agents.case ? `<button class="btn agent" data-agent="case" ${["IN_ASSESSMENT", "CREDIT_CASE_READY", "MORE_INFO_REQUESTED", "SENT_BACK"].includes(st) ? "" : "disabled"}>▶ Prepare credit case</button>` : ""}
            ${humanBtn("MSME: submit to credit officer", "submit", ["applicant", "rm"], ["CREDIT_CASE_READY", "MORE_INFO_REQUESTED", "SENT_BACK"].includes(st))}</div>
          ${cc ? `<div class="grid g2 section"><div><div class="score">${cc.readiness_score}</div><div class="muted small">${esc(cc.score_label)}</div><div class="small">Confidence ${Math.round(cc.confidence * 100)}%</div></div>
              <div>${Object.entries(cc.factor_scores).map(([k, v]) => `<div class="row-bar" style="grid-template-columns:1fr 90px 30px"><div class="small">${k.replaceAll("_", " ")}</div><div class="bar ${v < 50 ? "bad" : v < 70 ? "warn" : ""}"><span style="width:${v}%"></span></div><div class="small num">${v}</div></div>`).join("")}</div></div>
            <h3>Evidence</h3><table><tbody>${cc.evidence.map((e) => `<tr><td class="small"><b>${esc(e.item)}</b><div>${esc(e.detail)}</div><div class="muted">${esc(e.source)}</div></td><td class="num small">${Math.round(e.confidence * 100)}%</td></tr>`).join("")}</tbody></table>
            <div class="grid g2 section"><div><h3>Strengths</h3><ul class="small">${cc.strengths.map((s) => `<li>${esc(s)}</li>`).join("") || "<li>—</li>"}</ul></div><div><h3>Risks</h3><ul class="small">${cc.risks.map((s) => `<li>${esc(s)}</li>`).join("")}</ul></div></div>
            <h3>Questions for the credit officer</h3><ul class="small">${cc.review_questions.map((s) => `<li>${esc(s)}</li>`).join("") || "<li>—</li>"}</ul>
            ${cc.narrative ? `<div class="callout small"><b>Agent memo:</b> ${esc(cc.narrative)}</div>` : ""}` : '<div class="empty">Not prepared yet</div>'}
        </div>
        <div class="card"><h2>4 · Human decision</h2>
          <div class="callout gold small"><b>AI prepared the case. A named LANDBANK officer makes the decision.</b> Agents are blocked from these actions by the service itself.</div>
          <div class="kv section"><div>Assigned officer</div><div>${esc(a.assigned_officer || "—")}</div><div>Decision</div><div>${a.decision ? `${badge(a.decision)} by ${esc(a.decision_by)} — ${esc(a.decision_reason)}` : "—"}</div></div>
          <div class="btn-row section">
            ${humanBtn("Open case", "open", ["credit_officer"], st === "SUBMITTED_FOR_REVIEW", "secondary")}
            ${humanBtn("Request more info", "REQUEST_MORE_INFO", ["credit_officer"], review, "secondary")}
            ${humanBtn("Send back", "SEND_BACK", ["credit_officer"], review, "secondary")}
            ${humanBtn("Recommend decline", "RECOMMEND_DECLINE", ["credit_officer"], review, "danger")}
            ${humanBtn("Recommend approval", "RECOMMEND_APPROVAL", ["credit_officer"], review)}
            ${humanBtn("Sanction: approve", "APPROVE", ["credit_officer"], st === "RECOMMENDED_APPROVAL", "gold")}
            ${humanBtn("Loan ops: activate", "activate", ["loan_ops"], st === "APPROVED", "gold")}
          </div>
          ${!can("credit_officer", "loan_ops") ? '<div class="muted small">Switch "Acting as" to Credit Officer or Loan Operations to take these actions.</div>' : ""}
          <h3 class="section">Timeline</h3><ul class="timeline">${a.timeline.map((e) => `<li>${badge(e.actor_type)} <b>${esc(e.event_type)}</b> <span class="muted small">${esc(e.actor_name)} · ${dt(e.occurred_at)}</span></li>`).join("") || '<div class="empty">No events yet</div>'}</ul>
        </div>
      </div>`;

    const A = main();
    const agentActions = {
      consent: () => api("/consents", { method: "POST", key: agentKey("application"), body: { customer_id: a.customer_id, purpose: `Loan application ${id}`, application_id: id } }),
      fetch: () => api(`/applications/${id}/documents/fetch`, { method: "POST", key: agentKey("application") }),
      validate: async () => { const r = await api(`/applications/${id}/documents/validate`, { method: "POST", key: agentKey("application") }); toast(r.plain_english_summary); return r; },
      fa: () => api(`/applications/${id}/financial-analysis`, { method: "POST", key: agentKey("financial") }),
      case: () => api(`/applications/${id}/credit-case`, { method: "POST", key: agentKey("case"), body: {} }),
    };
    A.querySelectorAll("[data-agent]").forEach((b) => (b.onclick = () => act(agentActions[b.dataset.agent], b.dataset.agent === "validate" ? null : "Agent step done")));
    A.querySelectorAll("[data-human]").forEach((b) => (b.onclick = () => {
      const f = b.dataset.human;
      if (f === "grant") return act(() => api(`/consents/${a.consent.consent_id}/grant`, { method: "POST" }), "Consent granted");
      if (f === "submit") return act(() => api(`/applications/${id}/submit`, { method: "POST" }), "Submitted to credit officer");
      if (f === "open") return act(() => api(`/applications/${id}/open`, { method: "POST" }), "Case opened");
      if (f === "activate") return act(() => api(`/applications/${id}/activate`, { method: "POST", body: {} }), "Loan activated — monitoring started");
      modal(`<h2>${f.replaceAll("_", " ")}</h2><label>Reason (recorded in the audit trail)</label><textarea name="reason" rows="3" placeholder="e.g. Confirm export order pipeline"></textarea>`,
        (v) => act(() => api(`/applications/${id}/decision`, { method: "POST", body: { decision: f, reason: v.reason || f } }), "Decision recorded"));
    }));
    A.querySelectorAll("[data-request]").forEach((b) => (b.onclick = () => modal(`<h2>Request document (agent)</h2><label>Reason shown to the MSME</label><textarea name="reason" rows="3">Please upload the ${b.dataset.request.replaceAll("_", " ").toLowerCase()}.</textarea>`,
      (v) => act(() => api(`/applications/${id}/documents/request`, { method: "POST", key: agentKey("application"), body: { doc_type: b.dataset.request, reason: v.reason } }), "Document requested"))));
    A.querySelectorAll("[data-upload]").forEach((b) => (b.onclick = () => {
      const inp = document.createElement("input");
      inp.type = "file";
      inp.accept = "application/pdf,image/*";
      inp.onchange = () => { const fd = new FormData(); fd.append("doc_type", b.dataset.upload); fd.append("file", inp.files[0]); act(() => api(`/applications/${id}/documents/upload`, { method: "POST", form: fd }), "Uploaded"); };
      inp.click();
    }));
    A.querySelectorAll("[data-pdf]").forEach((l) => (l.onclick = async (e) => {
      e.preventDefault();
      const r = await fetch(`/api/v1/documents/${l.dataset.pdf}/file`, { headers: { "X-API-Key": S.role.key } });
      window.open(URL.createObjectURL(await r.blob()), "_blank");
    }));
  };

  views.risk = async () => {
    const [alerts, custs] = await Promise.all([api("/alerts"), api("/customers")]);
    const flagged = custs.filter((c) => c.health_status !== "HEALTHY");
    const withAlert = new Set(alerts.filter((a) => ["OPEN", "IN_PROGRESS"].includes(a.status)).map((a) => a.customer_id));
    main().innerHTML = `<div class="page-head"><div><h1>Risk &amp; early warning</h1><div class="muted">Signals for human investigation — never automatic loan actions</div></div>
      ${S.agents.portfolio ? '<button class="btn agent" id="run-mon">▶ Portfolio agent: run monitoring</button>' : ""}</div>
      <div class="grid g2">
        <div class="card"><h2>Relationships needing attention (${flagged.length})</h2><table><tbody>
          ${flagged.map((c) => `<tr><td><a href="#/customer/${esc(c.customer_id)}"><b>${esc(c.business_name)}</b></a><div class="muted small">${esc(c.sector)} · ${peso(c.total_outstanding)} · DPD ${c.max_days_past_due ?? 0}</div></td><td>${badge(c.health_status)}</td>
            <td>${withAlert.has(c.customer_id) ? '<span class="small muted">alert open</span>' : S.agents.portfolio ? `<button class="btn agent" data-alert="${esc(c.customer_id)}" data-sev="${c.health_status === "HIGH_ATTENTION" ? "HIGH" : "WATCH"}">▶ Raise alert</button>` : ""}</td></tr>`).join("")}
        </tbody></table></div>
        <div class="card"><h2>Alerts</h2>${alerts.map((a) => `<div class="signal ${a.severity === "HIGH" ? "HIGH" : ""}"><b>${esc(a.alert_id)} · ${esc(a.business_name)}</b> ${badge(a.severity)} ${badge(a.status)}
            <div>${esc(a.summary)}</div><div class="small"><b>Recommended:</b> ${esc(a.recommended_action)}</div>
            <div class="small muted">${(a.signals || []).map((s) => esc(s.rule_code + ":" + s.level)).join(" · ")} · by ${esc(a.created_by)}</div>
            ${can("rm", "credit_officer") && ["OPEN", "IN_PROGRESS"].includes(a.status) ? `<div class="btn-row" style="margin-top:6px"><button class="btn secondary" data-res="${esc(a.alert_id)}" data-st="RESOLVED">Resolve</button><button class="btn danger" data-res="${esc(a.alert_id)}" data-st="ESCALATED">Escalate</button></div>` : ""}</div>`).join("") || '<div class="empty">No alerts</div>'}</div>
      </div>`;
    const b = $("#run-mon");
    if (b) b.onclick = () => act(async () => { const r = await api("/portfolio/monitoring-run", { method: "POST", key: agentKey("portfolio") }); toast(`${r.customers_checked} checked · ${r.needs_attention.length} need attention · ${r.health_changes.length} changed`); });
    main().querySelectorAll("[data-alert]").forEach((btn) => (btn.onclick = () => act(async () => {
      const cid = btn.dataset.alert;
      const sig = await api(`/customers/${cid}/signals`, { key: agentKey("portfolio") });
      const summary = sig.signals.map((s) => s.explanation).join(" ");
      const al = await api("/alerts", { method: "POST", key: agentKey("portfolio"), body: { customer_id: cid, severity: btn.dataset.sev, summary, recommended_action: "RM outreach within 2 business days. No automatic change to loan terms.", signals: sig.signals } });
      await api("/rm-tasks", { method: "POST", key: agentKey("growth"), body: { customer_id: cid, task_type: "RISK_OUTREACH", title: "Proactive risk outreach", details: summary, priority: btn.dataset.sev === "HIGH" ? "HIGH" : "MEDIUM", related_alert_id: al.alert_id } });
    }, "Alert raised and RM task created")));
    main().querySelectorAll("[data-res]").forEach((btn) => (btn.onclick = () => modal(`<h2>${btn.dataset.st} ${btn.dataset.res}</h2><label>Note</label><textarea name="note" rows="3"></textarea>`,
      (v) => act(() => api(`/alerts/${btn.dataset.res}`, { method: "PATCH", body: { status: btn.dataset.st, note: v.note } }), "Alert updated"))));
  };

  views.rm = async () => {
    const q = await api("/rm/work-queue");
    main().innerHTML = `<div class="page-head"><div><h1>RM work queue</h1><div class="muted">Prioritised by urgency · every item has a reason</div></div></div>
      <div class="grid g2">
        <div class="card"><h2>Tasks (${q.open_tasks.length})</h2>${q.open_tasks.map((t) => `<div class="callout" style="margin-bottom:8px">${badge(t.priority)} ${badge(t.task_type)} <b>${esc(t.title)}</b> — <a href="#/customer/${esc(t.customer_id)}">${esc(t.business_name)}</a> ${badge(t.health_status)}
            <div class="small">${esc(t.details)}</div><div class="small muted">RM ${esc(t.rm_name)} · due ${d10(t.due_date)} · created by ${esc(t.created_by)}</div>
            ${can("rm") ? `<div class="btn-row" style="margin-top:6px"><button class="btn secondary" data-task="${esc(t.task_id)}" data-st="IN_PROGRESS">Start</button><button class="btn" data-task="${esc(t.task_id)}" data-st="DONE">Mark done</button></div>` : ""}</div>`).join("") || '<div class="empty">No open tasks</div>'}</div>
        <div class="card"><h2>Leads (${q.open_leads.length})</h2>${q.open_leads.map((l) => `<div class="callout gold" style="margin-bottom:8px"><b>${esc(l.product_name)}</b> — <a href="#/customer/${esc(l.customer_id)}">${esc(l.business_name)}</a> ${badge(l.status)}
            <div class="small">${esc(l.reason)}</div><div class="small muted">RM ${esc(l.rm_name)} · by ${esc(l.created_by)}</div>
            ${can("rm") ? `<div class="btn-row" style="margin-top:6px"><button class="btn secondary" data-lead="${esc(l.lead_id)}" data-st="CONTACTED">Contacted</button><button class="btn" data-lead="${esc(l.lead_id)}" data-st="WON">Won</button><button class="btn danger" data-lead="${esc(l.lead_id)}" data-st="LOST">Lost</button></div>` : ""}</div>`).join("") || '<div class="empty">No open leads</div>'}</div>
      </div>
      ${can("rm") ? "" : '<div class="muted small section">Switch "Acting as" to Relationship Manager to update tasks and leads.</div>'}`;
    main().querySelectorAll("[data-task]").forEach((b) => (b.onclick = () => modal(`<h2>${b.dataset.st.replace("_", " ")}</h2><label>Outcome note</label><textarea name="note" rows="3"></textarea>`,
      (v) => act(() => api(`/rm-tasks/${b.dataset.task}`, { method: "PATCH", body: { status: b.dataset.st, note: v.note } }), "Task updated"))));
    main().querySelectorAll("[data-lead]").forEach((b) => (b.onclick = () => act(() => api(`/leads/${b.dataset.lead}`, { method: "PATCH", body: { status: b.dataset.st } }), "Lead updated")));
  };

  views.opportunities = async () => {
    const o = await api("/opportunities", { key: agentKey("growth") || S.role.key });
    main().innerHTML = `<div class="page-head"><div><h1>Growth opportunities</h1><div class="muted">${o.count} evidence-backed opportunities · ${peso(o.total_estimated_value)} potential · healthy customers only</div></div></div>
      <div class="card table-wrap"><table><thead><tr><th>Customer</th><th>Recommendation</th><th class="num">Confidence</th><th class="num">Potential</th><th>Why</th><th></th></tr></thead><tbody>
      ${o.opportunities.map((x) => `<tr><td><a href="#/customer/${esc(x.customer_id)}"><b>${esc(x.business_name)}</b></a></td><td>${esc(x.product_name)}</td><td class="num">${Math.round(x.confidence * 100)}%</td><td class="num">${peso(x.estimated_value)}<div class="muted small">${esc(x.value_basis)}</div></td><td class="small">${x.reasons.map(esc).join("<br>")}</td>
        <td>${can("rm") || S.agents.growth ? `<button class="btn secondary" data-c="${esc(x.customer_id)}" data-p="${esc(x.product_code)}" data-o="${esc(x.opportunity_id)}">Create lead</button>` : ""}</td></tr>`).join("")}
      </tbody></table></div>`;
    main().querySelectorAll("[data-c]").forEach((b) => (b.onclick = () => act(() => api("/leads", { method: "POST", key: can("rm") ? S.role.key : agentKey("growth"), body: { customer_id: b.dataset.c, product_code: b.dataset.p, opportunity_id: b.dataset.o, reason: "Evidence-backed opportunity" } }), "Lead created")));
  };

  views.events = async () => {
    const [ev, au] = await Promise.all([api("/events?limit=150"), api("/audit?limit=150")]);
    main().innerHTML = `<div class="page-head"><div><h1>Events &amp; audit trail</h1><div class="muted">Every state change is an event · every API call is audited</div></div><button class="btn secondary" id="refresh">Refresh</button></div>
      <div class="grid g2">
        <div class="card table-wrap"><h2>Events</h2><table><thead><tr><th>#</th><th>Event</th><th>Actor</th><th>Ref</th><th>When</th></tr></thead><tbody>
          ${ev.map((e) => `<tr><td class="small">${e.event_id}</td><td><b class="small">${esc(e.event_type)}</b></td><td>${badge(e.actor_type)}<div class="small muted">${esc(e.actor_name)}</div></td><td class="small">${esc(e.application_id || e.customer_id || "")}</td><td class="small">${dt(e.occurred_at)}</td></tr>`).join("")}
        </tbody></table></div>
        <div class="card table-wrap"><h2>API audit</h2><table><thead><tr><th>Actor</th><th>Tool</th><th>Result</th><th>When</th></tr></thead><tbody>
          ${au.map((a) => `<tr><td>${badge(a.actor_type)}<div class="small muted">${esc(a.actor_name)}</div></td><td class="mono">${esc(a.tool_name || a.path)}<div class="muted small">${esc(a.method)} ${esc(a.path)}</div></td><td>${a.status_code >= 400 ? `<span class="badge b-HIGH">${a.status_code}</span>` : `<span class="badge b-HEALTHY">${a.status_code}</span>`}</td><td class="small">${dt(a.at)}</td></tr>`).join("")}
        </tbody></table></div>
      </div>`;
    $("#refresh").onclick = () => route();
  };

  views.apis = async () => {
    let cat = [];
    try { cat = await (await fetch("/static/api_catalog.json")).json(); } catch (e) { /* catalog missing */ }
    const groups = {};
    cat.forEach((t) => (groups[t.agent] = groups[t.agent] || []).push(t));
    main().innerHTML = `<div class="page-head"><div><h1>APIs for AgenticOrg</h1><div class="muted">Register one custom connector (base URL + X-API-Key). Tools = operationIds below. Full spec: <a href="/docs" target="_blank">/docs</a> · <a href="/openapi.json" target="_blank">/openapi.json</a></div></div></div>
      <div class="callout gold">Tools marked <b>HUMAN ONLY</b> must never be given to an agent. The service also blocks them for agent keys (HTTP 403).</div>
      ${Object.entries(groups).map(([agent, tools]) => `<div class="card section table-wrap"><h2>${esc(agent)}</h2><table><thead><tr><th>Tool (operationId)</th><th>Method &amp; path</th><th>Grantex scope</th><th>What it does</th></tr></thead><tbody>
        ${tools.map((t) => `<tr><td class="mono"><b>${esc(t.tool)}</b></td><td class="mono">${esc(t.method)} ${esc(t.path)}</td><td><span class="badge ${t.permission === "HUMAN ONLY" ? "b-HIGH" : t.permission === "WRITE" ? "b-MEDIUM" : t.permission === "ADMIN" ? "b-SYSTEM" : "b-LOW"}">${esc(t.permission)}</span></td><td class="small">${esc(t.purpose)}</td></tr>`).join("")}
      </tbody></table></div>`).join("") || '<div class="empty">api_catalog.json not found — run tools/export_api_catalog.py</div>'}`;
  };

  // ------------------------------------------------------------------ router
  async function route() {
    const h = location.hash || "#/dashboard";
    const [path, qs] = h.slice(2).split("?");
    const [view, id] = path.split("/");
    document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === view || (view === "customer" && a.dataset.view === "customers") || (view === "application" && a.dataset.view === "applications")));
    main().innerHTML = '<div class="loading">Loading…</div>';
    try {
      const fn = views[view] || views.dashboard;
      await fn(id || Object.fromEntries(new URLSearchParams(qs || "")));
    } catch (e) {
      main().innerHTML = `<div class="card"><h2>Something went wrong</h2><div class="mono">${esc(e.message)}</div></div>`;
    }
  }

  async function init() {
    S.cfg = await (await fetch("/ui-config")).json();
    if (!S.cfg.demo_mode) { main().innerHTML = '<div class="card">Demo mode is off. Use the API with your own keys.</div>'; return; }
    const agentMap = { "MSME Application Agent": "application", "Financial Analysis Agent": "financial", "Credit Case Agent": "case", "Portfolio Intelligence Agent": "portfolio", "RM & Growth Agent": "growth" };
    (S.cfg.agents || []).forEach((a) => { if (agentMap[a.actor_name]) S.agents[agentMap[a.actor_name]] = a.key; });
    const sel = $("#role");
    sel.innerHTML = S.cfg.roles.map((r, i) => `<option value="${i}">${esc(r.actor_name)}</option>`).join("");
    let saved = null;
    try { saved = localStorage.getItem("lb-role"); } catch (e) { /* storage blocked */ }
    const adminIdx = Math.max(0, S.cfg.roles.findIndex((r) => r.role === "admin"));
    const n = saved === null ? -1 : Number(saved);
    sel.value = String(n >= 0 && n < S.cfg.roles.length ? n : adminIdx);
    S.role = S.cfg.roles[Number(sel.value)];
    sel.onchange = () => { S.role = S.cfg.roles[Number(sel.value)]; try { localStorage.setItem("lb-role", sel.value); } catch (e) { /* ignore */ } route(); };
    $("#asof").textContent = `Synthetic data · as of ${S.cfg.as_of}`;
    window.addEventListener("hashchange", route);
    route();
  }
  init();
})();
