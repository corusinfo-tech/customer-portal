from __future__ import annotations

import frappe
from frappe import _


CUSTOMER_FIELD_BY_DOCTYPE = {
    "Sales Invoice": "customer",
    "Sales Order": "customer",
    "Quotation": "party_name",
    "Delivery Note": "customer",
    "Project": "customer",
    "Issue": "customer",
    "HD Ticket": "customer",
    "AMC Contract": "customer",
    "Network Device": "customer",
    "Maintenance Schedule": "customer",
    "Customer Document": "customer",
    "SLA Report": "customer",
}

INTERNAL_USER_TYPES = {"System User"}
PRIVILEGED_ROLES = {"System Manager", "Customer Portal Manager"}
CUSTOMER_ADMIN_TYPE = "Customer Company Administrator"
CUSTOMER_STAFF_TYPE = "Customer Staff"
CUSTOMER_READ_ONLY_TYPE = "Customer Read Only"


def is_privileged_user(user: str | None = None) -> bool:
    user = user or frappe.session.user
    if user == "Administrator":
        return True
    if user in ("Guest", None):
        return False
    return bool(PRIVILEGED_ROLES.intersection(set(frappe.get_roles(user))))


def is_frappe_system_user(user: str | None = None) -> bool:
    user = user or frappe.session.user
    if user in ("Guest", None):
        return False
    return frappe.db.get_value("User", user, "user_type") in INTERNAL_USER_TYPES


def is_internal_user(user: str | None = None) -> bool:
    return is_privileged_user(user) or bool(get_internal_portal_user(user))


def get_user_customer(user: str | None = None) -> str | None:
    portal_user = get_portal_user(user)
    return portal_user.get("erpnext_customer") if portal_user else None


def require_customer(user: str | None = None) -> str:
    customer = get_user_customer(user)
    if not customer:
        frappe.throw(
            _("Your portal account is not configured. Ask your Customer Administrator to create or enable your Portal User profile."),
            frappe.PermissionError,
        )
    return customer


def get_portal_scope(user: str | None = None) -> dict:
    user = user or frappe.session.user
    if is_privileged_user(user):
        return {
            "internal": True,
            "privileged": True,
            "customer": None,
            "portal_customer": None,
            "portal_user": None,
            "department": None,
            "service_department": None,
            "user_type": "Internal",
            "permissions": {},
            "access_all_customers": True,
            "allowed_customers": [],
            "allowed_service_departments": [],
        }

    internal_user = get_internal_portal_user(user)
    if internal_user:
        return {
            "internal": True,
            "privileged": False,
            "customer": None,
            "portal_customer": None,
            "portal_user": internal_user.name,
            "department": None,
            "service_department": internal_user.service_department,
            "user_type": "Internal",
            "permissions": _internal_permission_map(internal_user),
            "access_all_customers": bool(internal_user.access_all_customers),
            "allowed_customers": [row.portal_customer for row in internal_user.allowed_customers],
            "allowed_service_departments": [internal_user.service_department],
        }

    if is_frappe_system_user(user):
        frappe.throw(_("Your internal portal access profile is not configured or disabled."), frappe.PermissionError)

    portal_user = get_portal_user(user)
    if not portal_user:
        frappe.throw(
            _("Your portal account is not configured. Ask your Customer Administrator to add your staff profile."),
            frappe.PermissionError,
        )

    return {
        "internal": False,
        "privileged": False,
        "customer": portal_user.erpnext_customer,
        "portal_customer": portal_user.portal_customer,
        "portal_user": portal_user.name,
        "department": portal_user.department,
        "service_department": None,
        "user_type": portal_user.user_type,
        "permissions": _permission_map(portal_user),
        "access_all_customers": False,
        "allowed_customers": [portal_user.portal_customer],
        "allowed_service_departments": [],
    }


def get_internal_portal_user(user: str | None = None):
    user = user or frappe.session.user
    if user in ("Guest", None) or is_privileged_user(user):
        return None
    if not frappe.db.exists("DocType", "Internal Portal User"):
        return None
    name = frappe.db.get_value("Internal Portal User", {"user": user, "enabled": 1}, "name")
    if not name:
        return None
    return frappe.get_cached_doc("Internal Portal User", name)


