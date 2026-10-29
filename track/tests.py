from decimal import Decimal
import json

from django.contrib.auth.models import User
from django.test import Client, TestCase

from track.models import Employee, MonthlyEntry, PaymentMethod, Transaction, WarehouseItem


def post_json(client, url, data=None):
    return client.post(url, json.dumps(data or {}), content_type="application/json")


class AuthTestCase(TestCase):
    """Common fixtures: a plain user, a staff user and a superuser."""

    @classmethod
    def setUpTestData(cls):
        cls.plain = User.objects.create_user("plain", password="pw-plain-123")
        cls.staff = User.objects.create_user("staff", password="pw-staff-123", is_staff=True)
        cls.boss = User.objects.create_superuser("boss", password="pw-boss-123", is_staff=True)

    def as_user(self, user, enforce_csrf=False):
        client = Client(enforce_csrf_checks=enforce_csrf)
        client.force_login(user)
        return client


class UserManagementPermissionTests(AuthTestCase):
    def test_plain_user_cannot_create_user(self):
        resp = post_json(self.as_user(self.plain), "/api/user/create/",
                         {"username": "evil", "password": "x" * 12, "is_staff": True})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(User.objects.filter(username="evil").exists())

    def test_plain_user_cannot_promote_self(self):
        resp = post_json(self.as_user(self.plain), f"/api/user/{self.plain.id}/update/", {"is_staff": True})
        self.assertEqual(resp.status_code, 403)
        self.plain.refresh_from_db()
        self.assertFalse(self.plain.is_staff)

    def test_plain_user_cannot_reset_other_password(self):
        resp = post_json(self.as_user(self.plain), f"/api/user/{self.staff.id}/update/", {"password": "hacked-pass-1"})
        self.assertEqual(resp.status_code, 403)
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.check_password("pw-staff-123"))

    def test_plain_user_cannot_delete_user(self):
        resp = post_json(self.as_user(self.plain), f"/api/user/{self.staff.id}/delete/")
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(User.objects.filter(id=self.staff.id).exists())

    def test_staff_can_create_user(self):
        resp = post_json(self.as_user(self.staff), "/api/user/create/",
                         {"username": "newbie", "password": "a-long-pass-9", "first_name": "N"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(User.objects.filter(username="newbie").exists())

    def test_staff_cannot_delete_self(self):
        resp = post_json(self.as_user(self.staff), f"/api/user/{self.staff.id}/delete/")
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(User.objects.filter(id=self.staff.id).exists())

    def test_staff_cannot_remove_own_staff_flag_or_deactivate_self(self):
        client = self.as_user(self.staff)
        post_json(client, f"/api/user/{self.staff.id}/update/", {"is_staff": False, "is_active": False})
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.is_staff)
        self.assertTrue(self.staff.is_active)

    def test_staff_cannot_touch_superuser(self):
        client = self.as_user(self.staff)
        self.assertEqual(post_json(client, f"/api/user/{self.boss.id}/update/", {"password": "takeover-pass-1"}).status_code, 403)
        self.assertEqual(post_json(client, f"/api/user/{self.boss.id}/delete/").status_code, 403)
        self.boss.refresh_from_db()
        self.assertTrue(self.boss.check_password("pw-boss-123"))

    def test_superuser_can_update_superuser(self):
        resp = post_json(self.as_user(self.boss), f"/api/user/{self.boss.id}/update/", {"first_name": "Boss"})
        self.assertEqual(resp.status_code, 200)

    def test_plain_user_cannot_read_the_user_list_page_or_api(self):
        plain = self.as_user(self.plain)
        self.assertEqual(plain.get("/users/").status_code, 403)
        self.assertEqual(plain.get("/api/users/").status_code, 403)
        self.assertEqual(plain.get(f"/api/user/{self.staff.id}/").status_code, 403)
        self.assertContains(plain.get("/users/"), "only available to staff", status_code=403)

    def test_staff_can_still_open_the_users_page_and_api(self):
        staff = self.as_user(self.staff)
        self.assertEqual(staff.get("/users/").status_code, 200)
        self.assertEqual(staff.get("/api/users/").status_code, 200)
        self.assertEqual(staff.get(f"/api/user/{self.plain.id}/").status_code, 200)

    def test_anonymous_is_still_sent_to_sign_in_not_shown_a_403(self):
        self.assertEqual(self.client.get("/users/").status_code, 302)

    def test_user_password_is_validated(self):
        resp = post_json(self.as_user(self.staff), "/api/user/create/", {"username": "weak", "password": "123"})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(User.objects.filter(username="weak").exists())


class CsrfEnforcementTests(AuthTestCase):
    """Every state-changing endpoint must reject a POST that has no CSRF token."""

    def test_all_post_endpoints_enforce_csrf(self):
        urls = [
            "/api/transaction/create/", "/api/transaction/1/update/", "/api/transaction/1/delete/",
            "/api/user/create/", "/api/user/1/update/", "/api/user/1/delete/",
            "/api/employee/create/", "/api/employee/1/", "/api/employee/1/delete/",
            "/api/monthly/entry/create/", "/api/monthly/product/add/", "/api/monthly/product/1/delete/",
            "/api/monthly/payment/add/", "/api/monthly/payment/1/delete/",
            "/api/warehouse/item/create/", "/api/warehouse/item/1/update/", "/api/warehouse/item/1/delete/",
            "/api/warehouse/entry/add/", "/api/warehouse/entry/1/delete/",
        ]
        client = self.as_user(self.boss, enforce_csrf=True)
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(post_json(client, url).status_code, 403)


class StaffOnlyWriteTests(AuthTestCase):
    """Plain users may read but never write business data."""

    def test_plain_user_cannot_write(self):
        method = PaymentMethod.objects.create(name="Cash")
        emp = Employee.objects.create(first_name="A", last_name="B")
        entry = MonthlyEntry.objects.create(employee=emp, month="2026-10-01")
        item = WarehouseItem.objects.create(name="W")
        client = self.as_user(self.plain)
        writes = [
            ("/api/transaction/create/", {"type": "income", "amount": 5, "date": "2026-10-01", "method": method.id}),
            ("/api/employee/create/", {"first_name": "X", "last_name": "Y"}),
            ("/api/monthly/product/add/", {"entry_id": entry.id, "product_name": "p", "quantity": "1", "price_per_unit": "1"}),
            ("/api/monthly/payment/add/", {"entry_id": entry.id, "amount": "1", "payment_date": "2026-10-01"}),
            ("/api/warehouse/item/create/", {"name": "Z"}),
            ("/api/warehouse/entry/add/", {"item_id": item.id, "type": "in", "quantity": 1, "date": "2026-10-01"}),
            (f"/api/warehouse/item/{item.id}/update/", {"quantity": 99}),
            (f"/api/warehouse/item/{item.id}/delete/", {}),
        ]
        for url, payload in writes:
            with self.subTest(url=url):
                self.assertEqual(post_json(client, url, payload).status_code, 403)
        self.assertEqual(Transaction.objects.count(), 0)
        self.assertEqual(Employee.objects.count(), 1)
        self.assertEqual(WarehouseItem.objects.count(), 1)


class SettingsTests(TestCase):
    """config.settings must fail closed and honour the environment (checked in a clean subprocess)."""

    def load_settings(self, **env):
        import os
        import subprocess
        import sys
        from pathlib import Path

        base = Path(__file__).resolve().parent.parent
        clean = {k: v for k, v in os.environ.items() if not k.startswith("DJANGO_")}
        clean.update({"DJANGO_ENV_FILE": os.devnull, "DJANGO_SETTINGS_MODULE": "config.settings"})
        clean.update(env)
        code = (
            "import json, config.settings as s;"
            "print(json.dumps({k: getattr(s, k, None) for k in ("
            "'DEBUG','ALLOWED_HOSTS','SESSION_COOKIE_SECURE','CSRF_COOKIE_SECURE',"
            "'SECURE_SSL_REDIRECT','SECURE_HSTS_SECONDS','TIME_ZONE','SECRET_KEY')}, default=str))"
        )
        proc = subprocess.run([sys.executable, "-c", code], cwd=base, env=clean,
                              capture_output=True, text=True, timeout=60)
        return proc

    def test_refuses_to_start_without_secret_key(self):
        proc = self.load_settings()
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY", proc.stderr)

    def test_production_values_come_from_environment(self):
        proc = self.load_settings(DJANGO_SECRET_KEY="k" * 60, DJANGO_ALLOWED_HOSTS="a.example.com, b.example.com")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        cfg = json.loads(proc.stdout)
        self.assertFalse(cfg["DEBUG"])
        self.assertEqual(cfg["ALLOWED_HOSTS"], ["a.example.com", "b.example.com"])
        self.assertEqual(cfg["SECRET_KEY"], "k" * 60)
        self.assertEqual(cfg["TIME_ZONE"], "Asia/Tashkent")

    def test_production_requires_allowed_hosts(self):
        proc = self.load_settings(DJANGO_SECRET_KEY="k" * 60)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("DJANGO_ALLOWED_HOSTS", proc.stderr)

    def test_https_flag_turns_on_secure_cookies_and_hsts(self):
        proc = self.load_settings(DJANGO_SECRET_KEY="k" * 60, DJANGO_ALLOWED_HOSTS="a.example.com", DJANGO_HTTPS="1")
        cfg = json.loads(proc.stdout)
        self.assertTrue(cfg["SESSION_COOKIE_SECURE"])
        self.assertTrue(cfg["CSRF_COOKIE_SECURE"])
        self.assertTrue(cfg["SECURE_SSL_REDIRECT"])
        self.assertGreater(cfg["SECURE_HSTS_SECONDS"], 0)

    def test_debug_mode_needs_no_secret_and_allows_localhost(self):
        proc = self.load_settings(DJANGO_DEBUG="1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        cfg = json.loads(proc.stdout)
        self.assertTrue(cfg["DEBUG"])
        self.assertIn("localhost", cfg["ALLOWED_HOSTS"])
        self.assertFalse(cfg["SESSION_COOKIE_SECURE"])


class StaffTestCase(AuthTestCase):
    def setUp(self):
        self.client = self.as_user(self.staff)
        self.method = PaymentMethod.objects.create(name="Cash")

    def post(self, url, data=None):
        return post_json(self.client, url, data)


class TransactionApiTests(StaffTestCase):
    def payload(self, **over):
        data = {"type": "income", "currency": "usd", "amount": 12.5, "date": "2026-01-15",
                "method": self.method.id, "description": "Sale"}
        data.update(over)
        return data

    def test_decimal_amount_is_stored_exactly(self):
        for raw in (12.5, "12.50"):
            with self.subTest(raw=raw):
                resp = self.post("/api/transaction/create/", self.payload(amount=raw))
                self.assertEqual(resp.status_code, 200, resp.content)
                self.assertEqual(str(Transaction.objects.get(id=resp.json()["id"]).amount), "12.50")

    def test_stats_sum_decimals(self):
        self.post("/api/transaction/create/", self.payload(amount="10.10"))
        self.post("/api/transaction/create/", self.payload(amount="0.20"))
        stats = self.client.get("/api/stats/").json()
        self.assertEqual(stats["incomes_usd"], 10.3)
        self.assertEqual(stats["balance_usd"], 10.3)

    def test_api_returns_numeric_amount(self):
        self.post("/api/transaction/create/", self.payload(currency="uzs", amount=1500000))
        amount = self.client.get("/api/transactions/").json()["transactions"][0]["amount"]
        self.assertEqual(amount, 1500000)
        self.assertIsInstance(amount, int)

    def test_rejects_bad_input(self):
        bad = [
            {"type": "banana"}, {"currency": "eur"}, {"amount": -5}, {"amount": 0}, {"amount": "abc"},
            {"amount": None}, {"date": "not-a-date"}, {"date": "2099-01-01"}, {"method": 99999},
            {"method": "x"}, {"description": "x" * 300}, {"amount": "1e20"},
        ]
        for over in bad:
            with self.subTest(over=over):
                resp = self.post("/api/transaction/create/", self.payload(**over))
                self.assertEqual(resp.status_code, 400, resp.content)
                self.assertFalse(resp.json()["success"])
                self.assertNotIn("constraint", resp.json()["error"].lower())
        self.assertEqual(Transaction.objects.count(), 0)

    def test_update_validates_and_missing_is_404(self):
        tid = self.post("/api/transaction/create/", self.payload()).json()["id"]
        self.assertEqual(self.post(f"/api/transaction/{tid}/update/", {"type": "banana"}).status_code, 400)
        self.assertEqual(self.post(f"/api/transaction/{tid}/update/", {"amount": "20.25"}).status_code, 200)
        self.assertEqual(str(Transaction.objects.get(id=tid).amount), "20.25")
        self.assertEqual(self.post("/api/transaction/9999/update/", {}).status_code, 404)

    def test_invalid_filters_return_400_not_500(self):
        for query in ("date_from=abc", "date_to=2026-13-45", "method=abc", "type=banana", "currency=eur"):
            for url in ("/api/transactions/", "/api/stats/"):
                with self.subTest(url=url, query=query):
                    self.assertEqual(self.client.get(f"{url}?{query}").status_code, 400)

    def test_valid_filters_still_work(self):
        self.post("/api/transaction/create/", self.payload(date="2026-01-10", amount=1))
        self.post("/api/transaction/create/", self.payload(date="2026-02-10", amount=2))
        data = self.client.get(f"/api/transactions/?date_from=2026-02-01&type=income&method={self.method.id}&currency=usd").json()
        self.assertEqual([t["amount"] for t in data["transactions"]], [2])

    def test_malformed_json_is_400(self):
        resp = self.client.post("/api/transaction/create/", "{not json", content_type="application/json")
        self.assertEqual(resp.status_code, 400)


class MonthlyApiTests(StaffTestCase):
    def setUp(self):
        super().setUp()
        self.emp = Employee.objects.create(first_name="A", last_name="B")
        self.entry = MonthlyEntry.objects.create(employee=self.emp, month="2026-10-01")

    def product(self, **over):
        data = {"entry_id": self.entry.id, "product_name": "Flour", "quantity": 2.5,
                "price_per_unit": 10.1, "unit_type": "kg", "currency": "usd"}
        data.update(over)
        return data

    def test_product_total_is_exact_and_balance_is_per_currency(self):
        self.assertEqual(self.post("/api/monthly/product/add/", self.product()).status_code, 200)
        self.assertEqual(self.post("/api/monthly/product/add/", self.product(currency="uzs", quantity=3, price_per_unit=1000)).status_code, 200)
        self.assertEqual(self.post("/api/monthly/payment/add/", {"entry_id": self.entry.id, "amount": "5.25", "currency": "usd", "payment_date": "2026-10-02"}).status_code, 200)
        detail = self.client.get(f"/api/monthly/entry/{self.entry.id}/").json()
        self.assertEqual(detail["balance_usd"], "20.00")
        self.assertEqual(detail["balance_uzs"], "3000.00")
        self.assertEqual(detail["balance_afn"], "0.00")

    def test_balances_for_all_employees_come_from_one_request_and_match_the_entries(self):
        other = Employee.objects.create(first_name="C", last_name="D")
        entry2 = MonthlyEntry.objects.create(employee=self.emp, month="2026-09-01")
        self.post("/api/monthly/product/add/", self.product())                                    # 25.25 usd
        self.post("/api/monthly/product/add/", self.product(entry_id=entry2.id, currency="usd", quantity=1, price_per_unit=4.75))
        self.post("/api/monthly/product/add/", self.product(currency="afn", quantity=2, price_per_unit=50))
        self.post("/api/monthly/payment/add/", {"entry_id": entry2.id, "amount": "10.00", "currency": "usd", "payment_date": "2026-09-05"})
        balances = self.client.get("/api/employees/balances/").json()["balances"]
        self.assertEqual(balances[str(self.emp.id)], {"uzs": "0.00", "usd": "20.00", "afn": "100.00"})
        self.assertEqual(balances[str(other.id)], {"uzs": "0.00", "usd": "0.00", "afn": "0.00"})

    def test_balances_query_count_does_not_grow_with_employees(self):
        def queries():
            from django.db import connection
            from django.test.utils import CaptureQueriesContext
            with CaptureQueriesContext(connection) as ctx:
                self.assertEqual(self.client.get("/api/employees/balances/").status_code, 200)
            return len(ctx)
        before = queries()
        for i in range(10):
            e = Employee.objects.create(first_name=f"E{i}", last_name="X")
            MonthlyEntry.objects.create(employee=e, month="2026-10-01")
        self.assertEqual(queries(), before)

    def test_balances_require_sign_in(self):
        self.assertEqual(Client().get("/api/employees/balances/").status_code, 401)

    def test_deleting_rows_updates_balance(self):
        pid = self.post("/api/monthly/product/add/", self.product()).json()["id"]
        payid = self.post("/api/monthly/payment/add/", {"entry_id": self.entry.id, "amount": 10, "currency": "usd", "payment_date": "2026-10-02"}).json()["id"]
        self.post(f"/api/monthly/payment/{payid}/delete/")
        self.assertEqual(self.client.get(f"/api/monthly/entry/{self.entry.id}/").json()["balance_usd"], "25.25")
        self.post(f"/api/monthly/product/{pid}/delete/")
        self.assertEqual(self.client.get(f"/api/monthly/entry/{self.entry.id}/").json()["balance_usd"], "0.00")

    def test_rejects_bad_products(self):
        bad = [{"quantity": -5}, {"quantity": 0}, {"price_per_unit": -1}, {"currency": "xxx"},
               {"unit_type": "bogus"}, {"product_name": "  "}, {"product_name": "x" * 300},
               {"quantity": "abc"}, {"entry_id": "zzz"}, {"quantity": "99999999999"}]
        for over in bad:
            with self.subTest(over=over):
                self.assertEqual(self.post("/api/monthly/product/add/", self.product(**over)).status_code, 400)
        self.assertEqual(self.post("/api/monthly/product/add/", self.product(entry_id=99999)).status_code, 404)

    def test_rejects_bad_payments(self):
        base = {"entry_id": self.entry.id, "amount": 5, "currency": "usd", "payment_date": "2026-10-02"}
        for over in ({"amount": -1}, {"amount": 0}, {"currency": "xxx"}, {"payment_date": "nope"}, {"payment_date": None}, {"amount": "abc"}):
            with self.subTest(over=over):
                self.assertEqual(self.post("/api/monthly/payment/add/", {**base, **over}).status_code, 400)
        self.assertEqual(self.post("/api/monthly/payment/add/", {**base, "entry_id": 99999}).status_code, 404)

    def test_monthly_page_does_not_write_on_get(self):
        before = MonthlyEntry.objects.count()
        Employee.objects.create(first_name="C", last_name="D")
        self.assertEqual(self.client.get("/monthly/").status_code, 200)
        self.assertEqual(MonthlyEntry.objects.count(), before)

    def test_create_entry_normalises_month_and_rejects_duplicates(self):
        resp = self.post("/api/monthly/entry/create/", {"employee_id": self.emp.id, "month": "2026-11-17"})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(str(MonthlyEntry.objects.get(id=resp.json()["id"]).month), "2026-11-01")
        self.assertEqual(self.post("/api/monthly/entry/create/", {"employee_id": self.emp.id, "month": "2026-11-02"}).status_code, 400)
        self.assertEqual(self.post("/api/monthly/entry/create/", {"employee_id": self.emp.id, "month": "bad"}).status_code, 400)

    def test_employee_validation(self):
        self.assertEqual(self.post("/api/employee/create/", {"first_name": "", "last_name": "X"}).status_code, 400)
        self.assertEqual(self.post("/api/employee/create/", {"first_name": "X", "last_name": "Y", "email": "nope"}).status_code, 400)
        self.assertEqual(self.post("/api/employee/create/", {"first_name": "X" * 200, "last_name": "Y"}).status_code, 400)
        ok = self.post("/api/employee/create/", {"first_name": " Ann ", "last_name": "Lee", "email": "a@b.co", "is_active": True})
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(Employee.objects.get(id=ok.json()["id"]).first_name, "Ann")
        self.assertEqual(self.post(f"/api/employee/{self.emp.id}/", {"last_name": ""}).status_code, 400)
        self.assertEqual(self.post("/api/employee/99999/", {"last_name": "Z"}).status_code, 404)

    def test_current_month_uses_local_timezone(self):
        from datetime import datetime, timezone as dt_timezone
        from unittest import mock
        # 2026-10-31 20:00 UTC is already 2026-11-01 01:00 in Tashkent (UTC+5)
        with mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 31, 20, 0, tzinfo=dt_timezone.utc)):
            from track.views import current_month_start
            self.assertEqual(str(current_month_start()), "2026-11-01")


