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


def is_internal_user(user: str | None = None) -> bool:
    user = user or frappe.session.user
    if user == "Administrator":
        return True
    if user in ("Guest", None):
        return False
    return frappe.db.get_value("User", user, "user_type") in INTERNAL_USER_TYPES


def get_user_customer(user: str | None = None) -> str | None:
    user = user or frappe.session.user
    if user == "Guest" or is_internal_user(user):
        return None

    contact = frappe.db.get_value("Contact", {"email_id": user}, "name")
    if not contact:
        dynamic_link = frappe.qb.DocType("Dynamic Link")
        rows = (
            frappe.qb.from_(dynamic_link)
            .select(dynamic_link.link_name)
            .where(dynamic_link.parenttype == "Contact")
            .where(dynamic_link.link_doctype == "Customer")
            .where(dynamic_link.parent.isin(
                frappe.get_all("Contact Email", filters={"email_id": user}, pluck="parent")
            ))
            .limit(1)
        ).run(as_dict=True)
        return _existing_customer(rows[0].link_name) if rows else None

    link = frappe.db.get_value(
        "Dynamic Link",
        {"parenttype": "Contact", "parent": contact, "link_doctype": "Customer"},
        "link_name",
    )
    return _existing_customer(link)


def require_customer(user: str | None = None) -> str:
    customer = get_user_customer(user)
    if not customer:
        frappe.throw(
            _("Your portal account is not linked to an active Customer. Ask your administrator to link your Contact to a valid Customer."),
            frappe.PermissionError,
        )
    return customer


def get_portal_scope(user: str | None = None) -> dict:
    user = user or frappe.session.user
    if is_internal_user(user):
        return {"internal": True, "customer": None}
    return {"internal": False, "customer": require_customer(user)}


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
