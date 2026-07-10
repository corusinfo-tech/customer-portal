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
CUSTOMER_ADMIN_TYPE = "Customer Company Administrator"
CUSTOMER_STAFF_TYPE = "Customer Staff"
CUSTOMER_READ_ONLY_TYPE = "Customer Read Only"


def is_internal_user(user: str | None = None) -> bool:
    user = user or frappe.session.user
    if user == "Administrator":
        return True
    if user in ("Guest", None):
        return False
    return frappe.db.get_value("User", user, "user_type") in INTERNAL_USER_TYPES


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
    if is_internal_user(user):
        return {
            "internal": True,
            "customer": None,
            "portal_customer": None,
            "portal_user": None,
            "department": None,
            "user_type": "Internal",
            "permissions": {},
        }

    portal_user = get_portal_user(user)
    if not portal_user:
        frappe.throw(
            _("Your portal account is not configured. Ask your Customer Administrator to add your staff profile."),
            frappe.PermissionError,
        )

    return {
        "internal": False,
        "customer": portal_user.erpnext_customer,
        "portal_customer": portal_user.portal_customer,
        "portal_user": portal_user.name,
        "department": portal_user.department,
        "user_type": portal_user.user_type,
        "permissions": _permission_map(portal_user),
    }


def get_portal_user(user: str | None = None):
    user = user or frappe.session.user
    if user in ("Guest", None) or is_internal_user(user):
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
    if scope["internal"]:
        return True
    if scope["user_type"] == CUSTOMER_ADMIN_TYPE:
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
    if is_internal_user(user):
        return None
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
    if is_internal_user(user):
        return None
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
    if is_internal_user(user):
        return None
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
    if is_internal_user(user):
        return None
    customer = get_user_customer(user)
    if not customer:
        return "1=0"
    return f"`tabProject`.`customer` = {frappe.db.escape(customer)}"


def get_ticket_permission_query_conditions(user: str | None = None) -> str:
    if is_internal_user(user):
        return None
    customer = get_user_customer(user)
    if not customer:
        return "1=0"
    ticket_dt = "HD Ticket" if frappe.db.exists("DocType", "HD Ticket") else "Issue"
    if ticket_dt == "HD Ticket":
        return f"coalesce(`tabHD Ticket`.`customer`, '') = {frappe.db.escape(customer)}"
    return f"coalesce(`tabIssue`.`customer`, '') = {frappe.db.escape(customer)}"


def has_customer_permission(doc, user: str | None = None, permission_type: str | None = None) -> bool:
    if is_internal_user(user):
        return True
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
    if scope["internal"]:
        return True
    if not has_portal_permission("manage_staff", scope):
        return False
    return not portal_customer or portal_customer == scope["portal_customer"]


def _condition_for_customer(doctype: str | None, customer: str) -> str:
    if not doctype or doctype not in CUSTOMER_FIELD_BY_DOCTYPE:
        return "1=0"
    fieldname = CUSTOMER_FIELD_BY_DOCTYPE[doctype]
    return f"`tab{doctype}`.`{fieldname}` = {frappe.db.escape(customer)}"


def _query_for(doctype: str, user: str | None = None) -> str:
    if is_internal_user(user):
        return None
    customer = get_user_customer(user)
    if not customer:
        return "1=0"
    return _condition_for_customer(doctype, customer)


def _existing_customer(customer: str | None) -> str | None:
    if customer and frappe.db.exists("Customer", customer):
        return customer
    return None


def _permission_map(portal_user) -> dict:
    if portal_user.user_type == CUSTOMER_ADMIN_TYPE or portal_user.is_company_admin:
        return {"manage_staff": True, "view_company_tickets": True, "create_ticket": True, "reply_ticket": True}
    if portal_user.user_type == CUSTOMER_READ_ONLY_TYPE:
        return {"view_company_tickets": True, "view_reports": True, "view_sla_reports": True}
    if not portal_user.permission_group:
        return {}

    group = frappe.get_cached_doc("Portal Permission Group", portal_user.permission_group)
    if not group.enabled:
        return {}
    return {
        field.fieldname: bool(group.get(field.fieldname))
        for field in group.meta.fields
        if field.fieldtype == "Check"
    }


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
