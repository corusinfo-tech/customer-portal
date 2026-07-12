from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime

from zentryx_customer_portal.permissions import (
    can_manage_customer_staff,
    get_portal_scope,
    has_portal_permission,
    require_portal_permission,
)
from zentryx_customer_portal.sync import sync_all


def _limit_page_length(limit_page_length=20):
    return max(1, min(cint(limit_page_length) or 20, 100))


def _ticket_doctype():
    return "HD Ticket" if frappe.db.exists("DocType", "HD Ticket") else "Issue"


@frappe.whitelist()
def dashboard_summary():
    scope = get_portal_scope()
    customer = scope["customer"]
    ticket_dt = _ticket_doctype()
    open_ticket_filters = _scoped_filters(scope, {"status": ["not in", ["Closed", "Resolved"]]})
    closed_ticket_filters = _scoped_filters(scope, {"status": ["in", ["Closed", "Resolved"]]})

    summary = {
        "customer": customer,
        "customer_name": _scope_title(scope),
        "outstanding_amount": _sum("Sales Invoice", "outstanding_amount", _scoped_filters(scope, {"docstatus": 1})),
        "open_tickets": frappe.db.count(ticket_dt, open_ticket_filters),
        "closed_tickets": frappe.db.count(ticket_dt, closed_ticket_filters),
        "pending_quotations": frappe.db.count(
            "Quotation",
            _scoped_filters(scope, {"quotation_to": "Customer", "status": ["not in", ["Ordered", "Lost"]]}, "party_name"),
        ),
        "active_projects": frappe.db.count(
            "Project", _scoped_filters(scope, {"status": ["not in", ["Completed", "Cancelled"]]})
        ),
        "amc_expiry": frappe.db.get_value(
            "AMC Contract",
            _scoped_filters(scope, {"status": "Active"}),
            "end_date",
            order_by="end_date asc",
        ),
        "recent_activities": recent_activities(scope),
        "announcements": announcements(),
    }
    return summary


@frappe.whitelist()
def tickets(limit_page_length=20):
    scope = get_portal_scope()
    doctype = _ticket_doctype()
    fields = ["name", "subject", "status", "priority", "creation", "modified"]
    if doctype == "HD Ticket":
        fields.extend(["agent_group", "raised_by"])
    return frappe.get_all(
        doctype,
        filters=_ticket_filters(scope),
        fields=fields,
        order_by="modified desc",
        limit_page_length=_limit_page_length(limit_page_length),
    )


@frappe.whitelist()
def create_ticket(subject, description, priority="Medium", customer=None):
    scope = get_portal_scope()
    require_portal_permission("create_ticket", scope)
    customer = _resolve_ticket_customer(scope, customer)
    doctype = _ticket_doctype()
    doc = frappe.new_doc(doctype)
    doc.subject = subject
    doc.description = description
    doc.priority = priority
    if customer and hasattr(doc, "customer"):
        doc.customer = customer
    if hasattr(doc, "raised_by"):
        doc.raised_by = frappe.session.user
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return {"name": doc.name}


@frappe.whitelist()
def reply_ticket(ticket, message):
    scope = get_portal_scope()
    require_portal_permission("reply_ticket", scope)
    doctype = _ticket_doctype()
    doc = frappe.get_doc(doctype, ticket)
    if not scope["internal"] and getattr(doc, "customer", None) != scope["customer"]:
        frappe.throw(_("Not permitted."), frappe.PermissionError)
    doc.add_comment("Comment", text=message)
    frappe.publish_realtime("zentryx_portal_notification", {"doctype": doctype, "name": ticket}, user=frappe.session.user)
    return {"ok": True}


@frappe.whitelist()
def invoices(status=None, limit_page_length=20):
    scope = get_portal_scope()
    require_portal_permission("view_invoices", scope)
    filters = _scoped_filters(scope, {"docstatus": 1})
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
    scope = get_portal_scope()
    require_portal_permission("view_orders", scope)
    return frappe.get_all(
        "Sales Order",
        filters=_scoped_filters(scope, {"docstatus": 1}),
        fields=["name", "transaction_date", "delivery_date", "grand_total", "status", "per_billed"],
        order_by="transaction_date desc",
        limit_page_length=_limit_page_length(limit_page_length),
    )


