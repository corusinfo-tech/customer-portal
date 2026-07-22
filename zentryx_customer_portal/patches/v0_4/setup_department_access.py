import frappe

from zentryx_customer_portal.install import ensure_permission_groups, ensure_service_departments


def execute():
    ensure_service_departments()
    ensure_permission_groups()
    _add_indexes()


def _add_indexes():
    indexes = [
        ("Portal Ticket Metadata", ["ticket_doctype", "ticket"]),
        ("Portal Ticket Metadata", ["portal_customer", "service_department", "duplicate_status"]),
        ("Portal Ticket Metadata", ["erpnext_customer", "service_department"]),
        ("Internal Portal User", ["user", "enabled"]),
        ("Portal User", ["portal_customer", "department", "enabled"]),
    ]
    for doctype, fields in indexes:
        if frappe.db.exists("DocType", doctype):
            try:
                frappe.db.add_index(doctype, fields)
            except Exception:
                # add_index is idempotent across most backends; ignore duplicate index errors.
                pass

