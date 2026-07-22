from __future__ import annotations

from difflib import SequenceMatcher
import json

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime

from zentryx_customer_portal.permissions import (
    can_manage_customer_staff,
    can_access_customer,
    can_access_service_department,
    can_access_ticket,
    get_ticket_metadata,
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
def portal_context():
    scope = get_portal_scope()
    permissions = scope["permissions"] if not scope["privileged"] else {"all": True}
    return {
        "internal": scope["internal"],
        "privileged": scope["privileged"],
        "customer": scope["customer"],
        "portal_customer": scope["portal_customer"],
        "department": scope["department"],
        "service_department": scope["service_department"],
        "user_type": scope["user_type"],
        "permissions": permissions,
        "allowed_service_departments": scope["allowed_service_departments"],
        "navigation": _authorized_navigation(scope),
    }


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
    rows = frappe.get_all(
        doctype,
        filters=_ticket_filters(scope),
        fields=fields,
        order_by="modified desc",
        limit_page_length=_limit_page_length(limit_page_length) * 3,
    )
    return [_with_ticket_metadata(row, doctype) for row in rows if _can_view_ticket_row(doctype, row, scope)][
        : _limit_page_length(limit_page_length)
    ]


@frappe.whitelist()
def create_ticket(subject, description, priority="Medium", customer=None, service_department=None, customer_department=None):
    scope = get_portal_scope()
    require_portal_permission("create_ticket", scope)
    portal_customer, erpnext_customer = _resolve_ticket_customer(scope, customer)
    service_department = _validate_service_department(scope, service_department)
    customer_department = _validate_customer_department(scope, portal_customer, customer_department)
    doctype = _ticket_doctype()
    doc = frappe.new_doc(doctype)
    doc.subject = subject
    doc.description = description
    doc.priority = priority
    if erpnext_customer and hasattr(doc, "customer"):
        doc.customer = erpnext_customer
    if hasattr(doc, "raised_by"):
        doc.raised_by = frappe.session.user
    _apply_service_route(doc, service_department)
    # Portal authorization and customer/department validation have already completed above.
    doc.insert(ignore_permissions=True)
    _upsert_ticket_metadata(
        doctype,
        doc.name,
        scope,
        erpnext_customer,
        portal_customer,
        service_department,
        customer_department,
    )
    frappe.db.commit()
    return {"name": doc.name}


@frappe.whitelist()
def reply_ticket(ticket, message):
    scope = get_portal_scope()
    require_portal_permission("reply_ticket", scope)
    doctype = _ticket_doctype()
    doc = frappe.get_doc(doctype, ticket)
    row = frappe.db.get_value(doctype, ticket, ["name", "raised_by"], as_dict=True)
    if not row or not _can_view_ticket_row(doctype, row, scope):
        frappe.throw(_("Not permitted."), frappe.PermissionError)
    doc.add_comment("Comment", text=message)
    frappe.publish_realtime("zentryx_portal_notification", {"doctype": doctype, "name": ticket}, user=frappe.session.user)
    return {"ok": True}


@frappe.whitelist()
def ticket_detail(ticket, ticket_doctype=None):
    scope = get_portal_scope()
    doctype = ticket_doctype or _ticket_doctype()
    if not can_access_ticket(doctype, ticket, scope):
        frappe.throw(_("Not permitted."), frappe.PermissionError)
    doc = frappe.get_doc(doctype, ticket)
    metadata = get_ticket_metadata(doctype, ticket)
    comments = frappe.get_all(
        "Comment",
        filters={"reference_doctype": doctype, "reference_name": ticket},
        fields=["name", "comment_type", "content", "owner", "creation"],
        order_by="creation asc",
        limit_page_length=100,
    )
    attachments = frappe.get_all(
        "File",
        filters={"attached_to_doctype": doctype, "attached_to_name": ticket},
        fields=["name", "file_name", "file_url", "is_private", "owner", "creation"],
        order_by="creation asc",
        limit_page_length=100,
    )
    merged = frappe.get_all(
        "Portal Ticket Metadata",
        filters={"ticket_doctype": doctype, "primary_ticket": ticket, "duplicate_status": "Merged"},
        fields=["ticket", "merged_by", "merged_on", "merge_reason"],
        order_by="merged_on desc",
    )
    return {
        "ticket": doc.as_dict(),
        "metadata": metadata.as_dict() if metadata else None,
        "comments": comments,
        "attachments": attachments,
        "merged_tickets": merged,
    }


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
def selectable_customers(q=None, limit_page_length=20):
    scope = get_portal_scope()
    if not scope["internal"]:
        frappe.throw(_("Customer selector is available only for internal users."), frappe.PermissionError)
    filters = {"status": "Active"}
    if q:
        filters["customer_name"] = ["like", f"%{q}%"]
    rows = frappe.get_all(
        "Portal Customer",
        filters=filters,
        fields=["name", "customer_name", "erpnext_customer"],
        order_by="customer_name asc",
        limit_page_length=_limit_page_length(limit_page_length) * 3,
    )
    return [row for row in rows if can_access_customer(scope, row.erpnext_customer, row.name)][
        : _limit_page_length(limit_page_length)
    ]


@frappe.whitelist()
def service_departments():
    scope = get_portal_scope()
    filters = {"enabled": 1}
    if scope["internal"] and not scope["privileged"]:
        filters["name"] = ["in", scope["allowed_service_departments"]]
    return frappe.get_all(
        "Portal Service Department",
        filters=filters,
        fields=["name", "department_name", "category", "route_to_team"],
        order_by="department_name asc",
    )


@frappe.whitelist()
def previous_tickets(customer, status=None, service_department=None, q=None, limit_page_length=20):
    scope = get_portal_scope()
    portal_customer, erpnext_customer = _resolve_ticket_customer(scope, customer)
    doctype = _ticket_doctype()
    filters = {"customer": erpnext_customer}
    if status:
        filters["status"] = status
    if q:
        filters["subject"] = ["like", f"%{q}%"]
    rows = frappe.get_all(
        doctype,
        filters=filters,
        fields=["name", "subject", "status", "priority", "creation", "modified", "raised_by"],
        order_by="modified desc",
        limit_page_length=_limit_page_length(limit_page_length) * 3,
    )
    result = []
    for row in rows:
        metadata = get_ticket_metadata(doctype, row.name)
        if service_department and (not metadata or metadata.service_department != service_department):
            continue
        if metadata and metadata.portal_customer != portal_customer:
            continue
        if can_access_ticket(doctype, row.name, scope):
            result.append(_with_ticket_metadata(row, doctype))
    return result[: _limit_page_length(limit_page_length)]


@frappe.whitelist()
def similar_tickets(customer, service_department, subject, limit_page_length=5):
    scope = get_portal_scope()
    if not subject or len(subject.strip()) < 4:
        return []
    portal_customer, _erpnext_customer = _resolve_ticket_customer(scope, customer)
    service_department = _validate_service_department(scope, service_department)
    doctype = _ticket_doctype()
    metadata_rows = frappe.get_all(
        "Portal Ticket Metadata",
        filters={
            "ticket_doctype": doctype,
            "portal_customer": portal_customer,
            "duplicate_status": ["!=", "Merged"],
        },
        fields=["ticket", "service_department"],
        order_by="modified desc",
        limit_page_length=100,
    )
    normalized_subject = _normalize_subject(subject)
    candidates = []
    for metadata in metadata_rows:
        if metadata.service_department != service_department:
            continue
        if not can_access_ticket(doctype, metadata.ticket, scope):
            continue
        row = frappe.db.get_value(
            doctype,
            metadata.ticket,
            ["name", "subject", "status", "priority", "creation", "modified", "raised_by"],
            as_dict=True,
        )
        if not row:
            continue
        score = SequenceMatcher(None, normalized_subject, _normalize_subject(row.subject or "")).ratio()
        if score >= 0.55:
            row["service_department"] = metadata.service_department
            row["similarity_score"] = round(score, 3)
            row["view_url"] = f"/portal?ticket={row.name}"
            candidates.append(row)
    candidates.sort(key=lambda item: item.similarity_score, reverse=True)
    return candidates[: _limit_page_length(limit_page_length)]


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
    if permission_group and not scope["internal"] and frappe.db.get_value("Portal Permission Group", permission_group, "internal_only"):
        frappe.throw(_("Customer administrators cannot assign internal-only permission groups."), frappe.PermissionError)

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
def internal_portal_users(limit_page_length=50):
    scope = get_portal_scope()
    require_portal_permission("manage_internal_users", scope)
    return frappe.get_all(
        "Internal Portal User",
        fields=["name", "user", "employee_name", "enabled", "service_department", "permission_group", "access_all_customers"],
        order_by="employee_name asc",
        limit_page_length=_limit_page_length(limit_page_length),
    )


@frappe.whitelist()
def save_internal_portal_user(user, employee_name, service_department, permission_group, enabled=1, access_all_customers=0):
    scope = get_portal_scope()
    require_portal_permission("manage_internal_users", scope)
    if not scope["privileged"]:
        frappe.throw(_("Only privileged portal administrators can manage internal users."), frappe.PermissionError)
    if not frappe.db.exists("User", user) or not frappe.db.get_value("User", user, "user_type") == "System User":
        frappe.throw(_("Internal portal access requires a Frappe System User."), frappe.ValidationError)
    if not frappe.db.exists("Portal Service Department", service_department):
        frappe.throw(_("Select a valid service department."), frappe.ValidationError)
    if not frappe.db.get_value("Portal Permission Group", permission_group, "internal_only"):
        frappe.throw(_("Internal users require an internal-only permission group."), frappe.ValidationError)
    name = frappe.db.get_value("Internal Portal User", {"user": user}, "name")
    doc = frappe.get_doc("Internal Portal User", name) if name else frappe.new_doc("Internal Portal User")
    doc.user = user
    doc.employee_name = employee_name
    doc.service_department = service_department
    doc.permission_group = permission_group
    doc.enabled = cint(enabled)
    doc.access_all_customers = cint(access_all_customers)
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"name": doc.name}


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
def merge_tickets(primary_ticket, duplicate_ticket, reason=None, ticket_doctype=None):
    scope = get_portal_scope()
    require_portal_permission("merge_ticket", scope)
    doctype = ticket_doctype or _ticket_doctype()
    if primary_ticket == duplicate_ticket:
        frappe.throw(_("A ticket cannot be merged into itself."), frappe.ValidationError)
    if not frappe.db.exists(doctype, primary_ticket) or not frappe.db.exists(doctype, duplicate_ticket):
        frappe.throw(_("Both tickets must exist."), frappe.DoesNotExistError)
    if not can_access_ticket(doctype, primary_ticket, scope) or not can_access_ticket(doctype, duplicate_ticket, scope):
        frappe.throw(_("Not permitted."), frappe.PermissionError)

    primary_meta = get_ticket_metadata(doctype, primary_ticket)
    duplicate_meta = get_ticket_metadata(doctype, duplicate_ticket)
    if not primary_meta or not duplicate_meta:
        frappe.throw(_("Both tickets must have portal metadata before they can be merged."), frappe.ValidationError)
    if duplicate_meta.duplicate_status == "Merged":
        frappe.throw(_("Duplicate ticket is already merged."), frappe.ValidationError)
    if primary_meta.portal_customer != duplicate_meta.portal_customer:
        frappe.throw(_("Cross-customer ticket merge is not allowed."), frappe.PermissionError)
    if primary_meta.service_department != duplicate_meta.service_department and not scope["privileged"]:
        frappe.throw(_("Cross-department ticket merge is not allowed."), frappe.PermissionError)

    duplicate_meta.duplicate_status = "Merged"
    duplicate_meta.primary_ticket = primary_ticket
    duplicate_meta.merged_by = frappe.session.user
    duplicate_meta.merged_on = now_datetime()
    duplicate_meta.merge_reason = reason
    duplicate_meta.save(ignore_permissions=True)

    duplicate_doc = frappe.get_doc(doctype, duplicate_ticket)
    if hasattr(duplicate_doc, "status"):
        duplicate_doc.status = "Closed"
        duplicate_doc.save(ignore_permissions=True)
    frappe.get_doc(doctype, primary_ticket).add_comment(
        "Comment", text=_("Ticket {0} was merged into this ticket. Reason: {1}").format(duplicate_ticket, reason or "-")
    )
    duplicate_doc.add_comment(
        "Comment", text=_("This ticket was merged into {0}. Reason: {1}").format(primary_ticket, reason or "-")
    )
    _audit("Ticket Merged", scope, doctype, duplicate_ticket, {"primary_ticket": primary_ticket, "reason": reason})
    frappe.publish_realtime(
        "zentryx_portal_notification",
        {"doctype": doctype, "name": primary_ticket, "event": "ticket_merged"},
        user=frappe.session.user,
    )
    frappe.db.commit()
    return {"ok": True, "primary_ticket": primary_ticket, "duplicate_ticket": duplicate_ticket}


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
    table = frappe.qb.DocType(doctype)
    query = frappe.qb.from_(table).select(Sum(table[fieldname]).as_("total"))
    for key, value in (filters or {}).items():
        query = _apply_qb_filter(query, table, key, value)
    result = query.run(as_dict=True)
    return flt(result[0].total if result else 0)