def get_portal_user(user: str | None = None):
    user = user or frappe.session.user
    if user in ("Guest", None) or is_frappe_system_user(user):
        return None

    name = frappe.db.get_value("Portal User", {"user": user, "enabled": 1}, "name")
    if not name:
        name = frappe.db.get_value("Portal User", {"email": user, "enabled": 1}, "name")
    if not name:
        return None

    portal_user = frappe.get_cached_doc("Portal User", name)
    if not portal_user.portal_customer:
        return None
    portal_customer = frappe.get_cached_doc("Portal Customer", portal_user.portal_customer)
    if portal_customer.status != "Active" or not _existing_customer(portal_customer.erpnext_customer):
        return None
    return portal_user


def has_portal_permission(permission: str, scope: dict | None = None) -> bool:
    scope = scope or get_portal_scope()
    if scope["privileged"]:
        return True
    if scope["user_type"] == CUSTOMER_READ_ONLY_TYPE and permission.startswith(("view_", "read_")):
        return True
    return bool(scope["permissions"].get(permission))


def require_portal_permission(permission: str, scope: dict | None = None):
    scope = scope or get_portal_scope()
    if not has_portal_permission(permission, scope):
        frappe.throw(_("Not permitted for this portal account."), frappe.PermissionError)
    return scope


def get_customer_linked_permission_query_conditions(user: str | None = None) -> str | None:
    if is_privileged_user(user):
        return None
    if get_internal_portal_user(user):
        return _internal_customer_condition(user)
    customer = get_user_customer(user)
    if not customer:
        return "1=0"
    doctype = frappe.local.form_dict.get("doctype") if getattr(frappe.local, "form_dict", None) else None
    return _condition_for_customer(doctype, customer)


def sales_invoice_query(user=None):
    return _query_for("Sales Invoice", user)


def sales_order_query(user=None):
    return _query_for("Sales Order", user)


def quotation_query(user=None):
    if is_privileged_user(user):
        return None
    if get_internal_portal_user(user):
        condition = _internal_customer_condition(user, "party_name", "Quotation")
        return "`tabQuotation`.`quotation_to` = 'Customer'" if condition is None else f"`tabQuotation`.`quotation_to` = 'Customer' and {condition}"
    customer = get_user_customer(user)
    if not customer:
        return "1=0"
    return f"`tabQuotation`.`quotation_to` = 'Customer' and `tabQuotation`.`party_name` = {frappe.db.escape(customer)}"


def delivery_note_query(user=None):
    return _query_for("Delivery Note", user)


def amc_contract_query(user=None):
    return _query_for("AMC Contract", user)


def network_device_query(user=None):
    return _query_for("Network Device", user)


def maintenance_schedule_query(user=None):
    return _query_for("Maintenance Schedule", user)


def customer_document_query(user=None):
    return _query_for("Customer Document", user)


def sla_report_query(user=None):
    return _query_for("SLA Report", user)


def get_payment_permission_query_conditions(user: str | None = None) -> str:
    if is_privileged_user(user):
        return None
    internal_user = get_internal_portal_user(user)
    if internal_user:
        customers = _internal_allowed_erp_customers(internal_user)
        if internal_user.access_all_customers:
            return None
        if not customers:
            return "1=0"
        escaped = ", ".join(frappe.db.escape(customer) for customer in customers)
        return (
            "exists (select 1 from `tabPayment Entry Reference` per "
            "left join `tabSales Invoice` si on si.name = per.reference_name and per.reference_doctype = 'Sales Invoice' "
            "left join `tabSales Order` so on so.name = per.reference_name and per.reference_doctype = 'Sales Order' "
            "where per.parent = `tabPayment Entry`.`name` "
            f"and coalesce(si.customer, so.customer) in ({escaped}))"
        )
    customer = get_user_customer(user)
    if not customer:
        return "1=0"
    return (
        "exists (select 1 from `tabPayment Entry Reference` per "
        "left join `tabSales Invoice` si on si.name = per.reference_name and per.reference_doctype = 'Sales Invoice' "
        "left join `tabSales Order` so on so.name = per.reference_name and per.reference_doctype = 'Sales Order' "
        "where per.parent = `tabPayment Entry`.`name` "
        f"and coalesce(si.customer, so.customer) = {frappe.db.escape(customer)})"
    )


def get_project_permission_query_conditions(user: str | None = None) -> str:
    if is_privileged_user(user):
        return None
    if get_internal_portal_user(user):
        return _internal_customer_condition(user, "customer", "Project")
    customer = get_user_customer(user)
    if not customer:
        return "1=0"
    return f"`tabProject`.`customer` = {frappe.db.escape(customer)}"


