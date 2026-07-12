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
        "primary_color": getattr(settings, "primary_color", None) or "#0f766e",
        "secondary_color": getattr(settings, "secondary_color", None) or "#2563eb",
        "theme": getattr(settings, "theme", None) or "System",
        "portal_name": getattr(settings, "portal_name", None) or "Zentryx Customer Portal",
        "support_email": getattr(settings, "support_email", None),
        "support_phone": getattr(settings, "support_phone", None),
        "footer": getattr(settings, "footer", None),
        "security": {
            "enable_otp": bool(getattr(settings, "enable_otp", 0)),
            "enable_two_factor_authentication": bool(getattr(settings, "enable_two_factor_authentication", 0)),
            "enable_sso": bool(getattr(settings, "enable_sso", 0)),
            "session_timeout": getattr(settings, "session_timeout", 60),
            "login_attempts": getattr(settings, "login_attempts", 5),
            "ip_restrictions": getattr(settings, "ip_restrictions", None),
            "enable_audit_logs": bool(getattr(settings, "enable_audit_logs", 1)),
            "enable_login_history": bool(getattr(settings, "enable_login_history", 1)),
        },
        "notifications": {
            "email": bool(getattr(settings, "enable_email_notifications", 1)),
            "sms": bool(getattr(settings, "enable_sms_notifications", 0)),
            "whatsapp": bool(getattr(settings, "enable_whatsapp_notifications", 0)),
            "push": bool(getattr(settings, "enable_push_notifications", 0)),
            "telegram": bool(getattr(settings, "enable_telegram_notifications", 0)),
            "slack": bool(getattr(settings, "enable_slack_notifications", 0)),
        },
        "modules": {
            "projects": bool(getattr(settings, "enable_projects", 1)),
            "amc": bool(getattr(settings, "enable_amc", 1)),
            "network": bool(getattr(settings, "enable_network", 1)),
            "documents": bool(getattr(settings, "enable_documents", 1)),
            "payments": bool(getattr(settings, "enable_payments", 1)),
            "knowledge_base": bool(getattr(settings, "enable_knowledge_base", 1)),
        },
    }