def _apply_qb_filter(query, table, key, value):
    field = table[key]
    if isinstance(value, (list, tuple)) and len(value) == 2:
        operator, operand = value
        if operator == "=":
            return query.where(field == operand)
        if operator == "!=":
            return query.where(field != operand)
        if operator == ">":
            return query.where(field > operand)
        if operator == ">=":
            return query.where(field >= operand)
        if operator == "<":
            return query.where(field < operand)
        if operator == "<=":
            return query.where(field <= operand)
        if operator == "in":
            return query.where(field.isin(operand))
        if operator == "not in":
            return query.where(field.notin(operand))
    return query.where(field == value)


def _scoped_filters(scope, filters=None, customer_field="customer"):
    filters = dict(filters or {})
    if scope["internal"]:
        if not scope["access_all_customers"]:
            customers = _scope_erp_customers(scope)
            filters[customer_field] = ["in", customers or [""]]
    else:
        filters[customer_field] = scope["customer"]
    return filters


def _ticket_filters(scope):
    filters = _scoped_filters(scope)
    if scope["internal"]:
        if not scope["access_all_customers"]:
            customers = _scope_erp_customers(scope)
            filters["customer"] = ["in", customers or [""]]
        return filters
    if has_portal_permission("view_company_tickets", scope):
        return filters
    if has_portal_permission("view_department_tickets", scope):
        # Department visibility is enforced after metadata lookup because department lives in app-owned metadata.
        return filters
    filters["raised_by"] = frappe.session.user
    return filters


