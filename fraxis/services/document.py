# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""
Document CRUD service layer.

Each function is a single unit of work invoked through ``run_frappe`` — it executes in a
worker thread that owns the connection, transaction and ``set_user`` identity, so the
permission checks here are evaluated against the authenticated user (analysis §6.2, §7).
Functions never call ``frappe.db.commit()``: the executor commits on success and rolls
back on error.
"""

from typing import Optional

import frappe


def create_document(doctype: str, data: Optional[dict]) -> dict:
    if not frappe.has_permission(doctype, ptype="create"):
        raise frappe.PermissionError(f"No create permission on {doctype}")
    doc = frappe.new_doc(doctype)
    doc.update(data or {})
    doc.insert()
    return doc.as_dict()


def read_document(doctype: str, name: str) -> dict:
    if not frappe.has_permission(doctype, doc=name, ptype="read"):
        raise frappe.PermissionError(f"No read permission on {doctype} {name}")
    return frappe.get_doc(doctype, name).as_dict()


def update_document(doctype: str, name: str, data: Optional[dict]) -> dict:
    if not frappe.has_permission(doctype, doc=name, ptype="write"):
        raise frappe.PermissionError(f"No write permission on {doctype} {name}")
    doc = frappe.get_doc(doctype, name)
    doc.update(data or {})
    doc.save()
    return doc.as_dict()


def delete_document(doctype: str, name: str) -> dict:
    if not frappe.has_permission(doctype, doc=name, ptype="delete"):
        raise frappe.PermissionError(f"No delete permission on {doctype} {name}")
    frappe.delete_doc(doctype, name)
    return {"name": name}


def assert_read_permission(doctype: str, name: Optional[str] = None) -> dict:
    """Permission gate for subscription handlers; returns a small confirmation payload."""
    if not frappe.has_permission(doctype, doc=name, ptype="read"):
        target = f"{doctype} {name}" if name else doctype
        raise frappe.PermissionError(f"No read permission on {target}")
    return {"doctype": doctype, "name": name}
