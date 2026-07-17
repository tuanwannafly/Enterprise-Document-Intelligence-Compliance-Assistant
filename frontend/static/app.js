/* --------------------------------------------------------------------------
 * Enterprise Document Intelligence & Compliance Assistant - frontend logic
 * --------------------------------------------------------------------------
 * Dependency-free vanilla JS that drives the four panels. All requests carry
 * the bearer token configured in the topbar and the X-Tenant-Id header.
 * -------------------------------------------------------------------------- */

const API_BASE = "/api/v1";

// ---- state ------------------------------------------------------------------
const state = {
    token: localStorage.getItem("edi.token") || "",
    tenantId: localStorage.getItem("edi.tenant") || "acme",
};

// ---- helpers ----------------------------------------------------------------
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

function setStatus(text, level = "") {
    const el = $("#upload-status");
    if (!el) return;
    el.textContent = text || "";
    el.classList.remove("is-success", "is-error", "is-warn");
    if (level) el.classList.add("is-" + level);
}

function escapeHtml(s) {
    return String(s || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

async function api(path, options = {}) {
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
    headers["X-Tenant-Id"] = state.tenantId;
    const resp = await fetch(API_BASE + path, { ...options, headers });
    if (!resp.ok) {
        let detail = resp.statusText;
        try {
            const body = await resp.json();
            detail = body.detail || JSON.stringify(body);
        } catch (_) { /* swallow */ }
        throw new Error(`${resp.status} ${detail}`);
    }
    if (resp.status === 204) return null;
    const ct = resp.headers.get("content-type") || "";
    return ct.includes("application/json") ? resp.json() : resp.text();
}

// ---- tabs -------------------------------------------------------------------
function showTab(name) {
    $$(".tab").forEach((tab) => {
        const active = tab.dataset.tab === name;
        tab.classList.toggle("is-active", active);
        tab.setAttribute("aria-selected", String(active));
    });
    $$(".panel").forEach((panel) => {
        panel.classList.toggle("is-active", panel.id === `tab-${name}`);
    });
}

$$(".tab").forEach((tab) => {
    tab.addEventListener("click", () => showTab(tab.dataset.tab));
});

// ---- credentials ------------------------------------------------------------
function applyCredentials() {
    state.token = $("#auth-token").value.trim() || "dev-only-do-not-use-in-prod";
    state.tenantId = $("#tenant-id").value.trim() || "acme";
    localStorage.setItem("edi.token", state.token);
    localStorage.setItem("edi.tenant", state.tenantId);
    setStatus("Credentials applied. Try the Chat tab.", "is-success");
    ping();
}

$("#save-credentials").addEventListener("click", applyCredentials);
$("#auth-token").value = state.token;
$("#tenant-id").value = state.tenantId;

// ---- upload -----------------------------------------------------------------
$("#upload-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const title = $("#title").value.trim();
    const fileInput = $("#file");
    if (!fileInput.files || !fileInput.files[0]) {
        setStatus("Select a file first.", "is-warn");
        return;
    }
    const file = fileInput.files[0];
    const form = new FormData();
    form.append("file", file);
    form.append("title", title || file.name);
    setStatus("Uploading and ingesting...");
    try {
        const headers = {};
        if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
        headers["X-Tenant-Id"] = state.tenantId;
        const resp = await fetch(API_BASE + "/documents/upload", {
            method: "POST",
            headers,
            body: form,
        });
        if (!resp.ok) {
            const err = await resp.text();
            throw new Error(`${resp.status} ${err}`);
        }
        const body = await resp.json();
        setStatus(`Ingested ${body.document_id} (${body.status})`, "is-success");
        fileInput.value = "";
    } catch (err) {
        setStatus(`Upload failed: ${err.message}`, "is-error");
    }
});

// ---- chat -------------------------------------------------------------------
const messagesEl = $("#messages");
function appendMessage(role, text, citations = []) {
    const div = document.createElement("div");
    div.className = `message ${role}`;
    const body = document.createElement("div");
    body.className = "body";
    body.textContent = text;
    div.appendChild(body);
    if (citations.length) {
        const meta = document.createElement("div");
        meta.className = "meta";
        meta.textContent = "Sources:";
        div.appendChild(meta);
        const cits = document.createElement("div");
        cits.className = "citations";
        citations.forEach((c, i) => {
            const pill = document.createElement("span");
            pill.className = "citation";
            pill.textContent = `[${i + 1}] ${c.document_title || c.document_id}`;
            pill.title = c.snippet || "";
            cits.appendChild(pill);
        });
        div.appendChild(cits);
    }
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

$("#chat-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = $("#question").value.trim();
    if (!question) return;
    appendMessage("user", question);
    $("#question").value = "";
    setStatus("Streaming response...");
    let url = `${API_BASE}/query/stream`;
    const body = JSON.stringify({ question, top_k: 5 });
    const headers = { "Content-Type": "application/json" };
    if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
    headers["X-Tenant-Id"] = state.tenantId;
    try {
        const resp = await fetch(url, { method: "POST", headers, body });
        if (!resp.ok) {
            const detail = await resp.text();
            throw new Error(`${resp.status} ${detail}`);
        }
        setStatus("", "");
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let assistantText = "";
        let citations = [];
        const assistantDiv = document.createElement("div");
        assistantDiv.className = "message assistant";
        const bodyDiv = document.createElement("div");
        bodyDiv.className = "body";
        bodyDiv.textContent = "";
        assistantDiv.appendChild(bodyDiv);
        messagesEl.appendChild(assistantDiv);
        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            let idx;
            while ((idx = buffer.indexOf("\n\n")) !== -1) {
                const rawEvent = buffer.slice(0, idx);
                buffer = buffer.slice(idx + 2);
                const lines = rawEvent.split("\n");
                const event = {};
                for (const ln of lines) {
                    if (ln.startsWith("event: ")) event.event = ln.slice(7).trim();
                    if (ln.startsWith("data: ")) event.data = ln.slice(6).trim();
                }
                if (!event.event) continue;
                if (event.event === "citation") {
                    citations = JSON.parse(event.data || "[]");
                    const cits = document.createElement("div");
                    cits.className = "citations";
                    citations.forEach((c, i) => {
                        const pill = document.createElement("span");
                        pill.className = "citation";
                        pill.textContent = `[${i + 1}] ${c.document_title || c.document_id}`;
                        pill.title = c.snippet || "";
                        cits.appendChild(pill);
                    });
                    assistantDiv.appendChild(cits);
                } else if (event.event === "token") {
                    const tok = JSON.parse(event.data || "\"\"");
                    assistantText += tok;
                    bodyDiv.textContent = assistantText;
                    messagesEl.scrollTop = messagesEl.scrollHeight;
                } else if (event.event === "error") {
                    bodyDiv.textContent = `Error: ${event.data}`;
                } else if (event.event === "done") {
                    // final sentinel — show audit ID as meta
                    try {
                        const meta = document.createElement("div");
                        meta.className = "meta";
                        const parsed = JSON.parse(event.data || "{}");
                        meta.textContent = `Audit ID: ${parsed.audit_id || "-"}`;
                        assistantDiv.appendChild(meta);
                    } catch (_) { /* ignore */ }
                }
            }
        }
    } catch (err) {
        appendMessage("assistant", `Error: ${err.message}`);
    }
});