def _can_view_ticket_row(ticket_doctype, row, scope):
    if not can_access_ticket(ticket_doctype, row.name, scope):
        return False
    if scope["internal"]:
        return True
    if has_portal_permission("view_company_tickets", scope):
        return True
    metadata = get_ticket_metadata(ticket_doctype, row.name)
    if has_portal_permission("view_department_tickets", scope):
        return bool(metadata and metadata.customer_department and metadata.customer_department == scope["department"])
    return row.get("raised_by") == frappe.session.user


def _scope_title(scope):
    if scope["internal"]:
        return _("All Organisations")
    customer = scope["customer"]
    return frappe.db.get_value("Customer", customer, "customer_name") or customer


def _resolve_ticket_customer(scope, requested_customer=None):
    if scope["internal"]:
        if not requested_customer:
            frappe.throw(_("Customer is mandatory when internal users create or search tickets."), frappe.ValidationError)
        portal_customer = requested_customer if frappe.db.exists("Portal Customer", requested_customer) else frappe.db.get_value(
            "Portal Customer", {"erpnext_customer": requested_customer}, "name"
        )
        erpnext_customer = frappe.db.get_value("Portal Customer", portal_customer, "erpnext_customer") if portal_customer else None
        if not portal_customer or not erpnext_customer:
            frappe.throw(_("Select a valid portal customer."), frappe.DoesNotExistError)
        if not can_access_customer(scope, erpnext_customer, portal_customer):
            frappe.throw(_("Not permitted for this customer."), frappe.PermissionError)
        return portal_customer, erpnext_customer
    return scope["portal_customer"], scope["customer"]


