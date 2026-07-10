import frappe


def after_install():
    ensure_role()
    ensure_settings()
    ensure_permission_groups()


def ensure_role():
    if not frappe.db.exists("Role", "Customer Portal Manager"):
        role = frappe.new_doc("Role")
        role.role_name = "Customer Portal Manager"
        role.desk_access = 1
        role.insert(ignore_permissions=True)


def ensure_settings():
    if frappe.db.exists("DocType", "Customer Portal Settings"):
        settings = frappe.get_single("Customer Portal Settings")
        settings.enable_projects = 1
        settings.enable_amc = 1
        settings.enable_network = 1
        settings.enable_documents = 1
        settings.enable_payments = 1
        settings.enable_knowledge_base = 1
        settings.sync_erp_customers = 1
        settings.sync_contacts = 1
        settings.sync_addresses = 1
        settings.auto_sync = 1
        settings.theme = settings.theme or "System"
        settings.portal_name = settings.portal_name or "Zentryx Customer Portal"
        settings.primary_color = settings.primary_color or "#0f766e"
        settings.secondary_color = settings.secondary_color or "#2563eb"
        settings.landing_page = settings.landing_page or "/portal"
        settings.save(ignore_permissions=True)


def ensure_permission_groups():
    groups = {
        "Ticket User": {
            "create_ticket": 1,
            "reply_ticket": 1,
            "upload_attachments": 1,
            "view_own_tickets": 1,
            "view_knowledge_base": 1,
        },
        "Ticket Manager": {
            "create_ticket": 1,
            "reply_ticket": 1,
            "upload_attachments": 1,
            "view_company_tickets": 1,
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
