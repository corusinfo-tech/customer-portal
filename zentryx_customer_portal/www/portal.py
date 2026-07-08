import frappe
from frappe import _


def get_context(context):
    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect-to=/portal"
        raise frappe.Redirect
    context.title = _("Portal")
    context.no_cache = 1
    context.show_sidebar = False
    context.boot = frappe.get_attr("zentryx_customer_portal.boot.get_portal_settings")()

