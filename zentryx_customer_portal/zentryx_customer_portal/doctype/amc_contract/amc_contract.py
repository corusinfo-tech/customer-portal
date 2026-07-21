import frappe
from frappe.model.document import Document


class AMCContract(Document):
    def validate(self):
        if self.end_date and self.start_date and self.end_date < self.start_date:
            frappe.throw("End Date cannot be before Start Date.")