class WarehouseApiTests(StaffTestCase):
    def setUp(self):
        super().setUp()
        self.item = WarehouseItem.objects.create(name="Flour")

    def move(self, kind, qty=0, kg=0, **over):
        data = {"item_id": self.item.id, "type": kind, "quantity": qty, "quantity_kg": kg, "date": "2026-10-01"}
        data.update(over)
        return self.post("/api/warehouse/entry/add/", data)

    def stock(self):
        self.item.refresh_from_db()
        return self.item.quantity, str(self.item.quantity_kg)

    def test_in_and_out_update_stock(self):
        self.assertEqual(self.move("in", 10, 250).status_code, 200)
        self.assertEqual(self.move("out", 4, 100).status_code, 200)
        self.assertEqual(self.stock(), (6, "150.00"))

    def test_cannot_take_out_more_than_in_stock(self):
        self.move("in", 10, 250)
        for qty, kg in ((11, 0), (0, 250.01)):
            with self.subTest(qty=qty, kg=kg):
                resp = self.move("out", qty, kg)
                self.assertEqual(resp.status_code, 400)
                self.assertIn("stock", resp.json()["error"].lower())
        self.assertEqual(self.stock(), (10, "250.00"))
        self.assertEqual(self.item.movements.count(), 1)

    def test_rejects_bad_movements(self):
        good = {"item_id": self.item.id, "type": "in", "quantity": 1, "quantity_kg": 0, "date": "2026-10-01"}
        for over in ({"type": "sideways"}, {"quantity": -1}, {"quantity": 0, "quantity_kg": 0},
                     {"date": "bad"}, {"quantity": "x"}, {"quantity": 1.5}, {"quantity_kg": -2}):
            with self.subTest(over=over):
                self.assertEqual(self.post("/api/warehouse/entry/add/", {**good, **over}).status_code, 400)
        self.assertEqual(self.post("/api/warehouse/entry/add/", {**good, "item_id": 99999}).status_code, 404)
        self.assertEqual(self.item.movements.count(), 0)

    def test_stock_always_equals_ledger(self):
        self.move("in", 10, 100)
        out = self.move("out", 3, 30).json()["id"]
        self.move("in", 5, 50)
        self.post(f"/api/warehouse/entry/{out}/delete/")
        ledger_qty = sum(m.quantity if m.type == "in" else -m.quantity for m in self.item.movements.all())
        self.assertEqual(self.stock()[0], ledger_qty)

    def test_cannot_delete_movement_that_would_make_stock_negative(self):
        incoming = self.move("in", 10, 100).json()["id"]
        self.move("out", 8, 80)
        resp = self.post(f"/api/warehouse/entry/{incoming}/delete/")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.stock(), (2, "20.00"))

    def test_update_cannot_bypass_the_ledger(self):
        self.assertEqual(self.post(f"/api/warehouse/item/{self.item.id}/update/", {"quantity": 9999}).status_code, 400)
        self.assertEqual(self.post(f"/api/warehouse/item/{self.item.id}/update/", {"name": "Flour 50kg"}).status_code, 200)
        self.assertEqual(self.stock()[0], 0)
        self.item.refresh_from_db()
        self.assertEqual(self.item.name, "Flour 50kg")

    def test_initial_stock_is_recorded_as_a_movement(self):
        resp = self.post("/api/warehouse/item/create/", {"name": "Rice", "quantity": 7, "quantity_kg": "12.5"})
        self.assertEqual(resp.status_code, 200, resp.content)
        item = WarehouseItem.objects.get(id=resp.json()["id"])
        self.assertEqual((item.quantity, str(item.quantity_kg)), (7, "12.50"))
        self.assertEqual(item.movements.count(), 1)
        self.assertEqual(self.post("/api/warehouse/item/create/", {"name": "  "}).status_code, 400)

    def test_form_post_errors_are_shown_not_swallowed(self):
        self.move("in", 1, 0)
        resp = self.client.post("/api/warehouse/entry/add/", {"item_id": self.item.id, "type": "out", "quantity": 5,
                                                              "quantity_kg": 0, "date": "2026-10-01"})
        self.assertEqual(resp.status_code, 302)
        page = self.client.get("/warehouse/")
        self.assertContains(page, "Not enough stock")