def get_ticket_permission_query_conditions(user: str | None = None) -> str:
    if is_privileged_user(user):
        return None
    internal_user = get_internal_portal_user(user)
    if internal_user:
        ticket_dt = "HD Ticket" if frappe.db.exists("DocType", "HD Ticket") else "Issue"
        customer_condition = _internal_customer_condition(user, "customer", ticket_dt)
        department_condition = (
            "exists (select 1 from `tabPortal Ticket Metadata` ptm "
            f"where ptm.ticket_doctype = {frappe.db.escape(ticket_dt)} "
            f"and ptm.ticket = `tab{ticket_dt}`.`name` "
            f"and ptm.service_department = {frappe.db.escape(internal_user.service_department)})"
        )
        if customer_condition is None:
            return department_condition
        return f"{customer_condition} and {department_condition}"
    customer = get_user_customer(user)
    if not customer:
        return "1=0"
    ticket_dt = "HD Ticket" if frappe.db.exists("DocType", "HD Ticket") else "Issue"
    if ticket_dt == "HD Ticket":
        return f"coalesce(`tabHD Ticket`.`customer`, '') = {frappe.db.escape(customer)}"
    return f"coalesce(`tabIssue`.`customer`, '') = {frappe.db.escape(customer)}"


def has_customer_permission(doc, user: str | None = None, permission_type: str | None = None) -> bool:
    if is_privileged_user(user):
        return True
    internal_user = get_internal_portal_user(user)
    if internal_user:
        scope = get_portal_scope(user)
        customer = _doc_customer(doc)
        if customer and not can_access_customer(scope, erpnext_customer=customer):
            return False
        if doc.doctype in ("HD Ticket", "Issue") and not can_access_ticket(doc.doctype, doc.name, scope):
            return False
        return bool(customer)
    customer = get_user_customer(user)
    if not customer:
        return False

    if doc.doctype == "Payment Entry":
        return _payment_belongs_to_customer(doc.name, customer)

    fieldname = CUSTOMER_FIELD_BY_DOCTYPE.get(doc.doctype)
    if fieldname and getattr(doc, fieldname, None):
        return getattr(doc, fieldname) == customer

    if doc.doctype == "Quotation":
        return getattr(doc, "quotation_to", None) == "Customer" and getattr(doc, "party_name", None) == customer

    return False


def can_manage_customer_staff(scope: dict, portal_customer: str | None = None) -> bool:
    if scope["privileged"]:
        return True
    if not has_portal_permission("manage_staff", scope):
        return False
    return not portal_customer or portal_customer == scope["portal_customer"]


def can_access_customer(scope: dict, erpnext_customer: str | None = None, portal_customer: str | None = None) -> bool:
    if scope["privileged"]:
        return True
    if portal_customer and not erpnext_customer:
        erpnext_customer = frappe.db.get_value("Portal Customer", portal_customer, "erpnext_customer")
    if erpnext_customer and not portal_customer:
        portal_customer = frappe.db.get_value("Portal Customer", {"erpnext_customer": erpnext_customer}, "name")
    if not erpnext_customer or not portal_customer:
        return False
    if scope["internal"]:
        return bool(scope["access_all_customers"] or portal_customer in scope["allowed_customers"])
    return erpnext_customer == scope["customer"] and portal_customer == scope["portal_customer"]


def can_access_service_department(scope: dict, service_department: str | None) -> bool:
    if scope["privileged"]:
        return True
    if not service_department:
        return False
    if scope["internal"]:
        return service_department in scope["allowed_service_departments"]
    return True


def can_access_ticket(ticket_doctype: str, ticket: str, scope: dict | None = None) -> bool:
    scope = scope or get_portal_scope()
    metadata = get_ticket_metadata(ticket_doctype, ticket)
    if metadata:
        return can_access_customer(scope, metadata.erpnext_customer, metadata.portal_customer) and can_access_service_department(
            scope, metadata.service_department
        )
    customer = frappe.db.get_value(ticket_doctype, ticket, "customer")
    return can_access_customer(scope, erpnext_customer=customer)


def get_ticket_metadata(ticket_doctype: str, ticket: str):
    if not frappe.db.exists("DocType", "Portal Ticket Metadata"):
        return None
    metadata = frappe.db.get_value("Portal Ticket Metadata", {"ticket_doctype": ticket_doctype, "ticket": ticket}, "name")
    return frappe.get_cached_doc("Portal Ticket Metadata", metadata) if metadata else None


