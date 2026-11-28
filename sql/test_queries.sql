--Produce rental details
SELECT * FROM rental 
 INNER JOIN customer on customer.customer_id = rental.customer_id 
  INNER JOIN vehicle on vehicle.vehicle_id = rental.vehicle_id
   INNER JOIN vehicle_category on vehicle_category.category_id = vehicle.category_id;

--Show overdue rentals
SELECT * FROM rental
 WHERE rental.status = 'active' AND
       rental.due_at < :REFERENCE_TIME;

-- Calculate charge of rental
WITH rental_totals AS (
    SELECT
        rental.rental_id,
        rental.pickup_at,
        rental.returned_at,
        rental.agreed_daily_rate_cents,
 
        CAST(
            JULIANDAY(
             DATE(
              COALESCE(
               rental.returned_at, :REFERENCE_TIME
               )
            )
        )
        - JULIANDAY(DATE(rental.pickup_at)) + 1 AS INTEGER
        ) AS rental_days,
 
        IFNULL(
            (
                SELECT SUM(payment.amount_cents)
                FROM payment
                WHERE payment.rental_id = rental.rental_id
            ), 0
        ) AS total_payments
 
    FROM rental
    WHERE rental.status NOT IN ('cancelled', 'reserved')
)
SELECT
    rental_id,
    pickup_at,
    returned_at,
    rental_days,
    agreed_daily_rate_cents,
    ((rental_days * agreed_daily_rate_cents))
        AS rental_charge,
    total_payments,
    (((rental_days * agreed_daily_rate_cents) - total_payments))
        AS remaining_balance
FROM rental_totals;

-- Vehicle Availability given time period
SELECT
    vehicle.*
FROM vehicle
-- Find conflicting rentals and reservations
LEFT JOIN rental
    ON rental.vehicle_id = vehicle.vehicle_id
    AND rental.status <> 'cancelled'
    AND JULIANDAY(rental.pickup_at) <
        JULIANDAY(:DROPOFF_DATE)
    AND JULIANDAY(
        CASE
            WHEN rental.status = 'completed'
                THEN rental.returned_at
            ELSE rental.due_at
        END
    ) > JULIANDAY(:PICKUP_DATE)
 
-- Find unfinished maintenance

LEFT JOIN maintenance
    ON maintenance.vehicle_id = vehicle.vehicle_id
    AND maintenance.completed_at IS NULL
    or ( JULIANDAY(maintenance.started_at) <
        JULIANDAY(:DROPOFF_DATE)
    AND JULIANDAY(maintenance.completed_at
    ) > JULIANDAY(:PICKUP_DATE))
 
WHERE
   rental.rental_id IS NULL
    AND maintenance.maintenance_id IS NULL
  
ORDER BY
    vehicle.make,
    vehicle.model,
    vehicle.model_year;


-- Maintenance records Query
SELECT
    maintenance.*,
    vehicle.*,
    CASE
        WHEN maintenance.completed_at IS NULL
            THEN 'unfinished'
        ELSE 'completed'
    END AS completion_state
FROM maintenance
JOIN vehicle
    ON vehicle.vehicle_id = maintenance.vehicle_id
ORDER BY
    maintenance.started_at,
    maintenance.maintenance_id;