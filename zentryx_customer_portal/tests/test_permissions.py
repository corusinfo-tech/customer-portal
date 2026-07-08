import unittest

from zentryx_customer_portal import permissions


class TestPermissionConditions(unittest.TestCase):
    def test_customer_scoped_query_blocks_unlinked_users(self):
        condition = permissions.sales_invoice_query("missing@example.com")
        self.assertEqual(condition, "1=0")

    def test_quotation_condition_blocks_unlinked_users(self):
        condition = permissions.quotation_query("missing@example.com")
        self.assertEqual(condition, "1=0")

    def test_known_customer_condition_uses_customer_field(self):
        condition = permissions._condition_for_customer("Sales Invoice", "CUST-0001")
        self.assertIn("`tabSales Invoice`.`customer`", condition)
        self.assertIn("CUST-0001", condition)

