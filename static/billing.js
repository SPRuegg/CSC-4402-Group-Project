(() => {
  const find = id => document.getElementById(id);
  const section = find('billing-section');
  const picker = find('billing-rental');
  const details = find('billing-details');
  const message = find('billing-message');
  const paymentForm = find('payment-form');
  const paymentEditor = find('payment-editor');
  const paymentError = find('payment-form-error');
  const returnForm = find('return-form');
  const previewResult = find('return-preview-result');

  let statement = null;
  let currentId = null;
  let editingPaymentId = null;
  let busy = false;

  const paymentField = name => paymentForm.elements.namedItem(name);
  const returnField = () => returnForm.elements.namedItem('returned_at');

  function decimal(cents) {
    let value = BigInt(cents);
    const sign = value < 0n ? '-' : '';
    if (value < 0n) value = -value;

    return sign + `${value / 100n}.`
      + String(value % 100n).padStart(2, '0');
  }

  function money(cents) {
    return cents < 0
      ? `-$${decimal(-cents)}`
      : `$${decimal(cents)}`;
  }

  function parseAmount(text) {
    text = text.trim();

    if (!/^\d+(\.\d{1,2})?$/.test(text)) {
      throw new Error(
        'Enter a positive amount with at most two decimal places.'
      );
    }

    const [dollars, fraction = ''] = text.split('.');
    const cents = BigInt(dollars) * 100n
      + BigInt(fraction.padEnd(2, '0'));

    if (cents <= 0n || cents > BigInt(Number.MAX_SAFE_INTEGER)) {
      throw new Error('Payment amount is outside the supported range.');
    }

    return Number(cents);
  }

  function timestamp(value) {
    const text = value.replace('T', ' ');
    return text.length === 16 ? `${text}:00` : text;
  }

  function utcInputNow() {
    return new Date().toISOString().slice(0, 19);
  }

  async function api(path, options = {}) {
    let response;

    try {
      response = await fetch(`/api/rentals${path}`, options);
    } catch {
      throw new Error('Cannot connect. Check that Flask is running.');
    }

    const data = await response.json().catch(() => null);

    if (!response.ok) {
      throw new Error(data?.error || 'The request failed.');
    }

    if (!data) {
      throw new Error('The server returned an unexpected response.');
    }

    return data;
  }

  function jsonOptions(method, data) {
    return {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    };
  }

  function updateControls() {
    const active = statement?.rental.status === 'active';
    const returned = Boolean(statement?.rental.returned_at);

    find('add-payment').disabled =
      busy || !active || statement.balance_cents <= 0;

    find('complete-return').disabled =
      busy || !active || !returned || statement.balance_cents !== 0;
  }

  function setBusy(value) {
    busy = value;
    picker.disabled = value;

    section.querySelectorAll('button').forEach(button => {
      button.disabled = value;
    });

    updateControls();
  }

  async function run(action, errorTarget = message) {
    if (busy) return;

    setBusy(true);
    errorTarget.textContent = '';

    try {
      await action();
    } catch (error) {
      errorTarget.textContent = error.message;
    } finally {
      setBusy(false);
    }
  }

  function warningText(ids) {
    return ids.length
      ? 'Late return affects reservation IDs: '
        + ids.join(', ')
        + '. Reassign or cancel these reservations in Reservations.'
      : '';
  }

  function addCell(row, text) {
    const cell = document.createElement('td');
    cell.textContent = String(text);
    row.append(cell);
    return cell;
  }

  function addButton(cell, label, action) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.disabled = busy;
    button.addEventListener('click', action);
    cell.append(button);
  }

  function renderStatement() {
    if (!statement) {
      details.hidden = true;
      updateControls();
      return;
    }

    const rental = statement.rental;
    const active = rental.status === 'active';
    const returned = Boolean(rental.returned_at);
    const quote = statement.charge_type === 'quote';

    details.hidden = false;
    find('billing-rental-heading').textContent =
      `Rental #${rental.rental_id} — ${rental.status}`;

    find('billing-rental-info').textContent =
      `${rental.customer_name} · ${rental.make} ${rental.model}`
      + ` (${rental.registration_no}) · Pickup: ${rental.pickup_at} UTC`
      + ` · Due: ${rental.due_at} UTC`;

    find('billing-charge-label').textContent =
      quote ? 'Contracted-term quote' : 'Final charge';

    find('billing-charge-note').textContent = quote
      ? 'Quote for the agreed term. Additional late time is finalized '
        + 'when the actual return is recorded.'
      : statement.charge_type === 'cancelled'
        ? 'Cancelled reservation: no rental charge.'
        : 'Final charge uses the agreed term or actual return, '
          + 'whichever ends later.';

    find('billing-rate').textContent =
      money(rental.agreed_daily_rate_cents);
    find('billing-days').textContent = statement.billed_days;
    find('billing-charge').textContent = money(statement.charge_cents);
    find('billing-paid').textContent = money(statement.paid_cents);
    find('billing-balance').textContent = money(statement.balance_cents);
    find('billing-warnings').textContent =
      warningText(statement.affected_reservation_ids);

    const body = find('payment-rows');
    body.replaceChildren();

    for (const payment of statement.payments) {
      const row = document.createElement('tr');
      addCell(row, payment.payment_id);
      addCell(row, money(payment.amount_cents));
      addCell(row, payment.paid_at);
      addCell(row, payment.method);

      const actions = addCell(row, '');
      actions.className = 'row-actions';

      if (active) {
        addButton(actions, 'Edit', () => openPayment(payment));
        addButton(actions, 'Delete', () => deletePayment(payment));
      } else {
        actions.textContent = '—';
      }

      body.append(row);
    }

    if (!statement.payments.length) {
      const row = document.createElement('tr');
      const cell = addCell(row, 'No payments recorded.');
      cell.colSpan = 5;
      body.append(row);
    }

    returnForm.hidden = !active || returned;
    find('complete-return').hidden = !active || !returned;
    previewResult.textContent = '';

    if (rental.status === 'completed') {
      find('billing-return-status').textContent =
        `Completed. Actual return: ${rental.returned_at} UTC. `
        + 'Rental and payment history are preserved.';
    } else if (active && returned) {
      find('billing-return-status').textContent =
        `Actual return: ${rental.returned_at} UTC. `
        + (statement.balance_cents === 0
          ? 'Fully paid. Complete the rental to release the vehicle.'
          : 'Record the remaining payment before completion. '
            + 'Payment timestamps must be at or before the return time.');
    } else if (active) {
      find('billing-return-status').textContent =
        'No return recorded. Preview the final bill, then record '
        + 'the actual return. Completion requires full payment.';
    } else {
      find('billing-return-status').textContent =
        'Payments and returns are available only for active rentals.';
    }

    updateControls();
  }

  async function loadStatement(rentalId) {
    statement = null;
    currentId = null;
    renderStatement();

    const data = await api(`/${rentalId}/statement`);
    statement = data.statement;
    currentId = statement.rental.rental_id;
    renderStatement();
  }

  async function loadPage() {
    const wanted = picker.value || String(currentId || '');
    const data = await api('');
    const rentals = [...data.rentals];

    const order = { active: 0, completed: 1, reserved: 2, cancelled: 3 };
    rentals.sort((a, b) =>
      order[a.status] - order[b.status] || b.rental_id - a.rental_id
    );

    picker.replaceChildren();

    for (const rental of rentals) {
      picker.add(new Option(
        `#${rental.rental_id} · ${rental.customer_name} · `
        + `${rental.registration_no} · ${rental.status}`,
        String(rental.rental_id)
      ));
    }

    if (!rentals.length) {
      statement = null;
      currentId = null;
      renderStatement();
      message.textContent = 'No rentals available.';
      return;
    }

    if (rentals.some(rental => String(rental.rental_id) === wanted)) {
      picker.value = wanted;
    }

    await loadStatement(picker.value);
  }

  async function refreshAfterSave(text) {
    message.textContent = text;

    try {
      await loadPage();
    } catch (error) {
      statement = null;
      currentId = null;
      renderStatement();
      message.textContent =
        `${text} Refresh failed: ${error.message} Click Refresh to retry.`;
    }
  }

  function openPayment(payment = null) {
    if (busy || !statement || statement.rental.status !== 'active') return;

    editingPaymentId = payment?.payment_id ?? null;
    paymentForm.reset();
    paymentError.textContent = '';

    find('payment-editor-heading').textContent =
      payment ? 'Edit payment' : 'Record payment';

    paymentField('amount').value = payment
      ? decimal(payment.amount_cents)
      : statement.balance_cents > 0
        ? decimal(statement.balance_cents)
        : '';

    paymentField('paid_at').value = payment
      ? payment.paid_at.replace(' ', 'T')
      : statement.rental.returned_at
        ? statement.rental.returned_at.replace(' ', 'T')
        : utcInputNow();

    paymentField('method').value = payment?.method || 'cash';
    paymentEditor.showModal();
  }

  paymentForm.addEventListener('submit', event => {
    event.preventDefault();

    run(async () => {
      const path = editingPaymentId === null
        ? `/${currentId}/payments`
        : `/${currentId}/payments/${editingPaymentId}`;

      const result = await api(path, jsonOptions(
        editingPaymentId === null ? 'POST' : 'PUT',
        {
          amount_cents: parseAmount(paymentField('amount').value),
          paid_at: timestamp(paymentField('paid_at').value),
          method: paymentField('method').value,
        }
      ));

      paymentEditor.close();
      await refreshAfterSave(result.message);
    }, paymentError);
  });

  function deletePayment(payment) {
    if (busy || !window.confirm(`Delete payment #${payment.payment_id}?`)) {
      return;
    }

    run(async () => {
      const result = await api(
        `/${currentId}/payments/${payment.payment_id}`,
        { method: 'DELETE' }
      );
      await refreshAfterSave(result.message);
    });
  }

  find('preview-return').addEventListener('click', () => {
    if (!returnForm.reportValidity()) return;

    run(async () => {
      const entered = returnField().value;
      const result = await api(
        `/${currentId}/return-preview`,
        jsonOptions('POST', { returned_at: timestamp(entered) })
      );

      // Do not show a result for a time edited while the request ran.
      if (returnField().value !== entered) return;

      const preview = result.statement;
      previewResult.textContent =
        `Preview only; nothing saved. ${preview.billed_days} billed days. `
        + `Final charge: ${money(preview.charge_cents)}. `
        + `Paid: ${money(preview.paid_cents)}. `
        + `Remaining: ${money(preview.balance_cents)}. `
        + warningText(preview.affected_reservation_ids);
    }, previewResult);
  });

  returnField().addEventListener('input', () => {
    previewResult.textContent = '';
  });

  returnForm.addEventListener('submit', event => {
    event.preventDefault();
    if (busy) return;

    const returnedAt = timestamp(returnField().value);

    if (!window.confirm(
      `Record actual return at ${returnedAt} UTC for rental #${currentId}?`
    )) return;

    run(async () => {
      const result = await api(
        `/${currentId}/return`,
        jsonOptions('POST', { returned_at: returnedAt })
      );
      await refreshAfterSave(result.message);
    });
  });

  find('complete-return').addEventListener('click', () => {
    if (busy || !window.confirm(`Complete rental #${currentId}?`)) return;

    run(async () => {
      const result = await api(`/${currentId}/complete`, { method: 'POST' });
      await refreshAfterSave(result.message);
    });
  });

  find('billing-load-form').addEventListener('submit', event => {
    event.preventDefault();
    run(() => loadStatement(picker.value));
  });

  picker.addEventListener('change', () => {
    statement = null;
    currentId = null;
    renderStatement();
    message.textContent = 'Click Load statement for the selected rental.';
  });

  find('refresh-billing').addEventListener('click', () => run(loadPage));
  find('add-payment').addEventListener('click', () => openPayment());

  find('cancel-payment-editor').addEventListener('click', () => {
    if (!busy) paymentEditor.close();
  });

  paymentEditor.addEventListener('cancel', event => {
    if (busy) event.preventDefault();
  });

  function showBilling() {
    section.hidden = window.location.hash !== '#payments';

    if (!section.hidden) {
      run(loadPage);
    } else if (paymentEditor.open) {
      paymentEditor.close();
    }
  }

  window.addEventListener('hashchange', showBilling);
  showBilling();
})();