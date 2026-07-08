import frappe


def after_install():
    ensure_role()
    ensure_settings()


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
        settings.theme = settings.theme or "System"
        settings.primary_color = settings.primary_color or "#0f766e"
        settings.secondary_color = settings.secondary_color or "#2563eb"
        settings.landing_page = settings.landing_page or "/portal"
        settings.save(ignore_permissions=True)

