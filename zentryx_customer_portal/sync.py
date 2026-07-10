from __future__ import annotations

import frappe
from frappe.utils import now_datetime


def sync_all(sync_type="Manual"):
    log = _start_log(sync_type)
    created = 0
    updated = 0
    try:
        result = sync_customers()
        created += result["created"]
        updated += result["updated"]
        contact_result = sync_contacts()
        created += contact_result["created"]
        updated += contact_result["updated"]
        _finish_log(log, "Completed", created, updated, "Customer and contact sync completed.")
        return {"created": created, "updated": updated}
    except Exception as exc:
        _finish_log(log, "Failed", created, updated, frappe.get_traceback())
        raise exc


def sync_customers():
    created = 0
    updated = 0
    customers = frappe.get_all(
        "Customer",
        fields=["name", "customer_name", "customer_group", "territory", "disabled"],
        order_by="modified asc",
    )
    for row in customers:
        portal_name = frappe.db.get_value("Portal Customer", {"erpnext_customer": row.name}, "name")
        if portal_name:
            doc = frappe.get_doc("Portal Customer", portal_name)
            updated += 1
        else:
            doc = frappe.new_doc("Portal Customer")
            doc.erpnext_customer = row.name
            created += 1
        doc.customer_name = row.customer_name or row.name
        doc.customer_group = row.customer_group
        doc.territory = row.territory
        doc.status = "Disabled" if row.disabled else "Active"
        doc.last_synced_on = now_datetime()
        doc.sync_status = "Synced"
        doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"created": created, "updated": updated}


def sync_contacts():
    created = 0
    updated = 0
    contact_names = frappe.get_all("Contact", pluck="name")
    for contact_name in contact_names:
        contact = frappe.get_doc("Contact", contact_name)
        email = _contact_email(contact)
        customer = _contact_customer(contact.name)
        if not email or not customer:
            continue

        portal_customer = frappe.db.get_value("Portal Customer", {"erpnext_customer": customer}, "name")
        if not portal_customer:
            continue

        portal_user_name = frappe.db.get_value("Portal User", {"email": email}, "name")
        if portal_user_name:
            portal_user = frappe.get_doc("Portal User", portal_user_name)
            updated += 1
        else:
            portal_user = frappe.new_doc("Portal User")
            portal_user.email = email
            portal_user.user = frappe.db.get_value("User", {"email": email}, "name")
            portal_user.user_type = "Customer Staff"
            portal_user.enabled = 1
            created += 1

        portal_user.full_name = contact.full_name or contact.first_name or email
        portal_user.portal_customer = portal_customer
        portal_user.contact = contact.name
        if not portal_user.permission_group:
            portal_user.permission_group = _default_permission_group()
        portal_user.save(ignore_permissions=True)
    frappe.db.commit()
    return {"created": created, "updated": updated}


def migrate_existing_portal_users():
    return sync_all("Migration")


def scheduled_sync():
    if not frappe.db.exists("DocType", "Customer Portal Settings"):
        return
    settings = frappe.get_single("Customer Portal Settings")
    if settings.auto_sync:
        sync_all("Scheduled")


def _contact_email(contact):
    if getattr(contact, "email_id", None):
        return contact.email_id
    for row in getattr(contact, "email_ids", []) or []:
        if row.email_id:
            return row.email_id
    return None


def _contact_customer(contact_name):
    return frappe.db.get_value(
        "Dynamic Link",
        {"parenttype": "Contact", "parent": contact_name, "link_doctype": "Customer"},
        "link_name",
    )


def _default_permission_group():
    return frappe.db.get_value("Portal Permission Group", {"group_name": "Ticket User"}, "name")


def _start_log(sync_type):
    doc = frappe.new_doc("Portal Sync Log")
    doc.sync_type = sync_type
    doc.status = "Started"
    doc.started_on = now_datetime()
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return doc.name


def _finish_log(log_name, status, created, updated, message):
    doc = frappe.get_doc("Portal Sync Log", log_name)
    doc.status = status
    doc.finished_on = now_datetime()
    doc.records_created = created
    doc.records_updated = updated
    doc.message = message
    doc.save(ignore_permissions=True)
    frappe.db.commit()

