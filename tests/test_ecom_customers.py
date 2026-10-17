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


def order(parent, sub, name=None, outlet="D001", total=100, status="Delivered", day="10/5/2026"):
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
        output.unlink(missing_ok=True)  # Each build() fixture is independent; refresh tests retain it explicitly.
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
                           order("P1", "S2", "TEST ALPHA", outlet="D002", total=30),
                           order("P1", "S3", None, total=20),
                           order("P2", "S4", "Test Alpha", total=200, status="Cancelled"),
                           order("P3", "S5", "Test Beta", total=60)],
        })
        self.assertEqual(data["schema"], refresh.SCHEMA)
        self.assertEqual(data["customers"]["kind"], "name")
        self.assertEqual(data["customers"]["list"], ["Test Alpha", "Test Beta"])
        self.assertEqual(data["months"], ["2026-10"])
        alpha = [r for r in data["customers"]["r"] if r[2] == 0]
        self.assertEqual(len({r[3] for r in alpha}), 2)
        self.assertEqual(sum(r[4] for r in alpha), 4)
        self.assertEqual(sum(r[5] for r in alpha), 170)
        p1_a = [r for r in alpha if r[3] == "P1" and data["outlets"][r[0]][0] == "D001"]
        self.assertEqual([r[4:] for r in p1_a], [[2, 140]])
        # The same parent appears in both outlet scopes, so summing outlet order counts is incorrect.
        self.assertEqual(len(alpha), 3)
        self.assertEqual(sum(data["daily"]["n"]), 5)

    def test_conflicting_product_or_suborder_names_exclude_the_whole_parent(self):
        data = self.build({"orders.xlsx": [
            order("P1", "S1", "Test Alpha"), order("P1", "S1", "Test Beta"),
            order("P1", "S2", None, outlet="D002"),
            order("P2", "S3", "Test Gamma"), order("P2", "S4", "Test Delta", outlet="D002"),
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
            order("P1", "S2", None, outlet="D002"),
            order("P2", "S3", "unknown"), order("P2", "S4", "Guest", outlet="D002"),
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
            order("P1", "S2", None, outlet="D002", day="10/5/2026", total=60),
            order("P2", "S3", "Test Alpha", outlet="D002", day="10/5/2026", total=80),
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
                           order("P1", "S2", None, outlet="D002", total=75, status="Cancelled"),
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
        self.assertTrue(all(len(r) == 10 for r in customers["history"]))
        history = {r[3]: r for r in customers["history"]}
        self.assertEqual(history["S1"][1:6], [0, "P1", "S1", "2026-10-01", "2026-10-05"])
        self.assertEqual(history["S1"][7:9], [125, 125])
        self.assertEqual(history["S2"][7:9], [75, 0])
        self.assertEqual(history["S2"][1], 0)
        self.assertEqual(data["outlets"][history["S2"][0]][0], "D002")
        self.assertEqual(customers["statuses"][history["S2"][6]], "Cancelled")
        self.assertEqual(history["S3"][1], -1)
        self.assertEqual([history[s][1] for s in ("S4", "S5")], [-2, -2])
        self.assertEqual(sum(r[8] for r in customers["history"]), sum(r[5] for r in customers["r"]))

    def test_history_reference_date_uses_placement_not_future_slot_or_build_date(self):
        early = order("P1", "S1", "Synthetic Alpha", day="11/3/2026")
        late = order("P1", "S2", None, outlet="D002", day="11/3/2026")
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
        self.assertEqual(history["S1"][7:9], [100.49, 100.49])
        self.assertEqual(history["S2"][7:9], [100.49, 100.49])
        self.assertEqual(history["S3"][7:9], [20.75, 0])
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


class ExtraColumnTests(unittest.TestCase):
    """Schema 4: every column is listed; safe categorical and numeric columns are charted, private ones never exported."""
    setUp = CustomerRankingTests.setUp
    build = CustomerRankingTests.build

    def test_columns_dims_nums_and_placed(self):
        headers = HEADERS + ["Zone", "DeliveryCharge", "Quantity", "CustomerPhone", "Shipping Address", "TransactionId"]
        def row(parent, sub, zone, charge, qty, status="Delivered", day="10/5/2026"):
            r = order(parent, sub, "Test Alpha", total=100, status=status, day=day)
            r.update({"Zone": zone, "DeliveryCharge": charge, "Quantity": qty, "CustomerPhone": "01711000000",
                      "Shipping Address": "Synthetic road 1", "TransactionId": "TX-" + parent})
            return r
        data = self.build({"orders.xlsx": [
            # one sub-order with two product lines: the charge repeats (sub-order level), the quantity differs (line level)
            row("P1", "S1", "North", 50, 1), row("P1", "S1", "North", 50, 2),
            row("P2", "S2", "South", 30, 1, day="10/6/2026"),
            row("P3", "S3", "South", 30, 4, status="Cancelled"),
        ]}, headers=headers)
        self.assertEqual(data["schema"], refresh.SCHEMA)
        cols = {c["name"]: c["use"] for c in data["source"]["files"][0]["columns"]}
        self.assertEqual(cols["Zone"], "dim")
        self.assertEqual(cols["DeliveryCharge"], "num")
        self.assertEqual(cols["CustomerPhone"], "private")
        self.assertEqual(cols["Shipping Address"], "private")
        self.assertEqual(cols["TransactionId"], "id")
        self.assertEqual(cols["OrderNumber"], "used")
        text = json.dumps(data)
        self.assertNotIn("01711000000", text)
        self.assertNotIn("Synthetic road", text)
        zone = data["dims"]["Zone"]
        by = {}
        for o, d, k, n, net in zone["r"]:
            by[zone["list"][k]] = by.get(zone["list"][k], 0) + n
        self.assertEqual(by, {"North": 1, "South": 2})
        self.assertIn("Payment method", data["dims"])
        self.assertIn("Sub-order status", data["dims"])
        nums = data["nums"]
        level = {c["name"]: c["level"] for c in nums["cols"]}
        self.assertEqual(level, {"DeliveryCharge": "sub", "Quantity": "line"})
        names = [c["name"] for c in nums["cols"]]
        totals = [sum(r[2 + i] for r in nums["r"]) for i in range(len(names))]
        # the cancelled sub-order is left out; the repeated charge counts once, the quantities add up
        self.assertEqual(dict(zip(names, totals)), {"DeliveryCharge": 80, "Quantity": 4})
        self.assertEqual(sum(r[4] for r in data["placed"]["r"]), 3)  # all orders
        self.assertEqual(sum(r[5] for r in data["placed"]["r"]), 2)  # delivered: the cancelled sub-order is left out
        self.assertEqual({(r[2], r[3]) for r in data["placed"]["r"]}, {(3, 9)})  # 1 Oct 2026 is a Thursday, 9 AM



    def test_snapshot_is_readable_by_the_static_web_server(self):
        self.build({"orders.xlsx": [order("P1", "S1", "Synthetic Alpha")]})
        self.assertEqual((self.root / "result.json").stat().st_mode & 0o444, 0o444)

    def test_failed_workbook_keeps_last_good_snapshot_and_does_not_poison_cache(self):
        self.build({"a.xlsx": [order("P1", "S1", "Synthetic Alpha")],
                    "b.xlsx": [order("P2", "S2", "Synthetic Beta")]})
        output = self.root / "result.json"
        before = output.read_bytes()
        items, _ = refresh.list_items(self.root)
        items = [{**item, "modified": "changed"} for item in items]
        native = refresh.first_sheet
        def fail_b(path):
            if Path(path).name == "b.xlsx":
                raise OSError("Synthetic read failure")
            return native(path)
        with mock.patch.object(refresh, "OUT", output), \
                mock.patch.object(refresh, "MASTER", self.root / "missing.json"), \
                mock.patch.object(refresh, "list_items", return_value=(items, None)), \
                mock.patch.object(sys, "argv", [str(SOURCE)]), \
                contextlib.redirect_stdout(io.StringIO()):
            with mock.patch.object(refresh, "first_sheet", side_effect=fail_b):
                self.assertEqual(refresh.main(), 1)
            self.assertEqual(output.read_bytes(), before)
            with mock.patch.object(refresh, "first_sheet", wraps=native) as reader:
                self.assertEqual(refresh.main(), 0)
                self.assertEqual(reader.call_count, 2, "A healthy retry must actually reread the failed source")
                self.assertEqual(refresh.main(), 0)
                self.assertEqual(reader.call_count, 2, "Only a fully successful build may hit the cache")

    def test_missing_month_retains_last_complete_snapshot(self):
        self.build({"a.xlsx": [order("P1", "S1", "Synthetic Alpha", day="9/1/2026")],
                    "b.xlsx": [order("P2", "S2", "Synthetic Beta", day="10/1/2026")]})
        output = self.root / "result.json"
        before = output.read_bytes()
        (self.root / "b.xlsx").unlink()
        with mock.patch.object(refresh, "OUT", output), \
                mock.patch.object(refresh, "MASTER", self.root / "missing.json"), \
                mock.patch.object(sys, "argv", [str(SOURCE), "--local", str(self.root)]), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(refresh.main(), 1)
        self.assertEqual(output.read_bytes(), before)

    def test_regression_validation_checks_dates_suborders_and_complaints(self):
        import copy
        baseline = self.build({"orders.xlsx": [order("P1", "S1", "Synthetic Alpha")]})
        for kind in ("date", "orders", "complaints"):
            old, new = copy.deepcopy(baseline), copy.deepcopy(baseline)
            if kind == "date":
                old["source"]["asOf"] = "2099-01-01 00:00"
            elif kind == "orders":
                new["customers"]["history"] = []
            else:
                old["complaints"] = [["Synthetic complaint"]]
            self.assertTrue(refresh.regression_reason(old, new), kind)
        self.assertEqual(refresh.regression_reason(baseline, baseline), "")

    def test_unknown_complaint_outlet_inherits_only_an_unambiguous_matched_outlet(self):
        self.assertEqual(refresh.complaint_outlet_code("?", [{"code": "D001"}]), "D001")
        self.assertEqual(refresh.complaint_outlet_code("", [{"code": "D001"}, {"code": "D001"}]), "D001")
        self.assertEqual(refresh.complaint_outlet_code("?", [{"code": "D001"}, {"code": "D002"}]), "?")
        self.assertEqual(refresh.complaint_outlet_code("D003", [{"code": "D001"}]), "D003")

    def test_history_retains_actual_delivery_date_separately_from_slot(self):
        row = order("P1", "S1", "Synthetic Alpha", day="10/1/2026", status="Complete")
        row["DeliveredOn"] = "Oct 02, 2026, 9:00:00 AM"
        data = self.build({"orders.xlsx": [row]}, headers=HEADERS + ["DeliveredOn"])
        self.assertEqual(data["customers"]["history"][0][5], "2026-10-01")
        self.assertEqual(data["customers"]["history"][0][9], "2026-10-02")


class SlotChangeTests(unittest.TestCase):
    """A slot moved from the customer's choice counts as a slot change; delivered after the customer's slot ended,
    it is late for the customer even though it is on time against the moved slot."""
    setUp = CustomerRankingTests.setUp
    build = CustomerRankingTests.build

    def row(self, parent, final, delivered, original=None, flag=None, day="10/5/2026"):
        r = order(parent, "S" + parent, "Test Alpha", day=day)
        r.update({"DeliveryTime": f"{final} {day}", "DeliveredOn": delivered,
                  "RequestedSlot": f"{original} {day}" if original else None, "Rescheduled": flag})
        return r

    def totals(self, data):
        return {k: sum(data["daily"][k]) for k in ("n", "late", "slotch", "slotchLate")}

    def test_original_slot_column(self):
        headers = HEADERS + ["DeliveredOn", "RequestedSlot"]
        data = self.build({"orders.xlsx": [
            # chose 11-12, moved to 3-4 PM, delivered 3:30 PM: on time for the moved slot, late for the customer
            self.row("P1", "03:00 PM - 04:00 PM", "Oct 05, 2026, 3:30:00 PM", "11:00 AM - 12:00 PM"),
            # chose 11-12, moved to 12-1 PM, delivered 11:45 AM: moved, but within the customer's slot
            self.row("P2", "12:00 PM - 01:00 PM", "Oct 05, 2026, 11:45:00 AM", "11:00 AM - 12:00 PM"),
            # not moved, delivered late against its slot
            self.row("P3", "09:00 AM - 10:00 AM", "Oct 05, 2026, 10:30:00 AM", "09:00 AM - 10:00 AM"),
        ]}, headers=headers)
        cols = {c["name"]: c["use"] for c in data["source"]["files"][0]["columns"]}
        self.assertEqual(cols["RequestedSlot"], "slot")
        self.assertEqual(self.totals(data), {"n": 3, "late": 1, "slotch": 2, "slotchLate": 1})
        self.assertEqual(data["slotChange"]["sources"], ["RequestedSlot"])
        slots = [s[0] for s in data["slots"]["list"]]
        moves = {(slots[r[2]], slots[r[3]]): r[4:] for r in data["slotChange"]["r"]}
        self.assertEqual(moves[("11:00 AM - 12:00 PM", "03:00 PM - 04:00 PM")], [1, 1])
        self.assertEqual(moves[("11:00 AM - 12:00 PM", "12:00 PM - 01:00 PM")], [1, 0])

    def test_slot_differs_between_exports(self):
        headers = HEADERS + ["DeliveredOn"]
        data = self.build({
            "a.xlsx": [self.row("P1", "11:00 AM - 12:00 PM", None)],
            "b.xlsx": [self.row("P1", "03:00 PM - 04:00 PM", "Oct 05, 2026, 3:30:00 PM")],
        }, headers=headers)
        self.assertEqual(self.totals(data), {"n": 1, "late": 0, "slotch": 1, "slotchLate": 1})
        self.assertEqual(data["slotChange"]["sources"], ["exports"])

    def test_reschedule_flag_and_no_source(self):
        headers = HEADERS + ["DeliveredOn", "Rescheduled"]
        data = self.build({"orders.xlsx": [
            self.row("P1", "03:00 PM - 04:00 PM", "Oct 05, 2026, 3:30:00 PM", flag="Yes"),
            self.row("P2", "03:00 PM - 04:00 PM", "Oct 05, 2026, 3:30:00 PM", flag="No"),
        ]}, headers=headers)
        self.assertEqual(self.totals(data), {"n": 2, "late": 0, "slotch": 1, "slotchLate": 0})
        self.assertEqual(data["slotChange"]["sources"], ["Rescheduled"])
        plain = self.build({"orders.xlsx": [self.row("P1", "03:00 PM - 04:00 PM", "Oct 05, 2026, 3:30:00 PM")]}, headers=HEADERS + ["DeliveredOn"])
        self.assertEqual(plain["slotChange"], {"sources": [], "r": []})
        self.assertEqual(sum(plain["daily"]["slotch"]), 0)


class ItemTests(unittest.TestCase):
    """Schema 6: every product line, by outlet and day; cancelled sub-orders apart."""
    setUp = CustomerRankingTests.setUp
    build = CustomerRankingTests.build

    def test_items(self):
        headers = HEADERS + ["SKU", "Quantity", "Discount", "Edit Reason", "Updated Qty"]
        def line(parent, name, sku, qty, price, total, status="Delivered", reason=None, upd=None, outlet="D001"):
            r = order(parent, "1", "Test Alpha", outlet=outlet, total=total, status=status)
            r.update({"ProductName": name, "SKU": sku, "Quantity": qty, "Price": price, "Discount": 5, "Edit Reason": reason, "Updated Qty": upd})
            return r
        data = self.build({"orders.xlsx": [
            line("P1", "Rice", 101, 2, 200, 300), line("P1", "Oil", 202, 1, 100, 300, reason="Out of Stock", upd=0),
            line("P2", "Rice", 101, 3, 300, 300, outlet="D002"),
            line("P3", "Rice", 101, 1, 100, 100, status="Cancelled"),
        ]}, headers=headers)
        it = data["items"]
        self.assertEqual(it["months"], ["2026-10"])
        names = {i: n for i, (n, sku) in enumerate(it["list"])}
        tot = {}
        for p, o, d, lines, subs, qty, amount, disc, oos, short, cl, ca in it["r"]:
            t = tot.setdefault(names[p], [0, 0, 0, 0, 0, 0, 0, 0, 0])
            for j, v in enumerate([lines, subs, qty, amount, disc, oos, short, cl, ca]):
                t[j] += v
        self.assertEqual(tot["Rice"], [2, 2, 5, 500, 10, 0, 0, 1, 100])
        self.assertEqual(tot["Oil"], [1, 1, 1, 100, 5, 1, 1, 0, 0])
        self.assertEqual(it["list"][[n for n, _ in it["list"]].index("Rice")][1], "101")