def _validate_service_department(scope, service_department):
    if not service_department:
        frappe.throw(_("Service department is required for portal-created tickets."), frappe.ValidationError)
    if not frappe.db.exists("Portal Service Department", {"name": service_department, "enabled": 1}):
        frappe.throw(_("Select a valid service department."), frappe.ValidationError)
    if not can_access_service_department(scope, service_department):
        frappe.throw(_("Not permitted for this service department."), frappe.PermissionError)
    return service_department


def _validate_customer_department(scope, portal_customer, customer_department):
    if not customer_department:
        return None
    dept_customer = frappe.db.get_value("Portal Department", customer_department, "portal_customer")
    if dept_customer != portal_customer:
        frappe.throw(_("Customer department does not belong to the selected customer."), frappe.PermissionError)
    if not scope["internal"] and scope["department"] and customer_department != scope["department"]:
        frappe.throw(_("Not permitted for this customer department."), frappe.PermissionError)
    return customer_department


def _apply_service_route(doc, service_department):
    route_to_team = frappe.db.get_value("Portal Service Department", service_department, "route_to_team")
    if route_to_team and hasattr(doc, "agent_group"):
        doc.agent_group = route_to_team


def _upsert_ticket_metadata(ticket_doctype, ticket, scope, erpnext_customer, portal_customer, service_department, customer_department):
    name = frappe.db.get_value("Portal Ticket Metadata", {"ticket_doctype": ticket_doctype, "ticket": ticket}, "name")
    doc = frappe.get_doc("Portal Ticket Metadata", name) if name else frappe.new_doc("Portal Ticket Metadata")
    doc.ticket_doctype = ticket_doctype
    doc.ticket = ticket
    doc.erpnext_customer = erpnext_customer
    doc.portal_customer = portal_customer
    doc.service_department = service_department
    doc.customer_department = customer_department
    doc.requesting_user = frappe.session.user
    doc.created_by_type = "Internal" if scope["internal"] else "Customer"
    doc.internal_created_by = frappe.session.user if scope["internal"] else None
    doc.permission_context = json.dumps(
        {
            "scope": scope["user_type"],
            "service_department": service_department,
            "customer_department": customer_department,
        }
    )
    doc.save(ignore_permissions=True)
    return doc


