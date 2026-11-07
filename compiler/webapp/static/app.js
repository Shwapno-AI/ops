"use strict";
(function () {
  const $ = (id) => document.getElementById(id);
  const state = { inputs: [], template: null, status: null, job: null, poll: null, uploading: false };
  const STAGES = { reading: "Reading your files", planning: "Qwen is planning the compile", writing: "Writing the Excel file", checking: "Checking the numbers" };
  const STAGE_ORDER = ["reading", "planning", "writing", "checking"];
  const INPUT_TYPES = [".xlsx", ".xlsm", ".xlsb", ".xls", ".ods", ".csv", ".tsv", ".txt"];
  const TEMPLATE_TYPES = [".xlsx", ".xlsm", ".xlsb", ".xls", ".ods"];
  const RESULT_CHIP = {
    ok: ["good", "Checks matched"],
    warn: ["warn", "Please check"],
    fail: ["bad", "Check failed"],
  };

  /** Builds elements with textContent only, so file contents can never become page code. */
  function el(tag, props, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props || {})) {
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key === "style") node.style.cssText = value; // allowed by the page's security policy, unlike a style attribute
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else if (value !== undefined && value !== null && value !== false) node.setAttribute(key, value === true ? "" : value);
    }
    for (const child of children.flat()) if (child) node.append(child);
    return node;
  }

  const chip = (kind, text) => el("span", { class: "chip " + kind, text });

  function formatSize(bytes) {
    if (bytes >= 1024 ** 3) return (bytes / 1024 ** 3).toFixed(1) + " GB";
    if (bytes >= 1024 ** 2) return (bytes / 1024 ** 2).toFixed(1) + " MB";
    return Math.max(1, Math.round(bytes / 1024)) + " KB";
  }

  function formatWhen(iso) {
    if (!iso) return "—";
    const date = new Date(iso);
    return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) + ", " +
      date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  }

  async function api(path, options) {
    const response = await fetch(path, options);
    let body = null;
    try { body = await response.json(); } catch (error) { /* a proxy error page is not JSON */ }
    if (response.status === 401) { location.href = "/login"; throw new Error("Please sign in again."); }
    if (!response.ok) {
      const failure = new Error((body && body.error) || "The server did not respond properly (" + response.status + "). Please try again.");
      failure.status = response.status;
      failure.body = body;
      throw failure;
    }
    return body;
  }

  const postJson = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

  function showError(message) {
    $("form-error").textContent = message || "";
    $("form-error").hidden = !message;
  }

  /* ---------- theme ---------- */
  function paintThemeButton() {
    const light = document.documentElement.getAttribute("data-theme") === "light";
    $("theme-toggle").textContent = light ? "Dark theme" : "Light theme";
  }
  $("theme-toggle").addEventListener("click", () => {
    const light = document.documentElement.getAttribute("data-theme") === "light";
    if (light) document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", "light");
    try { localStorage.setItem("excel-compiler-theme", light ? "dark" : "light"); } catch (error) { /* keep working without storage */ }
    paintThemeButton();
  });

  /* ---------- choosing files ---------- */
  const extension = (name) => { const dot = name.lastIndexOf("."); return dot < 0 ? "" : name.slice(dot).toLowerCase(); };

  function addInputs(files) {
    const skipped = [];
    for (const file of files) {
      if (file.name.startsWith("~$")) continue;
      if (!INPUT_TYPES.includes(extension(file.name))) { skipped.push(file.name); continue; }
      state.inputs = state.inputs.filter((f) => f.name !== file.name);
      state.inputs.push(file);
    }
    showError(skipped.length ? "Skipped " + skipped.join(", ") + ": only Excel and CSV files work." : "");
    paintFiles();
  }

  function setTemplate(files) {
    const file = files[0];
    if (!file) return;
    if (!TEMPLATE_TYPES.includes(extension(file.name))) {
      showError(file.name + " cannot be a template: use an Excel file.");
      return;
    }
    showError(files.length > 1 ? "A template is one file, so only " + file.name + " was used." : "");
    state.template = file;
    paintFiles();
  }

  function fileRow(file, onRemove) {
    return el("li", null,
      el("span", { class: "file-name", text: file.name }),
      el("span", { class: "file-size", text: formatSize(file.size) }),
      el("button", { class: "remove", type: "button", "aria-label": "Remove " + file.name, text: "×", onclick: onRemove }));
  }

  function paintFiles() {
    $("input-list").replaceChildren(...state.inputs.map((file) => fileRow(file, () => {
      state.inputs = state.inputs.filter((f) => f !== file);
      paintFiles();
    })));
    $("template-list").replaceChildren(...(state.template ? [fileRow(state.template, () => { state.template = null; paintFiles(); })] : []));
  }

  function wireDrop(zone, input, handler) {
    input.addEventListener("change", () => { handler([...input.files]); input.value = ""; });
    for (const name of ["dragenter", "dragover"]) zone.addEventListener(name, (event) => { event.preventDefault(); zone.classList.add("over"); });
    for (const name of ["dragleave", "drop"]) zone.addEventListener(name, (event) => { event.preventDefault(); zone.classList.remove("over"); });
    zone.addEventListener("drop", (event) => handler([...event.dataTransfer.files]));
  }
  wireDrop($("input-drop"), $("input-files"), addInputs);
  wireDrop($("template-drop"), $("template-file"), setTemplate);
  // A file dropped just outside a box must not navigate away from the page.
  for (const name of ["dragover", "drop"]) window.addEventListener(name, (event) => event.preventDefault());
  window.addEventListener("beforeunload", (event) => { if (state.uploading) event.preventDefault(); });

  /* ---------- upload ---------- */
  async function sendFile(jobId, kind, file, onProgress) {
    const size = state.status ? state.status.chunk_bytes : 8 * 1024 * 1024;
    let offset = 0;
    let failures = 0;
    while (offset < file.size || (file.size === 0 && offset === 0)) {
      const url = "/api/jobs/" + jobId + "/chunk?" + new URLSearchParams({ kind, name: file.name, offset });
      try {
        const body = await api(url, { method: "PUT", headers: { "Content-Type": "application/octet-stream" }, body: file.slice(offset, offset + size) });
        offset = body.size;
        failures = 0;
        onProgress(offset);
        if (file.size === 0) break;
      } catch (error) {
        if (error.status === 409 && error.body && error.body.error === "resync") { offset = error.body.size; continue; }
        const permanent = error.status && error.status < 500 && error.status !== 408 && error.status !== 429;
        if (permanent || ++failures > 5) throw error;
        await new Promise((resolve) => setTimeout(resolve, 1500 * failures));
      }
    }
  }

  async function compile() {
    showError("");
    if (!state.inputs.length) { showError("Add at least one source file."); return; }
    const uploads = state.inputs.map((file) => ({ kind: "input", file }));
    if (state.template) uploads.push({ kind: "template", file: state.template });
    const total = uploads.reduce((sum, item) => sum + item.file.size, 0);
    const limit = state.status ? state.status.max_upload_mb * 1024 * 1024 : Infinity;
    if (total > limit) { showError("These files are " + formatSize(total) + ", over the " + formatSize(limit) + " limit."); return; }

    state.uploading = true;
    $("compile").disabled = true;
    stopPolling();
    openJobPanel("Uploading");
    let sent = 0;
    try {
      const job = await api("/api/jobs", { method: "POST" });
      for (const [index, item] of uploads.entries()) {
        const before = sent;
        paintUpload(index + 1, uploads.length, sent, total, item.file.name);
        await sendFile(job.id, item.kind, item.file, (done) => {
          sent = before + done;
          paintUpload(index + 1, uploads.length, sent, total, item.file.name);
        });
        sent = before + item.file.size;
      }
      const started = await postJson("/api/jobs/" + job.id + "/start", {
        instruction: $("instruction").value,
        files: uploads.map((item) => ({ kind: item.kind, name: item.file.name, size: item.file.size })),
      });
      state.inputs = [];
      state.template = null;
      $("instruction").value = "";
      paintFiles();
      follow(started);
    } catch (error) {
      paintProblem("The upload did not finish", error.message);
    } finally {
      state.uploading = false;
      $("compile").disabled = false;
    }
  }

  /* ---------- following a job ---------- */
  function openJobPanel(title) {
    $("job-panel").hidden = false;
    $("job-title").textContent = title;
    $("job-subtitle").textContent = "";
    $("cancel-job").hidden = true;
  }

  function windowBox(label, right, percent, note) {
    return el("div", { class: "window" },
      el("div", { class: "window-top" }, el("span", { text: label }), el("span", { text: right })),
      el("div", { class: "track", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(Math.round(percent)), "aria-label": label },
        el("div", { style: "width:" + Math.max(percent, 2) + "%" })),
      note ? el("p", { text: note }) : null);
  }

  function paintUpload(index, count, sent, total, name) {
    const percent = total ? (100 * sent) / total : 100;
    $("job-body").replaceChildren(windowBox(
      "Uploading file " + index + " of " + count,
      formatSize(sent) + " of " + formatSize(total),
      percent,
      name + ". Keep this page open until the upload finishes."));
  }

  function paintProblem(title, message) {
    $("job-title").textContent = title;
    $("job-subtitle").textContent = "";
    $("job-body").replaceChildren(el("ul", { class: "items" }, el("li", null, chip("bad", "Failed"), el("div", { text: message }))));
  }

  function stopPolling() {
    if (state.poll) clearTimeout(state.poll);
    state.poll = null;
  }

  function follow(job) {
    state.job = job;
    try { history.replaceState(null, "", "#job=" + job.id); } catch (error) { /* the page still works without it */ }
    paintJob(job);
    stopPolling();
    if (job.status === "queued" || job.status === "running") {
      state.poll = setTimeout(async () => {
        try {
          follow(await api("/api/jobs/" + job.id));
        } catch (error) {
          if (error.status === 404) { paintProblem("Result not found", error.message); return; }
          state.poll = setTimeout(() => follow(state.job), 4000); // a brief network drop should not lose the job
        }
      }, 1500);
    } else {
      loadHistory();
    }
  }

  function paintJob(job) {
    openJobPanel("Compile");
    $("job-subtitle").textContent = describeFiles(job);
    const body = $("job-body");
    $("cancel-job").hidden = !(job.status === "queued" || job.status === "running");
    if (job.status === "queued") {
      const ahead = job.ahead ? job.ahead + (job.ahead === 1 ? " job is" : " jobs are") + " ahead of this one." : "Starting now.";
      body.replaceChildren(windowBox("Waiting to start", "", 2, ahead + " You can close this page; the result will be under Recent results."));
    } else if (job.status === "running") {
      const step = Math.max(0, STAGE_ORDER.indexOf(job.stage)) + 1;
      body.replaceChildren(windowBox(STAGES[job.stage] || "Working", "Step " + step + " of " + STAGE_ORDER.length, (100 * step) / (STAGE_ORDER.length + 1),
        "You can close this page; the result will be under Recent results."));
    } else if (job.status === "failed") {
      paintProblem("Compile failed", job.error || "Something went wrong.");
      body.append(runAgain(job));
    } else if (job.status === "cancelled") {
      body.replaceChildren(el("ul", { class: "items" }, el("li", null, chip("idle", "Cancelled"), el("div", { text: "This compile was stopped." }))), runAgain(job));
    } else if (job.report) {
      paintReport(job);
    }
  }

  function describeFiles(job) {
    const count = job.files.length;
    const parts = [count + (count === 1 ? " file" : " files")];
    if (job.template) parts.push("template: " + job.template.name);
    if (job.instruction) parts.push("with an instruction");
    return parts.join(" · ");
  }

  function downloadUrl(job, name) {
    return "/api/jobs/" + job.id + "/download/" + encodeURIComponent(name);
  }

  function checkList(items, kind, label) {
    return items.map((item) => el("li", null, chip(kind, label), el("div", null, el("b", { text: item.name + ": " }), item.detail)));
  }

  function table(headers, rows) {
    return el("div", { class: "table-wrap" }, el("table", null,
      el("thead", null, el("tr", null, headers.map((h) => el("th", { class: h.number ? "number" : "", scope: "col", text: h.label })))),
      el("tbody", null, rows.map((row) => el("tr", null, row.map((cell, i) => el("td", { class: headers[i].number ? "number" : "", text: cell })))))));
  }

  function paintReport(job) {
    const report = job.report;
    const [kind, label] = RESULT_CHIP[report.status];
    const parts = [
      el("div", { class: "result-head" }, chip(kind, label), el("strong", { text: report.status_text })),
      el("div", { class: "downloads" },
        el("a", { class: "btn primary", href: downloadUrl(job, report.output), text: "Download Excel" }),
        el("a", { class: "btn", href: downloadUrl(job, "report.md"), text: "Download report" })),
      el("p", { class: "output-name", text: report.output }),
    ];
    if (report.summary) parts.push(el("h3", { text: "What was done" }), el("p", { text: report.summary }));
    if (report.results && report.results.length) {
      parts.push(el("ul", { class: "plain" }, report.results.map((r) => el("li", { text: r.name + ": " + r.rows.toLocaleString("en-US") + " rows" }))));
    }
    if (report.failures.length || report.warnings.length) {
      parts.push(el("h3", { text: "Please check" }), el("ul", { class: "items" }, checkList(report.failures, "bad", "Failed"), checkList(report.warnings, "warn", "Check")));
    }
    if (report.assumptions.length) {
      parts.push(el("h3", { text: "Decisions made" }), el("ul", { class: "plain" }, report.assumptions.map((text) => el("li", { text }))));
    }
    if (report.literals.length) {
      parts.push(el("h3", { text: "Values typed in directly" }), el("ul", { class: "plain" }, report.literals.map((text) => el("li", { text }))));
    }
    const files = el("details", null, el("summary", { text: "Files read (" + report.tables.length + ")" }),
      table([{ label: "File" }, { label: "Sheet" }, { label: "Data rows", number: true }, { label: "Removed" }, { label: "Notes" }],
        report.tables.map((t) => [t.file, t.sheet, t.rows.toLocaleString("en-US"), t.removed || "—", t.notes.join("; ") || "—"])));
    if (report.hidden_skipped) files.append(el("p", { class: "muted", text: "Hidden sheets skipped: " + report.hidden_skipped + "." }));
    if (report.empty_sheets.length) files.append(el("p", { class: "muted", text: "Empty sheets: " + report.empty_sheets.join(", ") + "." }));
    if (report.ignored.length) files.append(el("p", { class: "muted", text: "Not spreadsheets, so ignored: " + report.ignored.join(", ") + "." }));
    parts.push(files);
    if (report.passed.length) {
      parts.push(el("details", null, el("summary", { text: "Checks that matched (" + report.passed.length + ")" }),
        el("ul", { class: "plain" }, report.passed.map((c) => el("li", { text: c.name + ": " + c.detail })))));
    }
    parts.push(el("details", null, el("summary", { text: "Rows at each step" }),
      table([{ label: "Table" }, { label: "Step" }, { label: "Before", number: true }, { label: "After", number: true }],
        report.steps.map((s) => [s.frame, s.step, s.rows_in === null ? "—" : s.rows_in.toLocaleString("en-US"), s.rows_out.toLocaleString("en-US")]))));
    const ai = report.ai;
    parts.push(el("p", { class: "muted ai-note", text: ai.used
      ? "Planned by " + ai.model + " using " + ai.tokens.toLocaleString("en-US") + " tokens. Qwen saw column names and " + ai.sample_rows + " sample rows per table, not the full data."
      : "Qwen was not used for this result." }));
    parts.push(runAgain(job));
    $("job-body").replaceChildren(...parts);
  }

  function runAgain(job) {
    const box = el("textarea", { class: "input", id: "again-instruction", rows: "2", maxlength: "4000", placeholder: "What should change? Bangla or English." });
    box.value = job.instruction || "";
    const status = el("p", { class: "form-error", role: "alert", hidden: true });
    return el("div", { class: "again" },
      el("label", { class: "field-label", for: "again-instruction", text: "Not quite right? Change the instruction and run the same files again." }),
      box, status,
      el("div", { class: "actions" }, el("button", { class: "btn", type: "button", text: "Run again", onclick: async () => {
        try {
          follow(await postJson("/api/jobs/" + job.id + "/rerun", { instruction: box.value }));
          $("job-panel").scrollIntoView();
        } catch (error) {
          status.textContent = error.message;
          status.hidden = false;
        }
      } })));
  }

  $("cancel-job").addEventListener("click", async () => {
    if (!state.job) return;
    try { follow(await postJson("/api/jobs/" + state.job.id + "/cancel")); } catch (error) { showError(error.message); }
  });

  /* ---------- history ---------- */
  function historyChip(job) {
    if (job.status === "done") return chip(...RESULT_CHIP[job.result || "ok"]);
    if (job.status === "failed") return chip("bad", "Failed");
    if (job.status === "cancelled") return chip("idle", "Cancelled");
    return chip("info", job.status === "queued" ? "Waiting" : "Running");
  }

  async function loadHistory() {
    let jobs;
    try { jobs = (await api("/api/jobs")).jobs; } catch (error) { return; }
    const holder = $("history");
    if (!jobs.length) {
      holder.replaceChildren(el("p", { class: "empty", text: "Nothing yet. Your compiled files will appear here." }));
      return;
    }
    const rows = jobs.map((job) => {
      const more = job.file_count > 1 ? " and " + (job.file_count - 1) + " more" : "";
      const actions = el("div", { class: "row-actions" },
        el("button", { class: "link", type: "button", text: "Open", onclick: async () => {
          try { follow(await api("/api/jobs/" + job.id)); $("job-panel").scrollIntoView(); } catch (error) { showError(error.message); }
        } }));
      if (job.output) {
        actions.append(el("a", { class: "link", href: "/api/jobs/" + job.id + "/download/" + encodeURIComponent(job.output), text: "Download" }));
      }
      if (job.status !== "queued" && job.status !== "running") {
        actions.append(el("button", { class: "link", type: "button", text: "Delete", onclick: async () => {
          if (!confirm("Delete this result and its files?")) return;
          try {
            await api("/api/jobs/" + job.id, { method: "DELETE" });
            if (state.job && state.job.id === job.id) { $("job-panel").hidden = true; state.job = null; try { history.replaceState(null, "", location.pathname); } catch (error) { /* harmless */ } }
            loadHistory();
          } catch (error) { showError(error.message); }
        } }));
      }
      return el("tr", null,
        el("td", null, el("div", { class: "cell-primary", text: (job.first_file || "—") + more }),
          job.template ? el("div", { class: "cell-secondary", text: "Template: " + job.template }) : null),
        el("td", { text: formatWhen(job.created) }),
        el("td", null, historyChip(job)),
        el("td", null, actions));
    });
    holder.replaceChildren(el("table", null,
      el("thead", null, el("tr", null, ["Files", "When", "Result", ""].map((label) => el("th", { scope: "col", text: label })))),
      el("tbody", null, rows)));
  }

  /* ---------- status, sample, test ---------- */
  async function loadStatus() {
    try { state.status = await api("/api/status"); } catch (error) { return; }
    const status = state.status;
    const pill = $("qwen-pill");
    pill.className = "chip " + (status.qwen_ready ? "good" : "warn");
    pill.textContent = status.qwen_ready ? "Qwen ready: " + status.model : "Qwen not set up";
    $("history-note").textContent = "Files are deleted after " + status.retention_days + " days.";
    const notes = [];
    if (!status.qwen_ready) {
      notes.push(el("div", { class: "notice" }, chip("warn", "Setup"),
        el("p", { text: "Qwen is not connected yet, so files are only joined by matching column names and instructions will not work. In Coolify, add QWEN_API_KEY under Environment Variables, then redeploy." })));
    }
    if (!status.storage_kept) {
      notes.push(el("div", { class: "notice" }, chip("warn", "Setup"),
        el("p", { text: "Results will be lost on each redeploy. To keep them, add persistent storage in Coolify with the path /data." })));
    }
    if (status.free_gb < 2) {
      notes.push(el("div", { class: "notice" }, chip("warn", "Disk"), el("p", { text: "The server has only " + status.free_gb + " GB free. Large compiles may fail." })));
    }
    $("notices").replaceChildren(...notes);
  }

  $("compile").addEventListener("click", compile);

  $("try-sample").addEventListener("click", async () => {
    showError("");
    try {
      follow(await postJson("/api/sample", { template: true }));
      $("job-panel").scrollIntoView();
    } catch (error) { showError(error.message); }
  });

  $("test-qwen").addEventListener("click", async () => {
    const out = $("test-result");
    out.textContent = "Testing…";
    try {
      const result = await postJson("/api/qwen-test");
      out.textContent = result.ok ? "Connected to " + result.model + " in " + result.seconds + " seconds." : result.error;
    } catch (error) { out.textContent = error.message; }
  });

  /* ---------- start ---------- */
  paintThemeButton();
  loadStatus();
  loadHistory();
  const opened = /^#job=([0-9a-f]{32})$/.exec(location.hash);
  if (opened) api("/api/jobs/" + opened[1]).then(follow).catch(() => {});
})();