class CommaThousandsFilterTests(TestCase):
    def test_matches_the_page_script_number_format(self):
        from decimal import Decimal
        from track.templatetags.number_format import comma_thousands
        self.assertEqual(comma_thousands(1500000), "1,500,000")
        self.assertEqual(comma_thousands(Decimal("1500000.00")), "1,500,000")
        self.assertEqual(comma_thousands(Decimal("12.50")), "12.5")
        self.assertEqual(comma_thousands(1234.567), "1,234.57")
        self.assertEqual(comma_thousands(-2500), "-2,500")
        self.assertEqual(comma_thousands(0), "0")
        self.assertEqual(comma_thousands("abc"), "abc")


class LoginPageTests(AuthTestCase):
    def test_login_page_is_clean_and_accessible(self):
        resp = self.client.get("/login/?next=/users/")
        self.assertContains(resp, "<!DOCTYPE html>")
        self.assertContains(resp, 'for="id_username"')
        self.assertContains(resp, 'autocomplete="current-password"')
        self.assertContains(resp, 'name="next" value="/users/"')
        self.assertNotContains(resp, "tailwind")
        self.assertLess(len(resp.content), 8000)

    def test_wrong_password_shows_actionable_error(self):
        resp = self.client.post("/login/", {"username": "plain", "password": "nope"})
        self.assertContains(resp, "Invalid username or password")

    def test_login_redirects_to_next(self):
        resp = self.client.post("/login/", {"username": "plain", "password": "pw-plain-123", "next": "/users/"})
        self.assertRedirects(resp, "/users/", fetch_redirect_response=False)