def _with_ticket_metadata(row, ticket_doctype):
    metadata = get_ticket_metadata(ticket_doctype, row.name)
    if metadata:
        row["service_department"] = metadata.service_department
        row["customer_department"] = metadata.customer_department
        row["duplicate_status"] = metadata.duplicate_status
        row["primary_ticket"] = metadata.primary_ticket
    return row


def _scope_erp_customers(scope):
    if scope["privileged"] or scope["access_all_customers"]:
        return []
    customers = []
    for portal_customer in scope["allowed_customers"]:
        customer = frappe.db.get_value("Portal Customer", portal_customer, "erpnext_customer")
        if customer:
            customers.append(customer)
    return customers


def _normalize_subject(value):
    return " ".join((value or "").lower().strip().split())


def _authorized_navigation(scope):
    if scope["privileged"]:
        return ["dashboard", "support", "tickets", "knowledge", "sales", "quotations", "orders", "invoices", "payments", "projects", "amc", "network", "reports", "documents", "admin", "settings", "profile"]
    items = ["dashboard", "support", "tickets", "profile"]
    permission_map = {
        "knowledge": "view_knowledge_base",
        "quotations": "view_quotations",
        "orders": "view_orders",
        "invoices": "view_invoices",
        "payments": "view_payments",
        "projects": "view_projects",
        "amc": "view_amc",
        "reports": "view_reports",
        "documents": "download_documents",
        "admin": "manage_staff",
        "settings": "manage_permissions",
    }
    for item, permission in permission_map.items():
        if has_portal_permission(permission, scope):
            items.append(item)
    if any(item in items for item in ("quotations", "orders", "invoices", "payments")):
        items.append("sales")
    return items


def _audit(event, scope, reference_doctype=None, reference_name=None, details=None):
    if not frappe.db.exists("DocType", "Portal Audit Log"):
        return
    doc = frappe.new_doc("Portal Audit Log")
    doc.event = event
    doc.user = frappe.session.user
    doc.portal_user = scope.get("portal_user")
    doc.portal_customer = scope.get("portal_customer")
    doc.reference_doctype = reference_doctype
    doc.reference_name = reference_name
    doc.ip_address = frappe.local.request_ip if getattr(frappe.local, "request_ip", None) else None
    doc.details = json.dumps(details or {})
    doc.insert(ignore_permissions=True)