@frappe.whitelist()
def payments(limit_page_length=20):
    scope = get_portal_scope()
    require_portal_permission("view_payments", scope)
    if scope["internal"]:
        return frappe.get_all(
            "Payment Entry",
            filters={"docstatus": 1},
            fields=["name", "posting_date", "paid_amount", "status"],
            order_by="posting_date desc",
            limit_page_length=_limit_page_length(limit_page_length),
        )
    customer = scope["customer"]
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
    scope = get_portal_scope()
    require_portal_permission("download_documents", scope)
    return frappe.get_all(
        "Customer Document",
        filters=_scoped_filters(scope),
        fields=["name", "title", "document_type", "reference_doctype", "reference_name", "file", "expires_on"],
        order_by="modified desc",
        limit_page_length=_limit_page_length(limit_page_length),
    )


@frappe.whitelist()
def update_profile(phone=None, mobile_no=None, notification_preferences=None):
    scope = get_portal_scope()
    if scope["internal"]:
        frappe.throw(_("Internal users should update their profile from Desk."), frappe.PermissionError)

    portal_user = frappe.get_doc("Portal User", scope["portal_user"])
    if notification_preferences is not None:
        portal_user.notification_preferences = notification_preferences
    portal_user.save(ignore_permissions=True)

    if portal_user.contact:
        contact = frappe.get_doc("Contact", portal_user.contact)
        if phone is not None:
            contact.phone = phone
        if mobile_no is not None:
            contact.mobile_no = mobile_no
        contact.save(ignore_permissions=True)
    return {"ok": True}


@frappe.whitelist()
def quotations(limit_page_length=20):
    scope = get_portal_scope()
    require_portal_permission("view_quotations", scope)
    return frappe.get_all(
        "Quotation",
        filters=_scoped_filters(scope, {"quotation_to": "Customer"}, "party_name"),
        fields=["name", "transaction_date", "valid_till", "grand_total", "status"],
        order_by="transaction_date desc",
        limit_page_length=_limit_page_length(limit_page_length),
    )


@frappe.whitelist()
def quotation_action(quotation, action, comment=None):
    scope = get_portal_scope()
    doc = frappe.get_doc("Quotation", quotation)
    if not scope["internal"] and (doc.quotation_to != "Customer" or doc.party_name != scope["customer"]):
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
    scope = get_portal_scope()
    require_portal_permission("view_projects", scope)
    return frappe.get_all(
        "Project",
        filters=_scoped_filters(scope),
        fields=["name", "project_name", "status", "percent_complete", "expected_end_date"],
        order_by="modified desc",
        limit_page_length=_limit_page_length(limit_page_length),
    )


@frappe.whitelist()
def amc(limit_page_length=20):
    scope = get_portal_scope()
    return frappe.get_all(
        "AMC Contract",
        filters=_scoped_filters(scope),
        fields=["name", "contract_number", "start_date", "end_date", "coverage", "sla", "status", "engineer", "renewal_date"],
        order_by="end_date asc",
        limit_page_length=_limit_page_length(limit_page_length),
    )