class ApiAuthTests(TestCase):
    def test_anonymous_api_call_gets_json_401(self):
        resp = self.client.get("/api/transactions/")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["success"], False)


class TransactionListLimitTests(StaffTestCase):
    def setUp(self):
        super().setUp()
        for day in range(1, 6):
            Transaction.objects.create(type="income", currency="uzs", method=self.method, amount=day,
                                       date=f"2026-01-{day:02d}", description=f"t{day}")

    def test_limit_returns_newest_first_with_total(self):
        data = self.client.get("/api/transactions/?limit=2").json()
        self.assertEqual([t["description"] for t in data["transactions"]], ["t5", "t4"])
        self.assertEqual(data["total"], 5)

    def test_stats_ignore_the_limit(self):
        self.assertEqual(self.client.get("/api/stats/?limit=1").json()["incomes_uzs"], 15)

    def test_bad_limit_is_400(self):
        for value in ("abc", "0", "-3", "100000"):
            with self.subTest(value=value):
                self.assertEqual(self.client.get(f"/api/transactions/?limit={value}").status_code, 400)

    def test_dashboard_caps_rendered_rows_and_says_so(self):
        from track import views
        with __import__("unittest").mock.patch.object(views, "TRANSACTION_PAGE_SIZE", 3):
            page = self.client.get("/?date_from=2000-01-01")
        self.assertContains(page, "Showing the latest 3 of 5 transactions")
        import re
        self.assertEqual(len(re.findall(r"toggleDropdown\(event, 'trans-\d+'\)", page.content.decode())), 3)