// ---- documents --------------------------------------------------------------
async function loadDocuments() {
    try {
        const items = await api("/documents");
        const tbody = $("#documents-table tbody");
        tbody.innerHTML = "";
        items.forEach((d) => {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td>${escapeHtml(d.title)}</td>
                <td>${escapeHtml(d.source_filename)}</td>
                <td>${escapeHtml(d.status)}</td>
                <td>${(d.size_bytes / 1024).toFixed(1)}</td>
                <td>${d.redacted_entity_count}</td>
                <td>${new Date(d.uploaded_at).toLocaleString()}</td>
                <td><button class="ghost" data-id="${d.id}">Delete</button></td>
            `;
            tbody.appendChild(tr);
        });
        $$("#documents-table .ghost").forEach((btn) => {
            btn.addEventListener("click", async () => {
                if (!confirm("Delete this document?")) return;
                try {
                    await api(`/documents/${btn.dataset.id}`, { method: "DELETE" });
                    loadDocuments();
                } catch (err) {
                    alert(`Delete failed: ${err.message}`);
                }
            });
        });
    } catch (err) {
        const tbody = $("#documents-table tbody");
        tbody.innerHTML = `<tr><td colspan="7">${escapeHtml(err.message)}</td></tr>`;
    }
}

$("#refresh-documents").addEventListener("click", loadDocuments);

// ---- audit ------------------------------------------------------------------
async function loadAudit() {
    try {
        const items = await api("/audit?limit=50");
        const tbody = $("#audit-table tbody");
        tbody.innerHTML = "";
        items.forEach((row) => {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td>${new Date(row.occurred_at).toLocaleString()}</td>
                <td>${escapeHtml(row.user_id)}</td>
                <td>${escapeHtml(row.action)}</td>
                <td>${escapeHtml(row.resource_type)}${row.resource_id ? ` <small>${escapeHtml(row.resource_id)}</small>` : ""}</td>
                <td><pre style="margin:0; white-space: pre-wrap; word-break: break-all;">${escapeHtml(JSON.stringify(row.metadata, null, 2))}</pre></td>
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        const tbody = $("#audit-table tbody");
        tbody.innerHTML = `<tr><td colspan="5">${escapeHtml(err.message)}</td></tr>`;
    }
}

$("#refresh-audit").addEventListener("click", loadAudit);

// ---- server connectivity ----------------------------------------------------
async function ping() {
    try {
        const data = await api("/health");
        $("#server-status").textContent = `Connected (${data.vector_store || "?"})`;
    } catch (err) {
        $("#server-status").textContent = `Disconnected: ${err.message}`;
    }
}

ping();
