import tempfile
import unittest
from pathlib import Path

from app import create_app
from db import get_db


class InventoryTests(unittest.TestCase):
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
            connection.execute(
                """
                INSERT INTO customer (
                    full_name, email, phone, driver_license_no
                ) VALUES ('Test Customer', 'test@example.com', '555', 'TEST1')
                """
            )
            connection.commit()

        response = self.client.post("/api/categories", json={
            "category_name": "Test",
            "standard_daily_rate_cents": 4999,
        })
        self.assertEqual(response.status_code, 201)
        self.category_id = response.get_json()["category"]["category_id"]

        self.vehicle = {
            "category_id": self.category_id,
            "vin": "TEST-VIN",
            "registration_no": "TEST-REG",
            "make": "Honda",
            "model": "Accord",
            "model_year": 2020,
            "odometer_km": 1000,
        }
        response = self.client.post("/api/vehicles", json=self.vehicle)
        self.assertEqual(response.status_code, 201)
        self.vehicle_id = response.get_json()["vehicle"]["vehicle_id"]

    def write(self, sql, parameters=()):
        with self.app.app_context():
            connection = get_db()
            connection.execute(sql, parameters)
            connection.commit()

    def rental(self, status="reserved", returned_at=None):
        self.write(
            """
            INSERT INTO rental (
                customer_id, vehicle_id, pickup_at, due_at,
                returned_at, agreed_daily_rate_cents, status
            ) VALUES (1, ?, ?, ?, ?, 4999, ?)
            """,
            (
                self.vehicle_id,
                "2026-12-01 10:00:00",
                "2026-12-02 10:00:00",
                returned_at,
                status,
            ),
        )

    def availability(
        self,
        pickup="2026-12-01 12:00:00",
        due="2026-12-01 18:00:00",
    ):
        response = self.client.get(
            f"/api/vehicles/{self.vehicle_id}/availability",
            query_string={"pickup_at": pickup, "due_at": due},
        )
        self.assertEqual(response.status_code, 200)
        return response.get_json()["availability"]

    def test_category_validation_and_update(self):
        for rate in (0, -1, 1.5, True, "4999"):
            with self.subTest(rate=rate):
                response = self.client.post("/api/categories", json={
                    "category_name": "Another",
                    "standard_daily_rate_cents": rate,
                })
                self.assertEqual(response.status_code, 400)

        for name in ("", "   ", "Test"):
            with self.subTest(name=name):
                response = self.client.post("/api/categories", json={
                    "category_name": name,
                    "standard_daily_rate_cents": 100,
                })
                self.assertEqual(response.status_code, 400)

        response = self.client.put(
            f"/api/categories/{self.category_id}",
            json={
                "category_name": "Updated",
                "standard_daily_rate_cents": 5999,
            },
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.get(f"/api/categories/{self.category_id}")
        self.assertEqual(
            response.get_json()["category"]["standard_daily_rate_cents"],
            5999,
        )

    def test_vehicle_validation_and_odometer(self):
        invalid_values = [
            ("model_year", 1979),
            ("model_year", 2101),
            ("model_year", 2020.5),
            ("odometer_km", -1),
            ("odometer_km", 999),
            ("odometer_km", True),
            ("vin", " "),
            ("make", ""),
            ("category_id", 999999),
        ]

        for field, value in invalid_values:
            with self.subTest(field=field, value=value):
                data = {**self.vehicle, field: value}
                response = self.client.put(
                    f"/api/vehicles/{self.vehicle_id}", json=data
                )
                self.assertEqual(response.status_code, 400)

        response = self.client.get(f"/api/vehicles/{self.vehicle_id}")
        self.assertEqual(response.get_json()["vehicle"]["odometer_km"], 1000)

        response = self.client.put(
            f"/api/vehicles/{self.vehicle_id}",
            json={**self.vehicle, "odometer_km": 1100},
        )
        self.assertEqual(response.status_code, 200)

    def test_duplicate_vehicle_identifiers(self):
        for changes in (
            {"registration_no": "OTHER-REG"},
            {"vin": "OTHER-VIN"},
        ):
            with self.subTest(changes=changes):
                response = self.client.post(
                    "/api/vehicles", json={**self.vehicle, **changes}
                )
                self.assertEqual(response.status_code, 400)

    def test_referenced_records_cannot_be_deleted(self):
        response = self.client.delete(f"/api/categories/{self.category_id}")
        self.assertEqual(response.status_code, 400)

        self.rental()
        response = self.client.delete(f"/api/vehicles/{self.vehicle_id}")
        self.assertEqual(response.status_code, 400)

    def test_maintenance_history_prevents_deletion(self):
        self.write(
            """
            INSERT INTO maintenance (
                vehicle_id, service_type, started_at,
                completed_at, cost_cents
            ) VALUES (?, 'Oil change', ?, ?, 1000)
            """,
            (
                self.vehicle_id,
                "2026-11-01 10:00:00",
                "2026-11-01 11:00:00",
            ),
        )
        response = self.client.delete(f"/api/vehicles/{self.vehicle_id}")
        self.assertEqual(response.status_code, 400)

    def test_reservation_overlap_and_boundaries(self):
        self.rental()
        self.assertFalse(self.availability()["available_for_reservation"])

        after = self.availability(
            "2026-12-02 10:00:00", "2026-12-03 10:00:00"
        )
        self.assertTrue(after["available_for_reservation"])

        before = self.availability(
            "2026-11-30 10:00:00", "2026-12-01 10:00:00"
        )
        self.assertTrue(before["available_for_reservation"])

    def test_completed_rental_uses_actual_return(self):
        self.rental("completed", "2026-12-03 10:00:00")

        overlap = self.availability(
            "2026-12-02 12:00:00", "2026-12-02 18:00:00"
        )
        self.assertFalse(overlap["available_for_reservation"])

        after = self.availability(
            "2026-12-03 10:00:00", "2026-12-04 10:00:00"
        )
        self.assertTrue(after["available_for_reservation"])

    def test_cancelled_rental_does_not_block(self):
        self.rental("cancelled")
        self.assertTrue(self.availability()["available_for_reservation"])

    def test_active_rental_and_unfinished_maintenance(self):
        self.rental("active")

        future = self.availability(
            "2026-12-04 10:00:00", "2026-12-05 10:00:00"
        )
        self.assertTrue(future["available_for_reservation"])
        self.assertIsNotNone(future["other_active_rental_id"])

        # Finish the rental before starting maintenance.
        self.write(
            """
            UPDATE rental
            SET status = 'completed', returned_at = '2026-12-02 10:00:00'
            WHERE vehicle_id = ?
            """,
            (self.vehicle_id,),
        )
        self.write(
            """
            INSERT INTO maintenance (
                vehicle_id, service_type, started_at, cost_cents
            ) VALUES (?, 'Inspection', '2026-12-03 10:00:00', 0)
            """,
            (self.vehicle_id,),
        )

        future = self.availability(
            "2026-12-04 10:00:00", "2026-12-05 10:00:00"
        )
        self.assertIsNone(future["other_active_rental_id"])
        self.assertIsNotNone(future["unfinished_maintenance_id"])

    def test_invalid_availability_periods(self):
        for pickup, due in (
            ("invalid", "2026-12-02 10:00:00"),
            ("2026-02-30 10:00:00", "2026-12-02 10:00:00"),
            ("2026-12-02 10:00:00", "2026-12-02 10:00:00"),
            ("2026-12-03 10:00:00", "2026-12-02 10:00:00"),
        ):
            with self.subTest(pickup=pickup, due=due):
                response = self.client.get(
                    f"/api/vehicles/{self.vehicle_id}/availability",
                    query_string={"pickup_at": pickup, "due_at": due},
                )
                self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()