@frappe.whitelist()
def network_status():
    scope = get_portal_scope()
    devices = frappe.get_all(
        "Network Device",
        filters=_scoped_filters(scope),
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
    scope = get_portal_scope()
    rows = announcements()
    schedules = frappe.get_all(
        "Maintenance Schedule",
        filters=_scoped_filters(scope, {"status": ["in", ["Planned", "In Progress"]]}),
        fields=["name", "title", "scheduled_start", "scheduled_end", "status"],
        order_by="scheduled_start asc",
        limit_page_length=_limit_page_length(limit_page_length),
    )
    return {"unread_count": len(rows) + len(schedules), "announcements": rows, "maintenance": schedules}


@frappe.whitelist()
def global_search(q, limit_page_length=10):
    scope = get_portal_scope()
    term = f"%{q}%"
    limit = _limit_page_length(limit_page_length)
    results = []
    search_specs = [
        ("Sales Invoice", _scoped_filters(scope), ["name", "status"]),
        ("Quotation", _scoped_filters(scope, {"quotation_to": "Customer"}, "party_name"), ["name", "status"]),
        ("Project", _scoped_filters(scope), ["name", "project_name", "status"]),
        (_ticket_doctype(), _scoped_filters(scope), ["name", "subject", "status"]),
    ]
    for doctype, filters, fields in search_specs:
        filters["name"] = ["like", term]
        for row in frappe.get_all(doctype, filters=filters, fields=fields, limit_page_length=limit):
            row["doctype"] = doctype
            results.append(row)
    return results[:limit]


@frappe.whitelist()
def portal_customers(limit_page_length=50):
    scope = get_portal_scope()
    if scope["internal"]:
        filters = {}
    else:
        filters = {"name": scope["portal_customer"]}
    return frappe.get_all(
        "Portal Customer",
        filters=filters,
        fields=["name", "customer_name", "erpnext_customer", "status", "primary_email", "primary_mobile"],
        order_by="customer_name asc",
        limit_page_length=_limit_page_length(limit_page_length),
    )


@frappe.whitelist()
def portal_staff(portal_customer=None, limit_page_length=50):
    scope = get_portal_scope()
    if scope["internal"]:
        filters = {"portal_customer": portal_customer} if portal_customer else {}
    else:
        require_portal_permission("manage_staff", scope)
        filters = {"portal_customer": scope["portal_customer"]}
    return frappe.get_all(
        "Portal User",
        filters=filters,
        fields=["name", "user", "email", "full_name", "user_type", "enabled", "portal_customer", "department", "permission_group"],
        order_by="full_name asc",
        limit_page_length=_limit_page_length(limit_page_length),
    )


@frappe.whitelist()
def portal_departments(portal_customer=None, limit_page_length=50):
    scope = get_portal_scope()
    if scope["internal"]:
        filters = {"portal_customer": portal_customer} if portal_customer else {}
    else:
        filters = {"portal_customer": scope["portal_customer"]}
    return frappe.get_all(
        "Portal Department",
        filters=filters,
        fields=["name", "portal_customer", "department_name", "manager", "enabled"],
        order_by="department_name asc",
        limit_page_length=_limit_page_length(limit_page_length),
    )


@frappe.whitelist()
def save_department(department_name, portal_customer=None, department=None, manager=None, enabled=1):
    scope = get_portal_scope()
    portal_customer = portal_customer if scope["internal"] else scope["portal_customer"]
    if not scope["internal"]:
        require_portal_permission("manage_departments", scope)
    if not frappe.db.exists("Portal Customer", portal_customer):
        frappe.throw(_("Portal Customer is required."), frappe.ValidationError)

    doc = frappe.get_doc("Portal Department", department) if department else frappe.new_doc("Portal Department")
    if not scope["internal"] and doc.name and doc.portal_customer != scope["portal_customer"]:
        frappe.throw(_("Not permitted for this portal account."), frappe.PermissionError)
    doc.portal_customer = portal_customer
    doc.department_name = department_name
    doc.manager = manager
    doc.enabled = cint(enabled)
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"name": doc.name}


@frappe.whitelist()
def permission_groups(limit_page_length=100):
    scope = get_portal_scope()
    if not scope["internal"] and not has_portal_permission("manage_permissions", scope):
        frappe.throw(_("Not permitted for this portal account."), frappe.PermissionError)
    return frappe.get_all(
        "Portal Permission Group",
        filters={"enabled": 1},
        fields=["name", "group_name", "read_only", "create_ticket", "reply_ticket", "view_company_tickets", "view_invoices"],
        order_by="group_name asc",
        limit_page_length=_limit_page_length(limit_page_length),
    )


