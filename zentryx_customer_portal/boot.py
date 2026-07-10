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
        "portal_name": settings.portal_name or "Zentryx Customer Portal",
        "support_email": settings.support_email,
        "support_phone": settings.support_phone,
        "footer": settings.footer,
        "security": {
            "enable_otp": bool(settings.enable_otp),
            "enable_two_factor_authentication": bool(settings.enable_two_factor_authentication),
            "enable_sso": bool(settings.enable_sso),
            "session_timeout": settings.session_timeout,
        },
        "modules": {
            "projects": bool(settings.enable_projects),
            "amc": bool(settings.enable_amc),
            "network": bool(settings.enable_network),
            "documents": bool(settings.enable_documents),
            "payments": bool(settings.enable_payments),
            "knowledge_base": bool(settings.enable_knowledge_base),
        },
    }
