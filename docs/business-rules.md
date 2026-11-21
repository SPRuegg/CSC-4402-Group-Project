# Rental Business Rules and Validation Requirements

## Scope

- One rental location, one primary customer/driver per rental, and one specific vehicle per rental.
- The system manages customers, vehicle categories, vehicles, rentals, payments, and maintenance as shown in [Database Design](database-design.md).
- Monetary amounts use integer cents. The website displays dollar amounts.

## Customer and Vehicle Records

| Record | Required validation |
|---|---|
| Customer | Requires a nonblank name, email, phone, and driver-license number. Email and license number must be unique. |
| Vehicle category | Requires a nonblank, unique category name and a positive integer daily rate in cents. Category names are unique. |
| Vehicle | Require an existing category, nonblank VIN, registration, make and model, an integer model year from 1980 through 2100, and a nonnegative integer odometer. VIN and registration are unique. Odometer readings cannot decrease. |

## Rental Lifecycle

| Status | Meaning | Allowed next status |
|---|---|---|
| `reserved` | A customer has reserved a specific vehicle for a defined period. | `active` or `cancelled` |
| `active` | The vehicle has been picked up and its rental has not been finalized. | `completed` |
| `completed` | The vehicle has been returned and its final balance is fully recorded as paid. | None |
| `cancelled` | The reservation ended before pickup and no longer blocks availability. | None |

- Require an existing customer and vehicle, a positive agreed daily rate, and a due time strictly after the pickup time.
- In this model, `pickup_at` is the agreed start of the rental used for booking and billing.
- Allow pickup only at or after `pickup_at` and before `due_at`. An expired reservation has to be edited or cancelled before pickup.
- Customer, vehicle, scheduled times, and agreed rate may be edited only while the rental is reserved.
- `returned_at` is empty for reserved/cancelled rentals and for active rentals until returned. It is required for completed rentals and must be after `pickup_at`.
- A rental becomes overdue when it remains active after its due time. Overdue is a derived condition, and not another stored status.
- Only a reserved rental may be cancelled. Cancellation preserves the record and releases its vehicle.

## Pricing

- Copy the category's advertised daily rate into `agreed_daily_rate_cents` when creating the reservation. A later category-rate change should not change an existing rental's rate.
- Calculate charge in whole 24-hour periods, rounded up, with a one-day minimum.
- The charge covers the agreed term even if the vehicle is returned early. A late return extends the billed period at the same agreed daily rate; there is no separate late penalty.

Before a return is recorded, display the contracted-term quote using `due_at`. Clearly label this as a quote: additional late time is finalized at return. Calculate monetary amounts using integer cents rather than floating-point currency.

## Payments and Return Settlement

- Payments record money received and do not charge a card or transfer money.
- Reserved and cancelled rentals cannot receive payments.
- Require an existing rental, a positive integer amount, a valid payment time, and a method of `cash`, `card`, or `transfer`.
- A payment cannot be before pickup or after the recorded return.
- Total payments cannot exceed the rental charge.
- Calculate the balance as the rental charge minus total payments.
- Complete a rental only when the full final charge is recorded as paid. Any remaining balance has to be recorded before completion.
- Payments may be edited or deleted only while the rental is active.

## Availability and Scheduling

- A vehicle cannot have overlapping reservations unless one is cancelled.
- For completed rentals, use the recorded return time to determine when the vehicle became available.
- Allow only one active rental per vehicle.
- Another rental cannot be picked up until the previous one is returned and completed.
- Future reservations may start after an active rental's due time, but availability has to be checked again at pickup.
- A vehicle with unfinished maintenance cannot be picked up.
- A late return may affect another reservation. Record the actual return and flag the affected reservation for reassignment or cancellation.
- Check availability and save the reservation in the same database transaction so two requests cannot reserve the same time slot.

## Maintenance

- Require an existing vehicle, a nonblank service description, a valid start time, and a nonnegative integer cost in cents. The cost is the quoted or recorded service amount.
- `completed_at` is empty while maintenance is ongoing. When entered, it cannot be before `started_at`.
- Maintenance cannot start while a vehicle is actively rented.
- Only one unfinished maintenance job per vehicle.
- Unfinished maintenance blocks pickup and check future reservations that may be affected.

## Editing and Deletion

- Allow deletion of unused customers, categories, and vehicles, but referenced records cannot be deleted.
- A reserved rental with no payments may be deleted to correct an accidental entry. Otherwise, cancel the reservation to keep its history.
- Keep active, completed, and cancelled rentals, completed rental payments, and started or completed maintenance records.
- Foreign-key checks must remain enabled.
