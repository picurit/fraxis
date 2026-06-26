# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

"""
Collection-level DocType service layer.

Invoked through ``run_frappe`` (own connection / transaction / identity). The page size
is clamped by the caller (services.validation.clamp_limit); ``fields`` and ``order_by``
are positively allowlisted here against the DocType's valid columns
(``get_valid_columns``) before reaching ``frappe.client.get_list`` — Frappe only
blacklists injection patterns, so the allowlist is what bounds the query surface
(analysis §7.3 / S1-3). ``filters`` are parameterized by Frappe's query builder. This
layer also enforces read permission for the authenticated user.
"""

from typing import Optional

import frappe

from fraxis.services.validation import validate_fields, validate_order_by


def list_documents(
    doctype: str,
    filters=None,
    fields=None,
    limit: int = 20,
    limit_start: int = 0,
    order_by: Optional[str] = None,
) -> list:
    if not frappe.has_permission(doctype, ptype="read"):
        raise frappe.PermissionError(f"No read permission on {doctype}")
    allowed = set(frappe.get_meta(doctype).get_valid_columns())
    fields = validate_fields(fields, allowed)
    order_by = validate_order_by(order_by, allowed)
    return frappe.client.get_list(
        doctype,
        filters=filters,
        fields=fields,
        limit_page_length=limit,
        limit_start=limit_start,
        order_by=order_by,
    )


def count_documents(doctype: str, filters=None) -> int:
    if not frappe.has_permission(doctype, ptype="read"):
        raise frappe.PermissionError(f"No read permission on {doctype}")
    return frappe.db.count(doctype, filters=filters)


def get_doctype_meta(doctype: str) -> dict:
    if not frappe.has_permission(doctype, ptype="read"):
        raise frappe.PermissionError(f"No read permission on {doctype}")
    return frappe.get_meta(doctype).as_dict()


def assert_read_permission(doctype: str) -> dict:
    if not frappe.has_permission(doctype, ptype="read"):
        raise frappe.PermissionError(f"No read permission on {doctype}")
    return {"doctype": doctype}
