"""Customer-ranking regression tests using synthetic workbook data only."""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import openpyxl


SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "ecom" / "refresh.py"
SPEC = importlib.util.spec_from_file_location("ecom_refresh", SOURCE)
refresh = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(refresh)

HEADERS = ["OrderNumber", "SuborderNumber", "DeliveryTime", "CreatedOn", "SubordeStatus",
           "Outlet Code", "Outlet Name", "SubOrderTotal", "CustomerName", "ProductName", "Price"]


def order(parent, sub, name=None, outlet="A", total=100, status="Delivered", day="10/5/2026"):
    return {"OrderNumber": parent, "SuborderNumber": sub, "DeliveryTime": f"09:00 AM - 10:00 AM {day}",
            "CreatedOn": "Oct 01, 2026, 9:00:00 AM", "SubordeStatus": status, "Outlet Code": outlet,
            "Outlet Name": f"Synthetic outlet {outlet}", "SubOrderTotal": total, "CustomerName": name,
            "ProductName": "Synthetic product", "Price": total}


class CustomerRankingTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory(prefix="test-ecom-customers-")
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)

    def build(self, books, headers=HEADERS):
        for filename, records in books.items():
            wb = openpyxl.Workbook(write_only=True)
            ws = wb.create_sheet()
            ws.append(headers)
            for record in records:
                ws.append([record.get(h) for h in headers])
            wb.save(self.root / filename)
            wb.close()
        output = self.root / "result.json"
        with mock.patch.object(refresh, "OUT", output), \
                mock.patch.object(refresh, "MASTER", self.root / "missing-master.json"), \
                mock.patch.object(sys, "argv", [str(SOURCE), "--local", str(self.root)]), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(refresh.main(), 0)
        return json.loads(output.read_text())

    def test_products_suborders_and_exports_do_not_inflate_parent_orders(self):
        data = self.build({
            "a-old.xlsx": [order("P1", "S1", "Former Synthetic Name", total=999, day="7/1/2026")],
            "b-new.xlsx": [order("P1", "S1", None, total=120),
                           order("P1", "S1", "  Test   Alpha  ", total=120),
                           order("P1", "S2", "TEST ALPHA", outlet="B", total=30),
                           order("P1", "S3", None, total=20),
                           order("P2", "S4", "Test Alpha", total=200, status="Cancelled"),
                           order("P3", "S5", "Test Beta", total=60)],
        })
        self.assertEqual(data["schema"], 3)
        self.assertEqual(data["customers"]["kind"], "name")
        self.assertEqual(data["customers"]["list"], ["Test Alpha", "Test Beta"])
        self.assertEqual(data["months"], ["2026-10"])
        alpha = [r for r in data["customers"]["r"] if r[2] == 0]
        self.assertEqual(len({r[3] for r in alpha}), 2)
        self.assertEqual(sum(r[4] for r in alpha), 4)
        self.assertEqual(sum(r[5] for r in alpha), 170)
        p1_a = [r for r in alpha if r[3] == "P1" and data["outlets"][r[0]][0] == "A"]
        self.assertEqual([r[4:] for r in p1_a], [[2, 140]])
        # The same parent appears in both outlet scopes, so summing outlet order counts is incorrect.
        self.assertEqual(len(alpha), 3)
        self.assertEqual(sum(data["daily"]["n"]), 5)

    def test_conflicting_product_or_suborder_names_exclude_the_whole_parent(self):
        data = self.build({"orders.xlsx": [
            order("P1", "S1", "Test Alpha"), order("P1", "S1", "Test Beta"),
            order("P1", "S2", None, outlet="B"),
            order("P2", "S3", "Test Gamma"), order("P2", "S4", "Test Delta", outlet="B"),
            order("P3", "S5", "Control Example"),
        ]})
        self.assertEqual(data["customers"]["list"], ["Control Example"])
        for parent in ("P1", "P2"):
            rows = [r for r in data["customers"]["r"] if r[3] == parent]
            self.assertTrue(rows)
            self.assertTrue(all(r[2] == -2 for r in rows))
        self.assertEqual(sum(r[4] for r in data["customers"]["r"]), 5)

    def test_missing_names_inherit_only_one_known_parent_identity(self):
        data = self.build({"orders.xlsx": [
            order("P1", "S1", None), order("P1", "S1", "Known Example"),
            order("P1", "S2", None, outlet="B"),
            order("P2", "S3", "unknown"), order("P2", "S4", "Guest", outlet="B"),
            order("P3", "S5", "qa@example.invalid"), order("P3", "S5", "+8801712345678"),
        ]})
        self.assertEqual(data["customers"]["list"], ["Known Example"])
        self.assertTrue(all(r[2] == 0 for r in data["customers"]["r"] if r[3] == "P1"))
        self.assertTrue(all(r[2] == -1 for r in data["customers"]["r"] if r[3] in {"P2", "P3"}))
        self.assertEqual(sum(r[4] for r in data["customers"]["r"]), 5)

    def test_unicode_case_whitespace_and_contact_masking(self):
        data = self.build({"orders.xlsx": [
            order("P1", "S1", "  Café   Example  "), order("P2", "S2", "CAFE\u0301 EXAMPLE"),
            order("P3", "S3", "0"), order("P4", "S4", "00123 Example"),
            order("P5", "S5", "Straße Example"), order("P6", "S6", "STRASSE EXAMPLE"),
            order("P7", "S7", "Contact Example +8801712345678 qa@example.invalid"),
        ]})
        names = data["customers"]["list"]
        self.assertEqual(len(names), 5)
        self.assertEqual(names[0], "Café Example")
        self.assertIn("0", names)
        self.assertIn("00123 Example", names)
        by_parent = {r[3]: r[2] for r in data["customers"]["r"]}
        self.assertEqual(by_parent["P1"], by_parent["P2"])
        self.assertEqual(by_parent["P5"], by_parent["P6"])
        serialized = json.dumps(data["customers"])
        self.assertNotIn("01712345678", serialized)
        self.assertNotIn("qa@example.invalid", serialized)
        self.assertIn("[number]", serialized)
        self.assertIn("[email]", serialized)

    def test_parent_membership_preserves_month_and_outlet_filters(self):
        data = self.build({"orders.xlsx": [
            order("P1", "S1", "Test Alpha", day="7/1/2026", total=40),
            order("P1", "S2", None, outlet="B", day="10/5/2026", total=60),
            order("P2", "S3", "Test Alpha", outlet="B", day="10/5/2026", total=80),
        ]})
        rows = data["customers"]["r"]
        self.assertEqual(len({r[3] for r in rows}), 2)
        july = data["months"].index("2026-07")
        october = data["months"].index("2026-10")
        self.assertEqual(len({r[3] for r in rows if r[1] == july}), 1)
        self.assertEqual(len({r[3] for r in rows if r[1] == october}), 2)
        self.assertTrue(all(r[2] == 0 for r in rows))

    def test_exports_without_customer_name_report_missing_coverage(self):
        headers = [h for h in HEADERS if h != "CustomerName"]
        data = self.build({"orders.xlsx": [order("P1", "S1"), order("P2", "S2")]}, headers=headers)
        self.assertEqual(data["customers"]["list"], [])
        self.assertEqual([r[2] for r in data["customers"]["r"]], [-1, -1])


if __name__ == "__main__":
    unittest.main()
