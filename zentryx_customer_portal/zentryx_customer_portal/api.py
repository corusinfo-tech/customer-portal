from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime

from zentryx_customer_portal.permissions import require_customer


def _limit_page_length(limit_page_length=20):
    return max(1, min(cint(limit_page_length) or 20, 100))


def _ticket_doctype():
    return "HD Ticket" if frappe.db.exists("DocType", "HD Ticket") else "Issue"


@frappe.whitelist()
def dashboard_summary():
    customer = require_customer()
    ticket_dt = _ticket_doctype()
    open_ticket_filters = {"customer": customer, "status": ["not in", ["Closed", "Resolved"]]}
    closed_ticket_filters = {"customer": customer, "status": ["in", ["Closed", "Resolved"]]}

    summary = {
        "customer": customer,
        "customer_name": frappe.db.get_value("Customer", customer, "customer_name") or customer,
        "outstanding_amount": _sum("Sales Invoice", "outstanding_amount", {"customer": customer, "docstatus": 1}),
        "open_tickets": frappe.db.count(ticket_dt, open_ticket_filters),
        "closed_tickets": frappe.db.count(ticket_dt, closed_ticket_filters),
        "pending_quotations": frappe.db.count(
            "Quotation", {"quotation_to": "Customer", "party_name": customer, "status": ["not in", ["Ordered", "Lost"]]}
        ),
        "active_projects": frappe.db.count("Project", {"customer": customer, "status": ["not in", ["Completed", "Cancelled"]]}),
        "amc_expiry": frappe.db.get_value(
            "AMC Contract",
            {"customer": customer, "status": "Active"},
            "end_date",
            order_by="end_date asc",
        ),
        "recent_activities": recent_activities(customer),
        "announcements": announcements(),
    }
    return summary


@frappe.whitelist()
def tickets(limit_page_length=20):
    customer = require_customer()
    doctype = _ticket_doctype()
    fields = ["name", "subject", "status", "priority", "creation", "modified"]
    if doctype == "HD Ticket":
        fields.extend(["agent_group", "raised_by"])
    return frappe.get_all(
        doctype,
        filters={"customer": customer},
        fields=fields,
        order_by="modified desc",
        limit_page_length=_limit_page_length(limit_page_length),
    )


@frappe.whitelist()
def create_ticket(subject, description, priority="Medium"):
    customer = require_customer()
    doctype = _ticket_doctype()
    doc = frappe.new_doc(doctype)
    doc.subject = subject
    doc.description = description
    doc.priority = priority
    doc.customer = customer
    if hasattr(doc, "raised_by"):
        doc.raised_by = frappe.session.user
    doc.insert(ignore_permissions=False)
    frappe.db.commit()
    return {"name": doc.name}


@frappe.whitelist()
def reply_ticket(ticket, message):
    customer = require_customer()
    doctype = _ticket_doctype()
    doc = frappe.get_doc(doctype, ticket)
    if getattr(doc, "customer", None) != customer:
        frappe.throw(_("Not permitted."), frappe.PermissionError)
    doc.add_comment("Comment", text=message)
    frappe.publish_realtime("zentryx_portal_notification", {"doctype": doctype, "name": ticket}, user=frappe.session.user)
    return {"ok": True}


@frappe.whitelist()
def invoices(status=None, limit_page_length=20):
    customer = require_customer()
    filters = {"customer": customer, "docstatus": 1}
    if status == "outstanding":
        filters["outstanding_amount"] = [">", 0]
    elif status == "paid":
        filters["outstanding_amount"] = ["=", 0]
    elif status == "overdue":
        filters.update({"outstanding_amount": [">", 0], "due_date": ["<", getdate()]})
    return frappe.get_all(
        "Sales Invoice",
        filters=filters,
        fields=["name", "posting_date", "due_date", "grand_total", "outstanding_amount", "status"],
        order_by="posting_date desc",
        limit_page_length=_limit_page_length(limit_page_length),
    )


@frappe.whitelist()
def sales_orders(limit_page_length=20):
    customer = require_customer()
    return frappe.get_all(
        "Sales Order",
        filters={"customer": customer, "docstatus": 1},
        fields=["name", "transaction_date", "delivery_date", "grand_total", "status", "per_billed"],
        order_by="transaction_date desc",
        limit_page_length=_limit_page_length(limit_page_length),
    )


@frappe.whitelist()
def payments(limit_page_length=20):
    customer = require_customer()
    return frappe.db.sql(
        """
        select distinct pe.name, pe.posting_date, pe.paid_amount, pe.status, per.reference_doctype, per.reference_name
        from `tabPayment Entry` pe
        inner join `tabPayment Entry Reference` per on per.parent = pe.name
        left join `tabSales Invoice` si on si.name = per.reference_name and per.reference_doctype = 'Sales Invoice'
        left join `tabSales Order` so on so.name = per.reference_name and per.reference_doctype = 'Sales Order'
        where pe.docstatus = 1 and coalesce(si.customer, so.customer) = %(customer)s
        order by pe.posting_date desc
        limit %(limit)s
        """,
        {"customer": customer, "limit": _limit_page_length(limit_page_length)},
        as_dict=True,
    )


@frappe.whitelist()
def documents(limit_page_length=20):
    customer = require_customer()
    return frappe.get_all(
        "Customer Document",
        filters={"customer": customer},
        fields=["name", "title", "document_type", "reference_doctype", "reference_name", "file", "expires_on"],
        order_by="modified desc",
        limit_page_length=_limit_page_length(limit_page_length),
    )