def _condition_for_customer(doctype: str | None, customer: str) -> str:
    if not doctype or doctype not in CUSTOMER_FIELD_BY_DOCTYPE:
        return "1=0"
    fieldname = CUSTOMER_FIELD_BY_DOCTYPE[doctype]
    return f"`tab{doctype}`.`{fieldname}` = {frappe.db.escape(customer)}"


def _query_for(doctype: str, user: str | None = None) -> str:
    if is_privileged_user(user):
        return None
    if get_internal_portal_user(user):
        return _internal_customer_condition(user, CUSTOMER_FIELD_BY_DOCTYPE.get(doctype), doctype)
    customer = get_user_customer(user)
    if not customer:
        return "1=0"
    return _condition_for_customer(doctype, customer)


def _existing_customer(customer: str | None) -> str | None:
    if customer and frappe.db.exists("Customer", customer):
        return customer
    return None


def _permission_map(portal_user) -> dict:
    if portal_user.user_type == CUSTOMER_READ_ONLY_TYPE:
        return {"view_company_tickets": True, "view_reports": True, "view_sla_reports": True}
    permissions = {}

    if portal_user.permission_group:
        group = frappe.get_cached_doc("Portal Permission Group", portal_user.permission_group)
        if group.enabled:
            permissions.update(
                {
                    field.fieldname: bool(group.get(field.fieldname))
                    for field in group.meta.fields
                    if field.fieldtype == "Check"
                }
            )

    if portal_user.user_type == CUSTOMER_ADMIN_TYPE or portal_user.is_company_admin:
        permissions.update(
            {
                "create_ticket": True,
                "reply_ticket": True,
                "upload_attachments": True,
                "view_company_tickets": True,
                "view_quotations": True,
                "view_orders": True,
                "view_invoices": True,
                "view_payments": True,
                "view_projects": True,
                "view_reports": True,
                "view_sla_reports": True,
                "download_documents": True,
                "view_knowledge_base": True,
                "manage_staff": True,
                "manage_departments": True,
                "manage_permissions": True,
                "manage_notifications": True,
            }
        )
    return permissions


def _internal_permission_map(internal_user) -> dict:
    if not internal_user.permission_group:
        return {}
    group = frappe.get_cached_doc("Portal Permission Group", internal_user.permission_group)
    if not group.enabled:
        return {}
    return {
        field.fieldname: bool(group.get(field.fieldname))
        for field in group.meta.fields
        if field.fieldtype == "Check"
    }


def _internal_allowed_erp_customers(internal_user) -> list[str]:
    if internal_user.access_all_customers:
        return []
    customers = []
    for row in internal_user.allowed_customers:
        customer = frappe.db.get_value("Portal Customer", row.portal_customer, "erpnext_customer")
        if customer:
            customers.append(customer)
    return customers


def _internal_customer_condition(user=None, fieldname="customer", doctype=None):
    internal_user = get_internal_portal_user(user)
    if not internal_user:
        return "1=0"
    if internal_user.access_all_customers:
        return None
    customers = _internal_allowed_erp_customers(internal_user)
    if not customers:
        return "1=0"
    escaped = ", ".join(frappe.db.escape(customer) for customer in customers)
    if doctype:
        return f"`tab{doctype}`.`{fieldname}` in ({escaped})"
    return f"`{fieldname}` in ({escaped})"


def _doc_customer(doc) -> str | None:
    if doc.doctype == "Quotation":
        return getattr(doc, "party_name", None) if getattr(doc, "quotation_to", None) == "Customer" else None
    fieldname = CUSTOMER_FIELD_BY_DOCTYPE.get(doc.doctype)
    return getattr(doc, fieldname, None) if fieldname else None


def _payment_belongs_to_customer(payment_entry: str, customer: str) -> bool:
    refs = frappe.get_all(
        "Payment Entry Reference",
        filters={"parent": payment_entry, "reference_doctype": ["in", ["Sales Invoice", "Sales Order"]]},
        fields=["reference_doctype", "reference_name"],
    )
    for ref in refs:
        fieldname = "customer"
        linked_customer = frappe.db.get_value(ref.reference_doctype, ref.reference_name, fieldname)
        if linked_customer == customer:
            return True
    return False
