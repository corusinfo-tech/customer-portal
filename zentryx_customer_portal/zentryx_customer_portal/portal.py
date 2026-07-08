from frappe import _


def get_context(context):
    context.title = _("Customer Portal")
    context.no_cache = 1
    context.show_sidebar = False
    return context

