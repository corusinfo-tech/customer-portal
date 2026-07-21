import frappe
from frappe.tests.utils import FrappeTestCase

from zentryx_customer_portal.permissions import get_portal_scope, has_portal_permission


class TestDepartmentAccess(FrappeTestCase):
    def test_unconfigured_system_user_is_denied(self):
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": "unconfigured.portal.internal@example.com",
                "first_name": "Unconfigured",
                "user_type": "System User",
                "enabled": 1,
            }
        ).insert(ignore_permissions=True)
        with self.assertRaises(frappe.PermissionError):
            get_portal_scope(user.name)

    def test_read_only_user_cannot_create_ticket(self):
        scope = {
            "internal": False,
            "privileged": False,
            "user_type": "Customer Read Only",
            "permissions": {"read_only": True},
        }
        self.assertFalse(has_portal_permission("create_ticket", scope))
        self.assertTrue(has_portal_permission("view_reports", scope))

