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

    def test_plain_user_can_still_read_user_list(self):
        self.assertEqual(self.as_user(self.plain).get("/api/users/").status_code, 200)

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


class DotThousandsFilterTests(TestCase):
    def test_formats_whole_and_fractional_numbers(self):
        from track.templatetags.number_format import dot_thousands
        self.assertEqual(dot_thousands(1500000), "1.500.000")
        self.assertEqual(dot_thousands(0), "0")
        self.assertEqual(dot_thousands(12.5), "12,50")
        self.assertEqual(dot_thousands(1234.56), "1.234,56")
        self.assertEqual(dot_thousands(-2500), "-2.500")
        self.assertEqual(dot_thousands("abc"), "abc")


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
        self.assertContains(resp, "Incorrect username or password")

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
            page = self.client.get("/")
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
        for path in ("/", "/monthly/", "/warehouse/", "/users/"):
            with self.subTest(path=path):
                self.assertEqual(self.nav_links(self.plain, path)[0], expected)
