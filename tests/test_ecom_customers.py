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

    def test_history_keeps_actual_suborders_dates_statuses_and_amounts(self):
        data = self.build({
            "a-old.xlsx": [order("P1", "S1", "Synthetic Alpha", total=999, day="7/1/2026")],
            "b-new.xlsx": [order("P1", "S1", "Synthetic Alpha", total=125),
                           order("P1", "S1", "Synthetic Alpha", total=125),
                           order("P1", "S2", None, outlet="B", total=75, status="Cancelled"),
                           order("P2", "S3", None, total=40),
                           order("P3", "S4", "Synthetic Beta", total=25),
                           order("P3", "S5", "Synthetic Gamma", total=35)],
        })
        customers = data["customers"]
        self.assertEqual(customers["historyVersion"], 1)
        self.assertEqual(customers["historyStatusBasis"], "latest-export")
        self.assertEqual(customers["asOf"], "2026-10-01")
        self.assertEqual(len(customers["history"]), 5)
        self.assertEqual(customers["historyCoverage"]["records"], 5)
        self.assertTrue(all(len(r) == 9 for r in customers["history"]))
        history = {r[3]: r for r in customers["history"]}
        self.assertEqual(history["S1"][1:6], [0, "P1", "S1", "2026-10-01", "2026-10-05"])
        self.assertEqual(history["S1"][7:], [125, 125])
        self.assertEqual(history["S2"][7:], [75, 0])
        self.assertEqual(history["S2"][1], 0)
        self.assertEqual(data["outlets"][history["S2"][0]][0], "B")
        self.assertEqual(customers["statuses"][history["S2"][6]], "Cancelled")
        self.assertEqual(history["S3"][1], -1)
        self.assertEqual([history[s][1] for s in ("S4", "S5")], [-2, -2])
        self.assertEqual(sum(r[8] for r in customers["history"]), sum(r[5] for r in customers["r"]))

    def test_history_reference_date_uses_placement_not_future_slot_or_build_date(self):
        early = order("P1", "S1", "Synthetic Alpha", day="11/3/2026")
        late = order("P1", "S2", None, outlet="B", day="11/3/2026")
        early["CreatedOn"] = "Oct 07, 2026, 9:00:00 AM"
        late["CreatedOn"] = "Oct 08, 2026, 9:00:00 AM"
        data = self.build({"orders.xlsx": [early, late]})
        self.assertEqual(data["source"]["asOf"], "2026-10-08 09:00")
        self.assertEqual(data["customers"]["asOf"], "2026-10-08")
        self.assertEqual({r[4] for r in data["customers"]["history"]}, {"2026-10-07", "2026-10-08"})
        self.assertTrue(all(r[5] == "2026-11-03" for r in data["customers"]["history"]))

    def test_history_preserves_fractional_taka_before_aggregate_rounding(self):
        data = self.build({"orders.xlsx": [
            order("P1", "S1", "Synthetic Alpha", total=100.49),
            order("P1", "S2", "Synthetic Alpha", total=100.49),
            order("P1", "S3", "Synthetic Alpha", total=20.75, status="Cancelled"),
        ]})
        history = {r[3]: r for r in data["customers"]["history"]}
        self.assertEqual(history["S1"][7:], [100.49, 100.49])
        self.assertEqual(history["S2"][7:], [100.49, 100.49])
        self.assertEqual(history["S3"][7:], [20.75, 0])
        self.assertEqual(sum(r[8] for r in history.values()), 200.98)
        self.assertEqual(data["customers"]["r"][0][5], 201)

    def test_incomplete_source_dates_report_omitted_rows_without_changing_aggregates(self):
        missing_placed = order("P2", "S2", "Synthetic Alpha")
        missing_placed["CreatedOn"] = None
        missing_slot = order("P3", "S3", "Synthetic Alpha")
        missing_slot["DeliveryTime"] = "invalid slot"
        missing_both = order("P4", "S4", "Synthetic Alpha")
        missing_both["CreatedOn"] = "invalid date"
        missing_both["DeliveryTime"] = None
        missing_parent = order(None, "S5", "Synthetic Alpha")
        data = self.build({"orders.xlsx": [order("P1", "S1", "Synthetic Alpha"),
                                          missing_placed, missing_placed, missing_slot,
                                          missing_both, missing_parent]})
        self.assertEqual(sum(data["daily"]["n"]), 1)
        self.assertEqual(len(data["customers"]["history"]), 1)
        self.assertEqual(data["customers"]["historyCoverage"], {
            "records": 1, "omittedSourceRows": 5, "omittedMissingOrderRows": 1,
            "omittedMissingPlacedDateRows": 3, "omittedMissingSlotDateRows": 2,
        })

    def test_unchanged_source_is_rebuilt_once_to_add_history(self):
        data = self.build({"orders.xlsx": [order("P1", "S1", "Synthetic Alpha")]})
        output = self.root / "result.json"
        del data["customers"]["historyVersion"]
        output.write_text(json.dumps(data))
        items, _ = refresh.list_items(self.root)
        with mock.patch.object(refresh, "OUT", output), \
                mock.patch.object(refresh, "MASTER", self.root / "missing-master.json"), \
                mock.patch.object(refresh, "list_items", return_value=(items, None)), \
                mock.patch.object(sys, "argv", [str(SOURCE)]), \
                mock.patch.object(refresh, "first_sheet", wraps=refresh.first_sheet) as read, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(refresh.main(), 0)
            self.assertEqual(read.call_count, 1)
            self.assertEqual(json.loads(output.read_text())["customers"]["historyVersion"], 1)
            self.assertEqual(refresh.main(), 0)
            self.assertEqual(read.call_count, 1)


if __name__ == "__main__":
    unittest.main()
