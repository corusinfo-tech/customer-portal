import frappe


def get_website_user_home_page(user=None):
    user = user or frappe.session.user
    if user and user not in ("Guest", "Administrator"):
        return "/portal"
    return "/login"


def get_bootinfo(bootinfo):
    if frappe.session.user == "Guest":
        return
    bootinfo.zentryx_customer_portal = {
        "home_page": "/portal",
        "settings": get_portal_settings(),
    }


def get_portal_settings():
    if not frappe.db.exists("DocType", "Customer Portal Settings"):
        return {}
    settings = frappe.get_single("Customer Portal Settings")
    return {
        "primary_color": settings.primary_color or "#0f766e",
        "secondary_color": settings.secondary_color or "#2563eb",
        "theme": settings.theme or "System",
        "support_contact": settings.support_contact,
        "footer": settings.footer,
        "modules": {
            "projects": bool(settings.enable_projects),
            "amc": bool(settings.enable_amc),
            "network": bool(settings.enable_network),
            "documents": bool(settings.enable_documents),
            "payments": bool(settings.enable_payments),
            "knowledge_base": bool(settings.enable_knowledge_base),
        },
    }

