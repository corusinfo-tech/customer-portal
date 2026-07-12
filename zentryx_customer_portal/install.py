import frappe


def after_install():
    ensure_role()
    ensure_settings()
    ensure_permission_groups()


def after_migrate():
    ensure_role()
    ensure_settings()
    ensure_permission_groups()
    sync_existing_master_data()


def ensure_role():
    if not frappe.db.exists("Role", "Customer Portal Manager"):
        role = frappe.new_doc("Role")
        role.role_name = "Customer Portal Manager"
        role.desk_access = 1
        role.insert(ignore_permissions=True)


def ensure_settings():
    if frappe.db.exists("DocType", "Customer Portal Settings"):
        settings = frappe.get_single("Customer Portal Settings")
        _set_if_field(settings, "enable_projects", 1)
        _set_if_field(settings, "enable_amc", 1)
        _set_if_field(settings, "enable_network", 1)
        _set_if_field(settings, "enable_documents", 1)
        _set_if_field(settings, "enable_payments", 1)
        _set_if_field(settings, "enable_knowledge_base", 1)
        _set_if_field(settings, "sync_erp_customers", 1)
        _set_if_field(settings, "sync_contacts", 1)
        _set_if_field(settings, "sync_addresses", 1)
        _set_if_field(settings, "sync_companies", 1)
        _set_if_field(settings, "auto_sync", 1)
        _set_if_field(settings, "enable_email_notifications", 1)
        _set_if_field(settings, "enable_audit_logs", 1)
        _set_if_field(settings, "enable_login_history", 1)
        _set_default_if_field(settings, "theme", "System")
        _set_default_if_field(settings, "portal_name", "Zentryx Customer Portal")
        _set_default_if_field(settings, "primary_color", "#0f766e")
        _set_default_if_field(settings, "secondary_color", "#2563eb")
        _set_default_if_field(settings, "landing_page", "/portal")
        _set_default_if_field(settings, "login_attempts", 5)
        _set_default_if_field(settings, "session_timeout", 60)
        settings.save(ignore_permissions=True)


def ensure_permission_groups():
    if not frappe.db.exists("DocType", "Portal Permission Group"):
        return
    groups = {
        "Ticket User": {
            "create_ticket": 1,
            "reply_ticket": 1,
            "upload_attachments": 1,
            "view_own_tickets": 1,
            "view_knowledge_base": 1,
            "download_documents": 1,
        },
        "Ticket Manager": {
            "create_ticket": 1,
            "reply_ticket": 1,
            "upload_attachments": 1,
            "view_company_tickets": 1,
            "view_knowledge_base": 1,
            "download_documents": 1,
            "assign_ticket": 1,
            "escalate_ticket": 1,
            "close_ticket": 1,
            "merge_ticket": 1,
            "reopen_ticket": 1,
        },
        "Accounts": {
            "view_quotations": 1,
            "view_orders": 1,
            "view_invoices": 1,
            "view_payments": 1,
        },
        "Projects": {
            "view_projects": 1,
            "view_tasks": 1,
            "view_timesheets": 1,
        },
        "Reports": {
            "view_reports": 1,
            "view_sla_reports": 1,
            "view_customer_analytics": 1,
        },
        "Customer Read Only": {
            "read_only": 1,
            "view_company_tickets": 1,
            "view_reports": 1,
            "view_sla_reports": 1,
            "download_documents": 1,
        },
        "Customer Administrator": {
            "create_ticket": 1,
            "reply_ticket": 1,
            "upload_attachments": 1,
            "view_company_tickets": 1,
            "view_quotations": 1,
            "view_orders": 1,
            "view_invoices": 1,
            "view_payments": 1,
            "view_projects": 1,
            "view_reports": 1,
            "view_sla_reports": 1,
            "download_documents": 1,
            "view_knowledge_base": 1,
            "manage_staff": 1,
            "manage_departments": 1,
            "manage_permissions": 1,
            "manage_notifications": 1,
        },
    }
    for group_name, values in groups.items():
        if frappe.db.exists("Portal Permission Group", group_name):
            continue
        doc = frappe.new_doc("Portal Permission Group")
        doc.name = group_name
        doc.group_name = group_name
        doc.enabled = 1
        for fieldname, value in values.items():
            if hasattr(doc, fieldname):
                setattr(doc, fieldname, value)
        doc.insert(ignore_permissions=True)


def sync_existing_master_data():
    if not (
        frappe.db.exists("DocType", "Portal Customer")
        and frappe.db.exists("DocType", "Portal User")
        and frappe.db.exists("DocType", "Portal Sync Log")
    ):
        return
    from zentryx_customer_portal.sync import migrate_existing_portal_users

    migrate_existing_portal_users()


def _set_if_field(doc, fieldname, value):
    if doc.meta.has_field(fieldname):
        doc.set(fieldname, value)


def _set_default_if_field(doc, fieldname, value):
    if doc.meta.has_field(fieldname) and not doc.get(fieldname):
        doc.set(fieldname, value)
