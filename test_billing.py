import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from app import create_app
from db import get_db
import billing


class BillingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.app = create_app({
            "TESTING": True,
            "DATABASE": str(Path(self.temp.name) / "test.sqlite3"),
        })
        self.client = self.app.test_client()

        clock = patch(
            "billing._utc_now",
            return_value=datetime(2030, 1, 10, 12, 0, 0),
        )
        clock.start()
        self.addCleanup(clock.stop)

        with self.app.app_context():
            connection = get_db()
            schema = Path(__file__).parent / "sql" / "schema.sql"
            connection.executescript(schema.read_text(encoding="utf-8"))
            connection.executescript("""
                INSERT INTO customer (
                    customer_id, full_name, email,
                    phone, driver_license_no
                ) VALUES (
                    1, 'Test Customer', 'test@example.com', '555', 'LIC1'
                );

                INSERT INTO vehicle_category (
                    category_id, category_name, standard_daily_rate_cents
                ) VALUES (1, 'Test Category', 5000);

                INSERT INTO vehicle (
                    vehicle_id, category_id, vin, registration_no,
                    make, model, model_year, odometer_km
                ) VALUES (
                    1, 1, 'VIN1', 'REG1', 'Honda', 'Accord', 2020, 1000
                );

                INSERT INTO rental (
                    rental_id, customer_id, vehicle_id,
                    pickup_at, due_at, agreed_daily_rate_cents, status
                ) VALUES (
                    1, 1, 1,
                    '2030-01-01 10:00:00', '2030-01-03 10:00:00',
                    5000, 'active'
                );
            """)

    def write(self, sql, parameters=()):
        with self.app.app_context():
            connection = get_db()
            connection.execute(sql, parameters)
            connection.commit()

    def statement(self, rental_id=1):
        response = self.client.get(
            f"/api/rentals/{rental_id}/statement"
        )
        self.assertEqual(response.status_code, 200)
        return response.get_json()["statement"]

    def pay(self, amount=1000, paid_at="2030-01-01 12:00:00"):
        response = self.client.post("/api/rentals/1/payments", json={
            "amount_cents": amount,
            "paid_at": paid_at,
            "method": "cash",
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["payment"]

    def record_return(self, returned_at="2030-01-02 10:00:00"):
        response = self.client.post("/api/rentals/1/return", json={
            "returned_at": returned_at,
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()["statement"]

    def finish(self):
        self.pay(10000)
        self.record_return()
        response = self.client.post("/api/rentals/1/complete")
        self.assertEqual(response.status_code, 200)

    def test_contracted_quote(self):
        statement = self.statement()
        self.assertEqual(statement["charge_type"], "quote")
        self.assertEqual(statement["billed_days"], 2)
        self.assertEqual(statement["charge_cents"], 10000)
        self.assertEqual(statement["paid_cents"], 0)
        self.assertEqual(statement["balance_cents"], 10000)

    def test_minimum_day_and_rounding(self):
        rental = self.statement()["rental"]

        for due, expected_days in (
            ("2030-01-01 10:00:01", 1),
            ("2030-01-02 10:00:00", 1),
            ("2030-01-02 10:00:01", 2),
        ):
            with self.subTest(due=due):
                charge = billing.calculate_charge({
                    **rental,
                    "due_at": due,
                })
                self.assertEqual(charge["billed_days"], expected_days)
                self.assertEqual(
                    charge["charge_cents"], expected_days * 5000
                )

    def test_early_return_keeps_agreed_term(self):
        statement = self.record_return()
        self.assertEqual(statement["charge_type"], "final")
        self.assertEqual(statement["billed_days"], 2)
        self.assertEqual(statement["charge_cents"], 10000)
        self.assertEqual(statement["rental"]["status"], "active")

    def test_late_preview_does_not_save(self):
        response = self.client.post(
            "/api/rentals/1/return-preview",
            json={"returned_at": "2030-01-03 10:00:01"},
        )
        self.assertEqual(response.status_code, 200)
        preview = response.get_json()["statement"]
        self.assertEqual(preview["charge_type"], "return_preview")
        self.assertEqual(preview["billed_days"], 3)
        self.assertEqual(preview["charge_cents"], 15000)

        saved = self.statement()
        self.assertIsNone(saved["rental"]["returned_at"])
        self.assertEqual(saved["charge_type"], "quote")

    def test_late_return_uses_agreed_rate(self):
        self.write(
            "UPDATE vehicle_category SET standard_daily_rate_cents = 9000"
        )
        statement = self.record_return("2030-01-04 10:00:00")
        self.assertEqual(statement["billed_days"], 3)
        self.assertEqual(statement["charge_cents"], 15000)

    def test_completion_requires_return_and_full_payment(self):
        response = self.client.post("/api/rentals/1/complete")
        self.assertEqual(response.status_code, 400)

        self.pay(2500)
        self.record_return()

        response = self.client.post("/api/rentals/1/complete")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.statement()["rental"]["status"], "active")

        self.pay(7500, "2030-01-02 10:00:00")
        response = self.client.post("/api/rentals/1/complete")
        self.assertEqual(response.status_code, 200)

        statement = self.statement()
        self.assertEqual(statement["rental"]["status"], "completed")
        self.assertEqual(statement["balance_cents"], 0)
        self.assertEqual(len(statement["payments"]), 2)

    def test_invalid_payment_values(self):
        base = {
            "amount_cents": 1000,
            "paid_at": "2030-01-01 12:00:00",
            "method": "cash",
        }

        for changes in (
            {"amount_cents": 0},
            {"amount_cents": -1},
            {"amount_cents": 1.5},
            {"amount_cents": True},
            {"amount_cents": "1000"},
            {"method": "bitcoin"},
            {"method": []},
            {"paid_at": "invalid"},
            {"paid_at": "2030-02-30 10:00:00"},
            {"unexpected": "value"},
        ):
            with self.subTest(changes=changes):
                response = self.client.post(
                    "/api/rentals/1/payments",
                    json={**base, **changes},
                )
                self.assertEqual(response.status_code, 400)

        self.assertEqual(self.statement()["payments"], [])

    def test_payment_time_boundaries(self):
        response = self.client.post("/api/rentals/1/payments", json={
            "amount_cents": 1000,
            "paid_at": "2030-01-01 09:59:59",
            "method": "card",
        })
        self.assertEqual(response.status_code, 400)

        self.pay(1000, "2030-01-01 10:00:00")
        self.record_return()

        response = self.client.post("/api/rentals/1/payments", json={
            "amount_cents": 1000,
            "paid_at": "2030-01-02 10:00:01",
            "method": "transfer",
        })
        self.assertEqual(response.status_code, 400)

        self.pay(1000, "2030-01-02 10:00:00")
        self.assertEqual(self.statement()["paid_cents"], 2000)

    def test_payment_edit_delete_and_overpayment_rollback(self):
        payment = self.pay(2000)
        path = f"/api/rentals/1/payments/{payment['payment_id']}"

        response = self.client.put(path, json={
            "amount_cents": 3000,
            "paid_at": payment["paid_at"],
            "method": "card",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.statement()["paid_cents"], 3000)

        response = self.client.put(path, json={
            "amount_cents": 10001,
            "paid_at": payment["paid_at"],
            "method": "cash",
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.statement()["paid_cents"], 3000)

        response = self.client.post("/api/rentals/1/payments", json={
            "amount_cents": 7001,
            "paid_at": payment["paid_at"],
            "method": "cash",
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(self.statement()["payments"]), 1)

        response = self.client.delete(path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.statement()["paid_cents"], 0)

    def test_reserved_and_cancelled_reject_payments_and_returns(self):
        for status in ("reserved", "cancelled"):
            self.write("UPDATE rental SET status = ?", (status,))

            with self.subTest(status=status):
                responses = [
                    self.client.post("/api/rentals/1/payments", json={
                        "amount_cents": 1000,
                        "paid_at": "2030-01-01 12:00:00",
                        "method": "cash",
                    }),
                    self.client.post("/api/rentals/1/return", json={
                        "returned_at": "2030-01-02 10:00:00",
                    }),
                    self.client.post("/api/rentals/1/complete"),
                ]
                for response in responses:
                    self.assertEqual(response.status_code, 400)

    def test_invalid_return_times_and_repeat_return(self):
        for returned_at in (
            "invalid",
            "2030-01-01 09:00:00",
            "2030-01-01 10:00:00",
            "2030-01-11 10:00:00",
        ):
            with self.subTest(returned_at=returned_at):
                response = self.client.post(
                    "/api/rentals/1/return",
                    json={"returned_at": returned_at},
                )
                self.assertEqual(response.status_code, 400)
                self.assertIsNone(
                    self.statement()["rental"]["returned_at"]
                )

        self.record_return()
        original = self.statement()

        response = self.client.post("/api/rentals/1/return", json={
            "returned_at": "2030-01-03 10:00:00",
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.statement(), original)

    def test_return_cannot_precede_existing_payment(self):
        self.pay(1000, "2030-01-02 12:00:00")

        response = self.client.post("/api/rentals/1/return", json={
            "returned_at": "2030-01-02 10:00:00",
        })
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(self.statement()["rental"]["returned_at"])

    def test_completed_history_is_immutable(self):
        self.finish()
        original = self.statement()
        payment_id = original["payments"][0]["payment_id"]

        responses = [
            self.client.post("/api/rentals/1/payments", json={
                "amount_cents": 1,
                "paid_at": "2030-01-01 12:00:00",
                "method": "cash",
            }),
            self.client.put(
                f"/api/rentals/1/payments/{payment_id}",
                json={
                    "amount_cents": 5000,
                    "paid_at": "2030-01-01 12:00:00",
                    "method": "card",
                },
            ),
            self.client.delete(f"/api/rentals/1/payments/{payment_id}"),
            self.client.post("/api/rentals/1/return", json={
                "returned_at": "2030-01-03 10:00:00",
            }),
            self.client.post("/api/rentals/1/complete"),
        ]

        for response in responses:
            self.assertEqual(response.status_code, 400)

        self.assertEqual(self.statement(), original)

    def test_missing_records(self):
        response = self.client.get("/api/rentals/999/statement")
        self.assertEqual(response.status_code, 404)

        for method in ("get", "put", "delete"):
            with self.subTest(method=method):
                kwargs = {}
                if method == "put":
                    kwargs["json"] = {
                        "amount_cents": 1000,
                        "paid_at": "2030-01-01 12:00:00",
                        "method": "cash",
                    }

                response = getattr(self.client, method)(
                    "/api/rentals/1/payments/999", **kwargs
                )
                self.assertEqual(response.status_code, 404)

    def test_late_return_flags_affected_reservations(self):
        self.write("""
            INSERT INTO rental (
                rental_id, customer_id, vehicle_id,
                pickup_at, due_at, agreed_daily_rate_cents, status
            ) VALUES (
                2, 1, 1, '2030-01-03 10:00:00',
                '2030-01-05 10:00:00', 5000, 'reserved'
            )
        """)

        statement = self.record_return("2030-01-04 10:00:00")
        self.assertEqual(statement["affected_reservation_ids"], [2])
        self.assertEqual(
            self.statement()["affected_reservation_ids"], [2]
        )

        self.write(
            "UPDATE rental SET status = 'cancelled' WHERE rental_id = 2"
        )
        self.assertEqual(
            self.statement()["affected_reservation_ids"], []
        )

    def test_return_database_failure_rolls_back(self):
        self.write("""
            CREATE TRIGGER fail_return
            AFTER UPDATE OF returned_at ON rental
            BEGIN
                SELECT RAISE(ABORT, 'Forced return failure');
            END
        """)

        with self.assertLogs(self.app.logger, level="ERROR"):
            response = self.client.post("/api/rentals/1/return", json={
                "returned_at": "2030-01-02 10:00:00",
            })

        self.assertEqual(response.status_code, 500)
        statement = self.statement()
        self.assertIsNone(statement["rental"]["returned_at"])
        self.assertEqual(statement["rental"]["status"], "active")

        self.write("DROP TRIGGER fail_return")
        self.record_return()

    def test_completion_database_failure_rolls_back(self):
        self.pay(10000)
        self.record_return()
        original = self.statement()

        self.write("""
            CREATE TRIGGER fail_completion
            AFTER UPDATE OF status ON rental
            WHEN NEW.status = 'completed'
            BEGIN
                SELECT RAISE(ABORT, 'Forced completion failure');
            END
        """)

        with self.assertLogs(self.app.logger, level="ERROR"):
            response = self.client.post("/api/rentals/1/complete")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.statement(), original)

    def test_simultaneous_payments_cannot_overpay(self):
        barrier = Barrier(2)

        def pay():
            with self.app.test_client() as client:
                barrier.wait(timeout=10)
                response = client.post("/api/rentals/1/payments", json={
                    "amount_cents": 6000,
                    "paid_at": "2030-01-01 12:00:00",
                    "method": "cash",
                })
                return response.status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(pay) for _ in range(2)]
            statuses = [future.result(timeout=15) for future in futures]

        self.assertEqual(sorted(statuses), [201, 400])
        self.assertEqual(self.statement()["paid_cents"], 6000)
        self.assertEqual(len(self.statement()["payments"]), 1)

    def test_cancelled_rental_has_no_charge(self):
        self.write("UPDATE rental SET status = 'cancelled'")
        statement = self.statement()
        self.assertEqual(statement["charge_type"], "cancelled")
        self.assertEqual(statement["billed_days"], 0)
        self.assertEqual(statement["charge_cents"], 0)
        self.assertEqual(statement["balance_cents"], 0)

    def test_future_payment_create_and_edit_preserve_history(self):
        payment = self.pay(1000)
        original = self.statement()
        data = {
            "amount_cents": 2000,
            "paid_at": "2030-01-10 12:00:01",
            "method": "card",
        }

        responses = [
            self.client.post("/api/rentals/1/payments", json=data),
            self.client.put(
                f"/api/rentals/1/payments/{payment['payment_id']}",
                json=data,
            ),
        ]

        for response in responses:
            self.assertEqual(response.status_code, 400)

        self.assertEqual(self.statement(), original)

        # The mocked clock is exactly this UTC time.
        self.pay(1000, "2030-01-10 12:00:00")

    def test_pending_late_return_blocks_overlap_but_allows_boundary(self):
        self.record_return("2030-01-04 10:00:00")
        self.assertEqual(self.statement()["rental"]["status"], "active")

        details = {
            "customer_id": 1,
            "vehicle_id": 1,
            "pickup_at": "2030-01-03 12:00:00",
            "due_at": "2030-01-05 10:00:00",
        }

        response = self.client.post("/api/rentals", json=details)
        self.assertEqual(response.status_code, 400)

        details["pickup_at"] = "2030-01-04 10:00:00"
        response = self.client.post("/api/rentals", json=details)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.get_json()["rental"]["status"], "reserved"
        )


if __name__ == "__main__":
    unittest.main()