@frappe.whitelist()
def invite_staff(email, full_name=None, portal_customer=None, department=None, permission_group=None, user_type="Customer Staff"):
    scope = get_portal_scope()
    portal_customer = portal_customer if scope["internal"] else scope["portal_customer"]
    if not can_manage_customer_staff(scope, portal_customer):
        frappe.throw(_("Not permitted for this portal account."), frappe.PermissionError)

    if not frappe.db.exists("Portal Customer", portal_customer):
        frappe.throw(_("Portal Customer is required."), frappe.ValidationError)

    user_name = frappe.db.get_value("User", {"email": email}, "name")
    if not user_name:
        user = frappe.new_doc("User")
        user.email = email
        user.first_name = full_name or email
        user.user_type = "Website User"
        user.send_welcome_email = 1
        user.insert(ignore_permissions=True)
        user_name = user.name

    portal_user_name = frappe.db.get_value("Portal User", {"email": email}, "name")
    doc = frappe.get_doc("Portal User", portal_user_name) if portal_user_name else frappe.new_doc("Portal User")
    doc.user = user_name
    doc.email = email
    doc.full_name = full_name or frappe.db.get_value("User", user_name, "full_name")
    doc.user_type = user_type
    doc.enabled = 1
    doc.portal_customer = portal_customer
    doc.department = department
    doc.permission_group = permission_group or doc.permission_group or frappe.db.get_value(
        "Portal Permission Group", {"group_name": "Ticket User"}, "name"
    )
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"name": doc.name, "user": user_name}


@frappe.whitelist()
def set_staff_enabled(portal_user, enabled):
    scope = get_portal_scope()
    doc = frappe.get_doc("Portal User", portal_user)
    if not can_manage_customer_staff(scope, doc.portal_customer):
        frappe.throw(_("Not permitted for this portal account."), frappe.PermissionError)
    doc.enabled = cint(enabled)
    doc.save(ignore_permissions=True)
    return {"ok": True}


@frappe.whitelist()
def reset_staff_password(portal_user):
    scope = get_portal_scope()
    doc = frappe.get_doc("Portal User", portal_user)
    if not can_manage_customer_staff(scope, doc.portal_customer):
        frappe.throw(_("Not permitted for this portal account."), frappe.PermissionError)
    if not doc.user:
        frappe.throw(_("No Frappe User is linked to this Portal User."), frappe.ValidationError)
    from frappe.core.doctype.user.user import reset_password

    reset_password(doc.user)
    return {"ok": True}


@frappe.whitelist()
def sync_customers():
    scope = get_portal_scope()
    if not scope["internal"]:
        frappe.throw(_("Only internal users can run customer synchronization."), frappe.PermissionError)
    return sync_all("Manual")


def announcements():
    return frappe.get_all(
        "Portal Announcement",
        filters={"enabled": 1},
        fields=["name", "title", "message", "valid_from", "valid_to"],
        order_by="valid_from desc",
        limit_page_length=5,
    )


def recent_activities(scope):
    rows = []
    for doctype, filters, title_field in [
        ("Sales Invoice", _scoped_filters(scope, {"docstatus": 1}), "name"),
        ("Quotation", _scoped_filters(scope, {"quotation_to": "Customer"}, "party_name"), "name"),
        (_ticket_doctype(), _scoped_filters(scope), "subject"),
        ("Project", _scoped_filters(scope), "project_name"),
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


def _scoped_filters(scope, filters=None, customer_field="customer"):
    filters = dict(filters or {})
    if not scope["internal"]:
        filters[customer_field] = scope["customer"]
    return filters


def _ticket_filters(scope):
    filters = _scoped_filters(scope)
    if scope["internal"] or has_portal_permission("view_company_tickets", scope):
        return filters
    if has_portal_permission("view_department_tickets", scope):
        return filters
    filters["raised_by"] = frappe.session.user
    return filters


def _scope_title(scope):
    if scope["internal"]:
        return _("All Organisations")
    customer = scope["customer"]
    return frappe.db.get_value("Customer", customer, "customer_name") or customer


def _resolve_ticket_customer(scope, requested_customer=None):
    if scope["internal"]:
        if not requested_customer:
            return None
        if not frappe.db.exists("Customer", requested_customer):
            frappe.throw(_("Could not find Customer: {0}").format(requested_customer), frappe.DoesNotExistError)
        return requested_customer
    return scope["customer"]
