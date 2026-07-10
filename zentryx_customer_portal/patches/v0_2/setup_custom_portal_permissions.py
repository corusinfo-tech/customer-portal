import frappe

from zentryx_customer_portal.install import ensure_permission_groups, ensure_settings
from zentryx_customer_portal.sync import migrate_existing_portal_users


def execute():
    ensure_settings()
    ensure_permission_groups()
    if frappe.db.exists("DocType", "Portal Customer") and frappe.db.exists("DocType", "Portal User"):
        migrate_existing_portal_users()

