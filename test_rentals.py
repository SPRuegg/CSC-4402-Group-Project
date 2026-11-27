import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from app import create_app
from db import get_db


class RentalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.app = create_app({
            "TESTING": True,
            "DATABASE": str(Path(self.temp.name) / "test.sqlite3"),
        })
        self.client = self.app.test_client()

        with self.app.app_context():
            connection = get_db()
            schema = Path(__file__).parent / "sql" / "schema.sql"
            connection.executescript(schema.read_text(encoding="utf-8"))
            connection.executescript("""
                INSERT INTO customer (
                    customer_id, full_name, email,
                    phone, driver_license_no
                ) VALUES (1, 'Test Customer', 'test@example.com',
                          '555', 'LICENSE1');

                INSERT INTO vehicle_category (
                    category_id, category_name, standard_daily_rate_cents
                ) VALUES (1, 'Test Category', 5000);

                INSERT INTO vehicle (
                    vehicle_id, category_id, vin, registration_no,
                    make, model, model_year, odometer_km
                ) VALUES (1, 1, 'VIN1', 'REG1',
                          'Honda', 'Accord', 2020, 1000);
            """)

        self.details = {
            "customer_id": 1,
            "vehicle_id": 1,
            "pickup_at": "2030-01-10 10:00:00",
            "due_at": "2030-01-11 10:00:00",
        }

    def write(self, sql, parameters=()):
        with self.app.app_context():
            connection = get_db()
            connection.execute(sql, parameters)
            connection.commit()

    def create(self, **changes):
        response = self.client.post(
            "/api/rentals", json={**self.details, **changes}
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["rental"]

    def get(self, rental_id):
        response = self.client.get(f"/api/rentals/{rental_id}")
        self.assertEqual(response.status_code, 200)
        return response.get_json()["rental"]

    def pickup(self, rental_id, now):
        with patch("rentals._utc_now", return_value=now):
            return self.client.post(f"/api/rentals/{rental_id}/pickup")

    def test_rate_snapshot(self):
        rental = self.create()
        self.assertEqual(rental["status"], "reserved")
        self.assertEqual(rental["agreed_daily_rate_cents"], 5000)
        self.assertIsNone(rental["returned_at"])

        self.write(
            "UPDATE vehicle_category SET standard_daily_rate_cents = 6000"
        )
        saved = self.get(rental["rental_id"])
        self.assertEqual(saved["agreed_daily_rate_cents"], 5000)

    def test_invalid_reservations(self):
        invalid = [
            {"customer_id": 999},
            {"vehicle_id": 999},
            {"customer_id": True},
            {"vehicle_id": "1"},
            {"pickup_at": "invalid"},
            {"pickup_at": "2030-02-30 10:00:00"},
            {"due_at": self.details["pickup_at"]},
            {"due_at": "2030-01-09 10:00:00"},
            {"status": "active"},
            {"agreed_daily_rate_cents": 1},
        ]

        for changes in invalid:
            with self.subTest(changes=changes):
                response = self.client.post(
                    "/api/rentals",
                    json={**self.details, **changes},
                )
                self.assertEqual(response.status_code, 400)

        response = self.client.get("/api/rentals")
        self.assertEqual(response.get_json()["rentals"], [])

    def test_conflicts_and_adjacent_booking(self):
        self.create()

        response = self.client.post("/api/rentals", json={
            **self.details,
            "pickup_at": "2030-01-10 12:00:00",
        })
        self.assertEqual(response.status_code, 400)

        adjacent = self.create(
            pickup_at="2030-01-11 10:00:00",
            due_at="2030-01-12 10:00:00",
        )
        self.assertEqual(adjacent["status"], "reserved")

    def test_edit_preserves_or_explicitly_changes_rate(self):
        rental = self.create()
        rental_id = rental["rental_id"]

        self.write(
            "UPDATE vehicle_category SET standard_daily_rate_cents = 6000"
        )
        edited = {**self.details, "due_at": "2030-01-12 10:00:00"}

        response = self.client.put(
            f"/api/rentals/{rental_id}", json=edited
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.get(rental_id)["agreed_daily_rate_cents"], 5000
        )

        response = self.client.put(
            f"/api/rentals/{rental_id}",
            json={**edited, "agreed_daily_rate_cents": 5500},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.get(rental_id)["agreed_daily_rate_cents"], 5500
        )

        response = self.client.put(
            f"/api/rentals/{rental_id}",
            json={**edited, "agreed_daily_rate_cents": 0},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            self.get(rental_id)["agreed_daily_rate_cents"], 5500
        )

    def test_failed_edit_preserves_original_record(self):
        first = self.create()
        self.create(
            pickup_at="2030-01-12 10:00:00",
            due_at="2030-01-13 10:00:00",
        )

        response = self.client.put(
            f"/api/rentals/{first['rental_id']}",
            json={
                **self.details,
                "due_at": "2030-01-13 10:00:00",
                "agreed_daily_rate_cents": 7000,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.get(first["rental_id"]), first)

    def test_cancellation_preserves_history_and_releases_vehicle(self):
        rental = self.create()
        rental_id = rental["rental_id"]

        response = self.client.post(f"/api/rentals/{rental_id}/cancel")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.get(rental_id)["status"], "cancelled")

        replacement = self.create()
        self.assertNotEqual(replacement["rental_id"], rental_id)

    def test_pickup_time_boundaries_and_repeat_pickup(self):
        rental_id = self.create()["rental_id"]

        for now in (
            datetime(2030, 1, 10, 9, 59, 59),
            datetime(2030, 1, 11, 10, 0, 0),
            datetime(2030, 1, 12, 10, 0, 0),
        ):
            with self.subTest(now=now):
                response = self.pickup(rental_id, now)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self.get(rental_id)["status"], "reserved")

        now = datetime(2030, 1, 10, 10, 0, 0)
        response = self.pickup(rental_id, now)
        self.assertEqual(response.status_code, 200)
        saved = self.get(rental_id)
        self.assertEqual(saved["status"], "active")
        self.assertEqual(saved["pickup_at"], self.details["pickup_at"])
        self.assertIsNone(saved["returned_at"])

        response = self.pickup(rental_id, now)
        self.assertEqual(response.status_code, 400)

    def test_maintenance_is_rechecked_at_pickup(self):
        rental_id = self.create()["rental_id"]

        self.write("""
            INSERT INTO maintenance (
                vehicle_id, service_type, started_at, cost_cents
            ) VALUES (1, 'Inspection', '2030-01-10 09:00:00', 0)
        """)

        response = self.pickup(
            rental_id, datetime(2030, 1, 10, 10, 0, 0)
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.get(rental_id)["status"], "reserved")

        self.write("""
            UPDATE maintenance
            SET completed_at = '2030-01-10 09:30:00'
        """)

        response = self.pickup(
            rental_id, datetime(2030, 1, 10, 10, 0, 0)
        )
        self.assertEqual(response.status_code, 200)

    def test_overdue_active_rental_blocks_later_pickup(self):
        self.write("""
            INSERT INTO rental (
                customer_id, vehicle_id, pickup_at, due_at,
                agreed_daily_rate_cents, status
            ) VALUES (
                1, 1, '2030-01-08 10:00:00', '2030-01-09 10:00:00',
                5000, 'active'
            )
        """)

        # Booking after the previous due time is permitted.
        rental_id = self.create()["rental_id"]

        # Pickup still requires the previous rental to be completed.
        response = self.pickup(
            rental_id, datetime(2030, 1, 10, 10, 0, 0)
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.get(rental_id)["status"], "reserved")

    def test_nonreserved_rentals_reject_changes(self):
        rental_id = self.create()["rental_id"]

        for status in ("active", "completed", "cancelled"):
            returned = (
                "2030-01-11 10:00:00" if status == "completed" else None
            )
            self.write(
                "UPDATE rental SET status = ?, returned_at = ? "
                "WHERE rental_id = ?",
                (status, returned, rental_id),
            )
            original = self.get(rental_id)

            with self.subTest(status=status):
                responses = [
                    self.client.put(
                        f"/api/rentals/{rental_id}", json=self.details
                    ),
                    self.client.post(f"/api/rentals/{rental_id}/cancel"),
                    self.pickup(
                        rental_id, datetime(2030, 1, 10, 10, 0, 0)
                    ),
                    self.client.delete(f"/api/rentals/{rental_id}"),
                ]

                for response in responses:
                    self.assertEqual(response.status_code, 400)

                self.assertEqual(self.get(rental_id), original)

    def test_delete_only_unpaid_reservations(self):
        rental_id = self.create()["rental_id"]

        # Defensive fixture: even an inconsistent reserved rental
        # with a payment must not be deleted.
        self.write(
            """
            INSERT INTO payment (
                rental_id, amount_cents, paid_at, method
            ) VALUES (?, 100, '2030-01-10 10:00:00', 'cash')
            """,
            (rental_id,),
        )

        response = self.client.delete(f"/api/rentals/{rental_id}")
        self.assertEqual(response.status_code, 400)

        self.write("DELETE FROM payment WHERE rental_id = ?", (rental_id,))
        response = self.client.delete(f"/api/rentals/{rental_id}")
        self.assertEqual(response.status_code, 200)
        response = self.client.get(f"/api/rentals/{rental_id}")
        self.assertEqual(response.status_code, 404)

    def test_missing_rental_returns_404(self):
        responses = [
            self.client.get("/api/rentals/999"),
            self.client.put("/api/rentals/999", json=self.details),
            self.client.post("/api/rentals/999/cancel"),
            self.client.post("/api/rentals/999/pickup"),
            self.client.delete("/api/rentals/999"),
        ]

        for response in responses:
            self.assertEqual(response.status_code, 404)

    def test_simultaneous_requests_cannot_double_book(self):
        barrier = Barrier(2)

        def reserve():
            with self.app.test_client() as client:
                barrier.wait(timeout=10)
                response = client.post("/api/rentals", json=self.details)
                return response.status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(reserve) for _ in range(2)]
            statuses = [future.result(timeout=15) for future in futures]

        self.assertEqual(sorted(statuses), [201, 400])
        response = self.client.get("/api/rentals")
        self.assertEqual(len(response.get_json()["rentals"]), 1)

    def test_database_failure_rolls_back_insert(self):
        # Force failure after an INSERT has started modifying the DB.
        self.write("""
            CREATE TRIGGER fail_rental_insert
            AFTER INSERT ON rental
            BEGIN
                SELECT RAISE(ABORT, 'Forced test failure');
            END
        """)

        with self.assertLogs(self.app.logger, level="ERROR"):
            response = self.client.post("/api/rentals", json=self.details)

        self.assertEqual(response.status_code, 500)
        response = self.client.get("/api/rentals")
        self.assertEqual(response.get_json()["rentals"], [])

        # The failed transaction must also leave the DB usable.
        self.write("DROP TRIGGER fail_rental_insert")
        self.create()


if __name__ == "__main__":
    unittest.main()