class NavbarConsistencyTests(AuthTestCase):
    """The header navigation must be identical on every page (only the highlighted link changes)."""

    PAGES = {"/": "Dashboard", "/monthly/": "Employees", "/warehouse/": "Warehouse", "/users/": "Users"}

    def nav_links(self, user, path):
        import re
        html = self.as_user(user).get(path).content.decode()
        nav = html[html.index("<nav"):html.index("</nav>")]
        links = re.findall(r"<a href=\"([^\"]+)\"[^>]*>(.*?)</a>", nav, re.S)
        labels = [(href, re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).strip()) for href, text in links]
        current = re.findall(r'aria-current="page"[^>]*>(.*?)</a>', nav, re.S)
        return labels, [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip() for c in current]

    def test_staff_sees_same_menu_everywhere(self):
        expected = [("/", "Dashboard"), ("/monthly/", "Employees"), ("/warehouse/", "Warehouse"), ("/users/", "Users")]
        for path, name in self.PAGES.items():
            with self.subTest(path=path):
                links, current = self.nav_links(self.staff, path)
                self.assertEqual(links, expected)
                self.assertEqual(current, [name])

    def test_plain_user_sees_same_menu_everywhere(self):
        expected = [("/", "Dashboard"), ("/monthly/", "Employees"), ("/warehouse/", "Warehouse")]
        for path in ("/", "/monthly/", "/warehouse/"):
            with self.subTest(path=path):
                self.assertEqual(self.nav_links(self.plain, path)[0], expected)


