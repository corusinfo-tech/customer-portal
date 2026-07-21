class ZentryxPortal {
  constructor() {
    this.root = document.querySelector(".zcp-shell");
    if (!this.root) return;
    this.chart = null;
    this.context = null;
    this.bindNavigation();
    this.bindTheme();
    this.bindSearch();
    this.bindTicketForm();
    this.bindAdministration();
    this.load();
    this.connectRealtime();
  }

  async call(method, args = {}) {
    const response = await frappe.call({ method: `zentryx_customer_portal.api.${method}`, args });
    return response.message;
  }

  bindNavigation() {
    document.querySelectorAll(".zcp-nav button").forEach((button) => {
      button.addEventListener("click", () => this.showPanel(button.dataset.view));
    });
  }

  bindTheme() {
    const saved = localStorage.getItem("zcp-theme");
    if (saved) document.documentElement.dataset.theme = saved;
    document.getElementById("zcp-theme")?.addEventListener("click", () => {
      const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      localStorage.setItem("zcp-theme", next);
    });
  }

  bindSearch() {
    const input = document.getElementById("zcp-search");
    let timeout;
    input?.addEventListener("input", () => {
      clearTimeout(timeout);
      timeout = setTimeout(async () => {
        if (input.value.trim().length < 2) return;
        const results = await this.call("global_search", { q: input.value.trim() });
        this.toast(`${results.length} result(s) found`);
      }, 350);
    });
  }

  bindTicketForm() {
    document.getElementById("zcp-ticket-customer")?.addEventListener("change", () => this.loadPreviousTickets());
    document.getElementById("zcp-service-department")?.addEventListener("change", () => {
      this.loadPreviousTickets();
      this.loadSimilarTickets();
    });
    document.querySelector("#zcp-ticket-form [name='subject']")?.addEventListener("input", () => {
      clearTimeout(this.similarTimer);
      this.similarTimer = setTimeout(() => this.loadSimilarTickets(), 400);
    });
    document.getElementById("zcp-ticket-form")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      const payload = Object.fromEntries(form.entries());
      Object.keys(payload).forEach((key) => {
        if (payload[key] === "") delete payload[key];
      });
      await this.call("create_ticket", payload);
      event.currentTarget.reset();
      this.toast("Ticket created");
      await this.loadTickets();
      this.showPanel("tickets");
    });
  }

  async load() {
    this.context = await this.call("portal_context");
    this.applyNavigation();
    const summary = await this.call("dashboard_summary");
    this.renderSummary(summary);
    this.renderActivities(summary.recent_activities || []);
    this.renderChart(summary);
    document.getElementById("zcp-customer-name").textContent = summary.customer_name || "Customer Portal";
    await Promise.all([
      this.safeLoad("tickets", () => this.loadTickets()),
      this.safeLoad("quotations", () => this.loadQuotations()),
      this.safeLoad("invoices", () => this.loadInvoices()),
      this.safeLoad("projects", () => this.loadProjects()),
      this.safeLoad("amc", () => this.loadAmc()),
      this.safeLoad("network", () => this.loadNetwork()),
      this.safeLoad("dashboard", () => this.loadNotifications()),
      this.safeLoad("admin", () => this.loadAdministration()),
      this.safeLoad("support", () => this.loadTicketControls()),
    ]);
  }

  applyNavigation() {
    const allowed = new Set(this.context?.navigation || []);
    document.querySelectorAll(".zcp-nav button").forEach((button) => {
      button.hidden = !allowed.has(button.dataset.view);
    });
  }

  async safeLoad(view, loader) {
    if (this.context?.navigation && !this.context.navigation.includes(view)) return;
    try {
      await loader();
    } catch {
      // Authorization is enforced server-side; failed optional modules should not break portal startup.
    }
  }

  renderSummary(summary) {
    const cards = [
      ["Outstanding Amount", this.currency(summary.outstanding_amount)],
      ["Open Tickets", summary.open_tickets],
      ["Closed Tickets", summary.closed_tickets],
      ["Pending Quotations", summary.pending_quotations],
      ["Active Projects", summary.active_projects],
      ["AMC Expiry", summary.amc_expiry || "-"],
      ["SLA Status", "Tracked"],
      ["Documents", "Available"],
    ];
    document.getElementById("zcp-summary").innerHTML = cards
      .map(([label, value]) => `<article class="zcp-card"><span>${this.escape(label)}</span><strong>${this.escape(value)}</strong></article>`)
      .join("");
  }

  renderActivities(rows) {
    document.getElementById("zcp-activities").innerHTML = rows.length
      ? rows.map((row) => this.row(row.title || row.name, row.doctype, row.modified)).join("")
      : `<div class="zcp-empty">No recent activity.</div>`;
  }

  renderChart(summary) {
    if (!window.Chart) return setTimeout(() => this.renderChart(summary), 100);
    const canvas = document.getElementById("zcp-chart");
    if (!canvas) return;
    this.chart?.destroy();
    this.chart = new Chart(canvas, {
      type: "doughnut",
      data: {
        labels: ["Open Tickets", "Closed Tickets", "Pending Quotations", "Active Projects"],
        datasets: [{
          data: [summary.open_tickets, summary.closed_tickets, summary.pending_quotations, summary.active_projects],
          backgroundColor: ["#0f766e", "#2563eb", "#b45309", "#7c3aed"],
        }],
      },
      options: { plugins: { legend: { position: "bottom" } } },
    });
  }

  async loadTickets() {
    const rows = await this.call("tickets");
    document.getElementById("zcp-tickets").innerHTML = rows.map((row) => this.row(row.subject || row.name, row.status, row.priority)).join("");
  }

  async loadQuotations() {
    const rows = await this.call("quotations");
    document.getElementById("zcp-quotations").innerHTML = rows
      .map((row) => this.row(row.name, row.status, `${this.currency(row.grand_total)} · <a href="/api/method/frappe.utils.print_format.download_pdf?doctype=Quotation&name=${encodeURIComponent(row.name)}">PDF</a>`))
      .join("");
  }

  async loadInvoices() {
    const rows = await this.call("invoices");
    document.getElementById("zcp-invoices").innerHTML = rows
      .map((row) => this.row(row.name, row.status, `${this.currency(row.outstanding_amount)} outstanding · <a href="/api/method/frappe.utils.print_format.download_pdf?doctype=Sales Invoice&name=${encodeURIComponent(row.name)}">PDF</a>`))
      .join("");
  }

  async loadProjects() {
    const rows = await this.call("projects");
    document.getElementById("zcp-projects").innerHTML = rows.map((row) => this.row(row.project_name || row.name, row.status, `${row.percent_complete || 0}%`)).join("");
  }

  async loadAmc() {
    const rows = await this.call("amc");
    document.getElementById("zcp-amc").innerHTML = rows.map((row) => this.row(row.contract_number || row.name, row.status, row.end_date)).join("");
  }

  async loadNetwork() {
    const status = await this.call("network_status");
    const health = status.device_health || [];
    document.getElementById("zcp-network").innerHTML = [
      this.row("Router Status", status.router_status, "REST placeholder"),
      this.row("Firewall Status", status.firewall_status, "REST placeholder"),
      ...health.map((device) => this.row(device.hostname, device.status, [device.vendor, device.model].filter(Boolean).join(" "))),
    ].join("");
  }

  async loadNotifications() {
    const data = await this.call("notifications");
    document.getElementById("zcp-unread").textContent = data.unread_count || 0;
  }

  async loadTicketControls() {
    await Promise.all([this.loadSelectableCustomers(), this.loadServiceDepartments()]);
  }

  async loadSelectableCustomers() {
    const select = document.getElementById("zcp-ticket-customer");
    if (!select) return;
    try {
      const rows = await this.call("selectable_customers");
      select.innerHTML = `<option value="">Select customer</option>` + rows
        .map((row) => `<option value="${this.escape(row.name)}">${this.escape(row.customer_name)} (${this.escape(row.erpnext_customer)})</option>`)
        .join("");
      select.hidden = rows.length === 0;
    } catch {
      select.hidden = true;
    }
  }

  async loadServiceDepartments() {
    const select = document.getElementById("zcp-service-department");
    if (!select) return;
    const rows = await this.call("service_departments");
    select.innerHTML = `<option value="">Select service department</option>` + rows
      .map((row) => `<option value="${this.escape(row.name)}">${this.escape(row.department_name)}</option>`)
      .join("");
  }

  async loadPreviousTickets() {
    const target = document.getElementById("zcp-previous-tickets");
    const customer = document.getElementById("zcp-ticket-customer")?.value;
    if (!target || !customer) return;
    try {
      const rows = await this.call("previous_tickets", {
        customer,
        service_department: document.getElementById("zcp-service-department")?.value,
      });
      target.innerHTML = rows.length
        ? rows.map((row) => this.row(row.subject || row.name, row.status, row.service_department || row.priority)).join("")
        : `<div class="zcp-empty">No previous tickets found.</div>`;
    } catch {
      target.innerHTML = "";
    }
  }

  async loadSimilarTickets() {
    const target = document.getElementById("zcp-similar-tickets");
    const customer = document.getElementById("zcp-ticket-customer")?.value;
    const service_department = document.getElementById("zcp-service-department")?.value;
    const subject = document.querySelector("#zcp-ticket-form [name='subject']")?.value;
    if (!target || !customer || !service_department || !subject || subject.length < 4) return;
    try {
      const rows = await this.call("similar_tickets", { customer, service_department, subject });
      target.innerHTML = rows.length
        ? rows.map((row) => this.row(row.subject || row.name, `${row.status} · ${Math.round(row.similarity_score * 100)}%`, `<a href="${row.view_url}">View</a>`)).join("")
        : `<div class="zcp-empty">No similar tickets found.</div>`;
    } catch {
      target.innerHTML = "";
    }
  }

  bindAdministration() {
    document.getElementById("zcp-sync")?.addEventListener("click", async () => {
      await this.call("sync_customers");
      this.toast("Customer synchronization completed");
      await this.loadAdministration();
    });
  }

  async loadAdministration() {
    await Promise.all([this.loadCustomers(), this.loadStaff()]);
  }

  async loadCustomers() {
    const target = document.getElementById("zcp-customers");
    if (!target) return;
    try {
      const rows = await this.call("portal_customers");
      target.innerHTML = rows.map((row) => this.row(row.customer_name, row.status, row.erpnext_customer)).join("");
    } catch {
      target.innerHTML = `<div class="zcp-empty">Customer administration is not available for this account.</div>`;
    }
  }

  async loadStaff() {
    const target = document.getElementById("zcp-staff");
    if (!target) return;
    try {
      const rows = await this.call("portal_staff");
      target.innerHTML = rows.map((row) => this.row(row.full_name || row.email, row.user_type, row.permission_group)).join("");
    } catch {
      target.innerHTML = `<div class="zcp-empty">Staff management is not available for this account.</div>`;
    }
  }

  showPanel(name) {
    document.querySelectorAll(".zcp-nav button").forEach((button) => button.classList.toggle("active", button.dataset.view === name));
    document.querySelectorAll("[data-panel]").forEach((panel) => panel.classList.toggle("d-none", panel.dataset.panel !== name));
  }

  connectRealtime() {
    if (!frappe.realtime) return;
    frappe.realtime.on("zentryx_portal_notification", () => this.loadNotifications());
  }

  row(title, meta, tail) {
    return `<div class="zcp-row"><div><strong>${this.escape(title || "-")}</strong><small>${this.escape(meta || "")}</small></div><span>${tail || ""}</span></div>`;
  }

  currency(value) {
    return Number(value || 0).toLocaleString(undefined, { style: "currency", currency: frappe.boot.sysdefaults?.currency || "INR" });
  }

  escape(value) {
    const element = document.createElement("span");
    element.textContent = String(value ?? "");
    return element.innerHTML;
  }

  toast(message) {
    if (frappe.show_alert) frappe.show_alert({ message, indicator: "green" });
  }
}

document.addEventListener("DOMContentLoaded", () => new ZentryxPortal());