@frappe.whitelist()
def update_profile(phone=None, mobile_no=None, notification_preferences=None):
    customer = require_customer()
    contact_name = frappe.db.get_value("Contact", {"email_id": frappe.session.user}, "name")
    if not contact_name:
        frappe.throw(_("No Contact is linked to your portal account."), frappe.DoesNotExistError)

    linked_customer = frappe.db.get_value(
        "Dynamic Link",
        {"parenttype": "Contact", "parent": contact_name, "link_doctype": "Customer"},
        "link_name",
    )
    if linked_customer != customer:
        frappe.throw(_("Not permitted."), frappe.PermissionError)

    contact = frappe.get_doc("Contact", contact_name)
    if phone is not None:
        contact.phone = phone
    if mobile_no is not None:
        contact.mobile_no = mobile_no
    if notification_preferences is not None and hasattr(contact, "portal_notification_preferences"):
        contact.portal_notification_preferences = notification_preferences
    contact.save(ignore_permissions=False)
    return {"ok": True}


@frappe.whitelist()
def quotations(limit_page_length=20):
    customer = require_customer()
    return frappe.get_all(
        "Quotation",
        filters={"quotation_to": "Customer", "party_name": customer},
        fields=["name", "transaction_date", "valid_till", "grand_total", "status"],
        order_by="transaction_date desc",
        limit_page_length=_limit_page_length(limit_page_length),
    )


@frappe.whitelist()
def quotation_action(quotation, action, comment=None):
    customer = require_customer()
    doc = frappe.get_doc("Quotation", quotation)
    if doc.quotation_to != "Customer" or doc.party_name != customer:
        frappe.throw(_("Not permitted."), frappe.PermissionError)
    if action == "accept":
        doc.status = "Ordered"
    elif action == "reject":
        doc.status = "Lost"
    elif action == "request_revision":
        doc.add_comment("Comment", text=comment or _("Revision requested by customer."))
        return {"status": "Revision Requested"}
    else:
        frappe.throw(_("Unsupported quotation action."))
    doc.add_comment("Comment", text=comment or _("Portal action: {0}").format(action))
    doc.save(ignore_permissions=False)
    return {"status": doc.status}


@frappe.whitelist()
def projects(limit_page_length=20):
    customer = require_customer()
    return frappe.get_all(
        "Project",
        filters={"customer": customer},
        fields=["name", "project_name", "status", "percent_complete", "expected_end_date"],
        order_by="modified desc",
        limit_page_length=_limit_page_length(limit_page_length),
    )


@frappe.whitelist()
def amc(limit_page_length=20):
    customer = require_customer()
    return frappe.get_all(
        "AMC Contract",
        filters={"customer": customer},
        fields=["name", "contract_number", "start_date", "end_date", "coverage", "sla", "status", "engineer", "renewal_date"],
        order_by="end_date asc",
        limit_page_length=_limit_page_length(limit_page_length),
    )


@frappe.whitelist()
def network_status():
    customer = require_customer()
    devices = frappe.get_all(
        "Network Device",
        filters={"customer": customer},
        fields=["name", "hostname", "vendor", "model", "serial_number", "warranty", "location", "status"],
        order_by="hostname asc",
        limit_page_length=100,
    )
    return {
        "updated_at": now_datetime(),
        "router_status": "Pending Integration",
        "firewall_status": "Pending Integration",
        "bandwidth": None,
        "latency": None,
        "packet_loss": None,
        "device_health": devices,
    }


@frappe.whitelist()
def notifications(limit_page_length=20):
    customer = require_customer()
    rows = announcements()
    schedules = frappe.get_all(
        "Maintenance Schedule",
        filters={"customer": customer, "status": ["in", ["Planned", "In Progress"]]},
        fields=["name", "title", "scheduled_start", "scheduled_end", "status"],
        order_by="scheduled_start asc",
        limit_page_length=_limit_page_length(limit_page_length),
    )
    return {"unread_count": len(rows) + len(schedules), "announcements": rows, "maintenance": schedules}


@frappe.whitelist()
def global_search(q, limit_page_length=10):
    customer = require_customer()
    term = f"%{q}%"
    limit = _limit_page_length(limit_page_length)
    results = []
    search_specs = [
        ("Sales Invoice", {"customer": customer}, ["name", "status"]),
        ("Quotation", {"quotation_to": "Customer", "party_name": customer}, ["name", "status"]),
        ("Project", {"customer": customer}, ["name", "project_name", "status"]),
        (_ticket_doctype(), {"customer": customer}, ["name", "subject", "status"]),
    ]
    for doctype, filters, fields in search_specs:
        filters["name"] = ["like", term]
        for row in frappe.get_all(doctype, filters=filters, fields=fields, limit_page_length=limit):
            row["doctype"] = doctype
            results.append(row)
    return results[:limit]


def announcements():
    return frappe.get_all(
        "Portal Announcement",
        filters={"enabled": 1},
        fields=["name", "title", "message", "valid_from", "valid_to"],
        order_by="valid_from desc",
        limit_page_length=5,
    )


def recent_activities(customer):
    rows = []
    for doctype, filters, title_field in [
        ("Sales Invoice", {"customer": customer, "docstatus": 1}, "name"),
        ("Quotation", {"quotation_to": "Customer", "party_name": customer}, "name"),
        (_ticket_doctype(), {"customer": customer}, "subject"),
        ("Project", {"customer": customer}, "project_name"),
    ]:
        for row in frappe.get_all(
            doctype,
            filters=filters,
            fields=["name", f"{title_field} as title", "modified"],
            order_by="modified desc",
            limit_page_length=3,
        ):
            row["doctype"] = doctype
            rows.append(row)
    return sorted(rows, key=lambda item: item.modified, reverse=True)[:8]


def _sum(doctype, fieldname, filters):
    value = frappe.db.get_value(doctype, filters, f"sum({fieldname})")
    return flt(value)