class DashboardFirstPaintTests(StaffTestCase):
    """What the server renders must already be what the page JS would show (no numbers changing after load)."""

    def setUp(self):
        super().setUp()
        from datetime import timedelta
        from django.utils import timezone
        self.today = timezone.localdate()
        self.five_ago = self.today - timedelta(days=5)

        def add(days_ago, kind, amount, desc):
            Transaction.objects.create(type=kind, currency="uzs", method=self.method, amount=amount,
                                       date=self.today - timedelta(days=days_ago), description=desc)
        add(0, "income", 100, "today")
        add(3, "expense", 40, "three days ago")
        add(30, "income", 1000, "last month")

    def test_default_view_is_the_last_five_days(self):
        resp = self.client.get("/")
        self.assertEqual(resp.context["incomes_uzs"], 100)
        self.assertEqual(resp.context["expenses_uzs"], 40)
        self.assertEqual(sorted(t.description for t in resp.context["transactions"]), ["three days ago", "today"])

    def test_first_paint_equals_api_for_the_same_filters(self):
        resp = self.client.get("/")
        api = self.client.get(f"/api/stats/?date_from={self.five_ago}&date_to={self.today}").json()
        for key, value in api.items():
            self.assertEqual(resp.context[key], value, key)

    def test_filter_inputs_are_prefilled_by_the_server(self):
        html = self.client.get("/").content.decode()
        self.assertIn(f'id="dateFromFilter" class="input-field" onchange="applyFilters()" value="{self.five_ago}"', html)
        self.assertIn(f'id="dateToFilter" class="input-field" onchange="applyFilters()" value="{self.today}"', html)

    def test_page_does_not_reload_its_own_data_on_load(self):
        html = self.client.get("/").content.decode()
        self.assertNotIn("setDefaultDates", html)
        self.assertNotIn("Load transactions and stats on page load", html)

    def test_query_string_overrides_the_default(self):
        resp = self.client.get("/?date_from=2000-01-01&type=income")
        self.assertEqual(resp.context["incomes_uzs"], 1100)
        self.assertContains(resp, '<option value="income" selected>Income</option>')

    def test_invalid_query_string_falls_back_to_default(self):
        resp = self.client.get("/?date_from=abc&type=banana")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["incomes_uzs"], 100)

    # The Income / Expense / Balance cards must say which period they add up.
    def test_cards_name_their_period(self):
        label = f"{self.five_ago} \u2013 {self.today}"
        self.assertContains(self.client.get("/"), f'>Totals for {label}</p>')

    def test_open_ended_and_all_time_labels(self):
        self.assertContains(self.client.get("/?date_from=2000-01-01&date_to="), ">Totals from 2000-01-01</p>")
        self.assertContains(self.client.get("/?date_to=2026-02-03"), ">Totals up to 2026-02-03</p>")
        self.assertContains(self.client.get("/?date_from=&date_to="), ">Totals for all time</p>")


class DashboardLooksTheSameAsBeforeTests(StaffTestCase):
    """The first paint must use the same number/date style the page script has always produced."""

    def test_numbers_dates_and_units_use_the_familiar_format(self):
        from django.utils import timezone
        today = timezone.localdate()
        Transaction.objects.create(type="income", currency="uzs", method=self.method, amount=1500000, date=today, description="a")
        Transaction.objects.create(type="income", currency="usd", method=self.method, amount="12.50", date=today, description="b")
        html = self.client.get("/").content.decode()
        for expected in ("1,500,000 UZS", "12.5 USD", f"<td>{today.isoformat()}</td>", "0 AFN"):
            with self.subTest(expected=expected):
                self.assertIn(expected, html)
        for unwanted in ("1.500.000", "$ ", "؋ ", "d-m-Y"):
            with self.subTest(unwanted=unwanted):
                self.assertNotIn(unwanted, html.split("</nav>")[1].split("<script")[0])


class SessionExpiryTests(AuthTestCase):
    """Someone with an old tab open must get a friendly sign-in prompt, never a technical error."""

    def test_stale_csrf_on_fetch_gets_json_and_session_header(self):
        client = self.as_user(self.staff, enforce_csrf=True)
        resp = post_json(client, "/api/transaction/create/", {})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp["X-Session-Expired"], "1")
        self.assertIn("sign in again", resp.json()["error"])

    def test_stale_csrf_on_form_redirects_to_login_for_that_page(self):
        client = self.as_user(self.staff, enforce_csrf=True)
        resp = client.post("/api/warehouse/item/create/", {"name": "x"}, HTTP_REFERER="http://testserver/warehouse/")
        self.assertRedirects(resp, "/login/?next=/warehouse/", fetch_redirect_response=False)

    def test_anonymous_api_call_carries_session_header(self):
        self.assertEqual(self.client.get("/api/stats/")["X-Session-Expired"], "1")

    def test_pages_install_the_session_handler(self):
        html = self.as_user(self.staff).get("/").content.decode()
        self.assertIn("X-Session-Expired", html)


from django.core.cache import cache
from django.test import override_settings

LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "login-throttle-tests"}}


@override_settings(CACHES=LOCMEM)
class LoginThrottleTests(AuthTestCase):
    def setUp(self):
        cache.clear()

    def attempt(self, username="plain", password="wrong", client=None):
        return (client or self.client).post("/login/", {"username": username, "password": password})

    def test_below_the_limit_shows_the_normal_error(self):
        for _ in range(4):
            resp = self.attempt()
        self.assertContains(resp, "Invalid username or password")
        self.assertEqual(resp.status_code, 200)

    def test_too_many_failures_block_even_the_right_password(self):
        for _ in range(5):
            self.attempt()
        resp = self.attempt(password="pw-plain-123")
        self.assertEqual(resp.status_code, 429)
        self.assertContains(resp, "Too many sign-in attempts", status_code=429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_other_usernames_are_not_affected(self):
        for _ in range(5):
            self.attempt()
        resp = self.attempt(username="staff", password="pw-staff-123")
        self.assertEqual(resp.status_code, 302)

    def test_a_good_sign_in_resets_the_counter(self):
        for _ in range(3):
            self.attempt()
        self.assertEqual(self.attempt(password="pw-plain-123").status_code, 302)
        self.client.logout()
        for _ in range(3):
            self.attempt()
        self.assertEqual(self.attempt().status_code, 200)

    def test_username_case_does_not_dodge_the_limit(self):
        for name in ("plain", "PLAIN", "Plain", "pLAIN", "plain"):
            self.attempt(username=name)
        self.assertEqual(self.attempt(username="plain", password="pw-plain-123").status_code, 429)


class WarehouseMovementCapTests(StaffTestCase):
    def setUp(self):
        super().setUp()
        self.item = WarehouseItem.objects.create(name="Flour")
        for n in range(5):
            self.post("/api/warehouse/entry/add/", {"item_id": self.item.id, "type": "in", "quantity": 1,
                                                    "date": "2026-10-01", "description": f"m{n}"})

    def rows(self, html):
        return html.split('id="movements"')[1].count("api/warehouse/entry/") 

    def test_long_history_is_capped_with_a_show_all_link(self):
        from unittest import mock
        from track import views
        with mock.patch.object(views, "WAREHOUSE_MOVEMENT_PAGE_SIZE", 3):
            page = self.client.get("/warehouse/")
            full = self.client.get("/warehouse/?all=1")
        self.assertContains(page, "Showing the latest 3 of 5 movements.")
        self.assertContains(page, 'href="?all=1"')
        self.assertEqual(self.rows(page.content.decode()), 3 + 1)   # 3 rows + the add-movement form action
        self.assertNotContains(full, "Showing the latest")
        self.assertEqual(self.rows(full.content.decode()), 5 + 1)

    def test_short_history_has_no_note(self):
        self.assertNotContains(self.client.get("/warehouse/"), "Showing the latest")



class ReadabilityTests(StaffTestCase):
    def test_comma_fixed2_groups_and_keeps_two_decimals(self):
        from track.templatetags.number_format import comma_fixed2
        self.assertEqual(comma_fixed2(123868), "123,868.00")
        self.assertEqual(comma_fixed2("0.5"), "0.50")
        self.assertEqual(comma_fixed2("-27025168.55"), "-27,025,168.55")
        self.assertEqual(comma_fixed2("junk"), "junk")

    def test_warehouse_numbers_are_grouped_right_aligned_and_zeros_are_quiet(self):
        WarehouseItem.objects.create(name="Wheat", quantity=20678, quantity_kg=Decimal("123868"))
        WarehouseItem.objects.create(name="Empty", quantity=0, quantity_kg=0)
        html = self.client.get("/warehouse/").content.decode()
        self.assertIn('<td class="num">20,678</td>', html)
        self.assertIn('<td class="num">123,868.00</td>', html)
        self.assertIn('<td class="num is-zero">0</td>', html)
        self.assertIn('<td class="num is-zero">0.00</td>', html)
        self.assertIn('<th class="num">Quantity</th>', html)

    def test_monthly_page_formats_amounts_in_the_browser_helpers(self):
        html = self.client.get("/monthly/").content.decode()
        self.assertIn("function formatAmount", html)
        self.assertIn("unicode-bidi: plaintext", html)
        self.assertNotIn(".toFixed(2)", html)
