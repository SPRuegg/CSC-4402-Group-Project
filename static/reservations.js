(() => {
  const find = id => document.getElementById(id);
  const section = find('reservations-section');
  const form = find('reservation-form');
  const editor = find('reservation-editor');
  const message = find('reservation-message');
  const formError = find('reservation-form-error');
  const search = find('reservation-search');
  const statusFilter = find('reservation-status');

  const extraFilters = find('reservation-extra-filters');
  const filterToggle = find('toggle-reservation-filters');
  const matchStartToggle = find('reservation-match-start');
  const filterNames = ['id', 'customer', 'vehicle', 'registration'];
  const filterInputs = ['customer', 'vehicle', 'registration']
    .map(name => find(`reservation-filter-${name}`));
  let filtersExpanded = false;
  let matchFromStart = false;

  function readNamedFilters(text) {
    if (!text.trim()) return ['', '', '', ''];
    const values = ['', '', '', ''];
    const pattern = /\s*(id|customer|vehicle|registration)\s*:\s*("(?:\\.|[^"\\])*")\s*(,|$)/giy;
    let position = 0;
    while (position < text.length) {
      pattern.lastIndex = position;
      const match = pattern.exec(text);
      if (!match) return null;
      try { values[filterNames.indexOf(match[1].toLowerCase())] = JSON.parse(match[2]); }
      catch { return null; }
      position = pattern.lastIndex;
      if (match[3] === ',' && !text.slice(position).trim()) return null;
    }
    return values;
  }

  function matchesSearch(value, query) {
    const text = String(value).toLowerCase();
    return matchFromStart ? text.startsWith(query) : text.includes(query);
  }

  let records = [];
  let customers = [];
  let vehicles = [];
  let editingId = null;
  let busy = false;
  let page = 1;
  let pages = 1;
  const pageSize = 15;

  const field = name => form.elements.namedItem(name);

  async function api(path, options = {}) {
    let response;

    try {
      response = await fetch(`/api${path}`, options);
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

  function rateText(cents) {
    const value = BigInt(cents);
    return `${value / 100n}.${String(value % 100n).padStart(2, '0')}`;
  }

  function parseRate(text) {
    text = text.trim();

    if (!/^\d+(\.\d{1,2})?$/.test(text)) {
      throw new Error(
        'Enter a positive rate with at most two decimal places.'
      );
    }

    const [dollars, fraction = ''] = text.split('.');
    const cents = BigInt(dollars) * 100n
      + BigInt(fraction.padEnd(2, '0'));

    if (cents <= 0n || cents > BigInt(Number.MAX_SAFE_INTEGER)) {
      throw new Error('Daily rate is outside the supported range.');
    }

    return Number(cents);
  }

  function timestamp(value) {
    const text = value.replace('T', ' ');
    return text.length === 16 ? `${text}:00` : text;
  }

  function updatePagination() {
    find('reservation-prev-page').disabled = busy || page <= 1;
    find('reservation-next-page').disabled = busy || page >= pages;
    find('reservation-page-info').textContent = `Page ${page} of ${pages}`;
  }

  function setBusy(value) {
    busy = value;
    section.querySelectorAll('button').forEach(button => {
      button.disabled = value;
    });
    updatePagination();
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

  function addCell(row, value) {
    const cell = document.createElement('td');
    cell.textContent = String(value);
    row.append(cell);
    return cell;
  }

  function addButton(cell, text, action) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = text;
    button.disabled = busy;
    button.addEventListener('click', action);
    cell.append(button);
  }

  function render() {
    const query = search.value.trim().toLowerCase();
    const activeFilters = filtersExpanded
      ? [search.value, ...filterInputs.map(input => input.value)]
      : readNamedFilters(search.value);
    const matches = records.filter(rental => {
      if (statusFilter.value && rental.status !== statusFilter.value) return false;
      const vehicleParts = [String(rental.model_year), rental.make, rental.model];
      const values = [String(rental.rental_id), rental.customer_name,
        vehicleParts.join(' '), rental.registration_no];
      if (activeFilters === null) {
        return [...values, ...vehicleParts].some(value => matchesSearch(value, query));
      }
      return activeFilters.every((value, index) => {
        const criterion = value.trim().toLowerCase();
        if (!criterion) return true;
        const candidates = index === 2 ? [values[index], ...vehicleParts] : [values[index]];
        return candidates.some(candidate => matchesSearch(candidate, criterion));
      });
    });

    pages = Math.max(1, Math.ceil(matches.length / pageSize));
    page = Math.min(page, pages);

    const body = find('reservation-rows');
    body.replaceChildren();

    const start = (page - 1) * pageSize;

    for (const rental of matches.slice(start, start + pageSize)) {
      const row = document.createElement('tr');
      addCell(row, rental.rental_id);
      addCell(row, rental.customer_name);
      addCell(
        row,
        `${rental.model_year} ${rental.make} ${rental.model}`
        + ` (${rental.registration_no})`
      );
      addCell(row, rental.pickup_at);
      addCell(row, rental.due_at);
      addCell(row, `$${rateText(rental.agreed_daily_rate_cents)}`);
      addCell(row, rental.status.charAt(0).toUpperCase() + rental.status.slice(1));

      const actions = addCell(row, '');

      if (rental.status === 'reserved') {
        const buttons = document.createElement('div');
        buttons.className = 'reservation-actions';
        actions.append(buttons);
        addButton(buttons, 'Edit', () => openEditor(rental.rental_id));
        addButton(buttons, 'Pick up', () => {
          changeRental(rental, 'pickup', 'Record pickup for');
        });
        addButton(buttons, 'Cancel', () => {
          changeRental(rental, 'cancel', 'Cancel');
        });
        addButton(buttons, 'Delete', () => {
          changeRental(rental, 'delete', 'Delete');
        });
      } else {
        actions.textContent = '—';
      }

      body.append(row);
    }

    if (!matches.length) {
      const row = document.createElement('tr');
      const cell = addCell(row, 'No matching reservations.');
      cell.colSpan = 8;
      body.append(row);
    }

    find('reservation-list-status').textContent = matches.length
      ? `Showing ${start + 1}–${Math.min(start + pageSize, matches.length)}`
        + ` of ${matches.length} rentals`
      : 'No matching reservations.';

    find('reservation-pagination').hidden = matches.length === 0;
    updatePagination();
  }

  async function loadData() {
    const [rentalData, customerData, vehicleData] = await Promise.all([
      api('/rentals'),
      api('/customers'),
      api('/vehicles'),
    ]);

    records = rentalData.rentals;
    customers = customerData.customers;
    vehicles = vehicleData.vehicles;
    render();
  }

  function updateRateNote() {
    if (editingId !== null) {
      find('reservation-rate-note').textContent =
        'The existing agreed rate is preserved unless you edit it.';
      return;
    }

    const vehicle = vehicles.find(
      item => String(item.vehicle_id) === field('vehicle_id').value
    );

    find('reservation-rate-note').textContent = vehicle
      ? `Current advertised daily rate: `
        + `$${rateText(vehicle.standard_daily_rate_cents)}. `
        + 'The current rate will be copied when you save.'
      : 'Select a vehicle to see its daily rate.';
  }

  function openEditor(rentalId = null) {
    run(async () => {
      // Reload choices and records before opening the form.
      await loadData();

      if (!customers.length || !vehicles.length) {
        throw new Error(
          'Add at least one customer and vehicle before reserving.'
        );
      }

      const rental = rentalId === null
        ? null
        : (await api(`/rentals/${rentalId}`)).rental;

      if (rental && rental.status !== 'reserved') {
        throw new Error('Only reserved rentals can be edited.');
      }

      editingId = rentalId;
      form.reset();
      formError.textContent = '';

      field('customer_id').replaceChildren();
      field('vehicle_id').replaceChildren();

      for (const customer of customers) {
        field('customer_id').add(new Option(
          `${customer.full_name} (#${customer.customer_id})`,
          String(customer.customer_id)
        ));
      }

      for (const vehicle of vehicles) {
        field('vehicle_id').add(new Option(
          `${vehicle.make} ${vehicle.model} (${vehicle.registration_no})`,
          String(vehicle.vehicle_id)
        ));
      }

      find('reservation-editor-heading').textContent =
        rental ? 'Edit reservation' : 'New reservation';

      find('reservation-rate-field').hidden = !rental;
      field('agreed_rate').disabled = !rental;
      field('agreed_rate').required = Boolean(rental);

      if (rental) {
        field('customer_id').value = rental.customer_id;
        field('vehicle_id').value = rental.vehicle_id;
        field('pickup_at').value = rental.pickup_at.replace(' ', 'T');
        field('due_at').value = rental.due_at.replace(' ', 'T');
        field('agreed_rate').value =
          rateText(rental.agreed_daily_rate_cents);
      }

      updateRateNote();
      editor.showModal();
    });
  }

  async function refreshAfterSave(text) {
    message.textContent = text;

    try {
      await loadData();
    } catch (error) {
      message.textContent =
        `${text} Refresh failed: ${error.message} Click Refresh to retry.`;
    }
  }

  form.addEventListener('submit', event => {
    event.preventDefault();

    run(async () => {
      const customerId = Number(field('customer_id').value);
      const vehicleId = Number(field('vehicle_id').value);

      if (
        !Number.isSafeInteger(customerId) || customerId <= 0
        || !Number.isSafeInteger(vehicleId) || vehicleId <= 0
      ) {
        throw new Error('Select an existing customer and vehicle.');
      }

      const data = {
        customer_id: customerId,
        vehicle_id: vehicleId,
        pickup_at: timestamp(field('pickup_at').value),
        due_at: timestamp(field('due_at').value),
      };

      if (editingId !== null) {
        data.agreed_daily_rate_cents =
          parseRate(field('agreed_rate').value);
      }

      const path = editingId === null
        ? '/rentals'
        : `/rentals/${editingId}`;

      const result = await api(path, {
        method: editingId === null ? 'POST' : 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });

      editor.close();
      await refreshAfterSave(
        `${result.message} Rental ID: ${result.rental.rental_id}.`
      );
    }, formError);
  });

  function changeRental(rental, action, question) {
    if (busy) return;

    if (!window.confirm(`${question} reservation #${rental.rental_id}?`)) {
      return;
    }

    run(async () => {
      const path = action === 'delete'
        ? `/rentals/${rental.rental_id}`
        : `/rentals/${rental.rental_id}/${action}`;

      const result = await api(path, {
        method: action === 'delete' ? 'DELETE' : 'POST',
      });

      await refreshAfterSave(result.message);
    });
  }

  find('add-reservation').addEventListener('click', () => openEditor());
  find('refresh-reservations').addEventListener('click', () => {
    run(loadData);
  });

  field('vehicle_id').addEventListener('change', updateRateNote);

  find('cancel-reservation-editor').addEventListener('click', () => {
    if (!busy) editor.close();
  });

  editor.addEventListener('cancel', event => {
    if (busy) event.preventDefault();
  });

  function resetSearchPage() {
    page = 1;
    render();
  }

  search.addEventListener('input', resetSearchPage);
  filterInputs.forEach(input => input.addEventListener('input', resetSearchPage));
  filterToggle.addEventListener('click', () => {
    if (filtersExpanded) {
      search.value = [search.value, ...filterInputs.map(input => input.value)]
        .map((value, index) => value.trim()
          ? `${filterNames[index]}: ${JSON.stringify(value.trim())}` : '')
        .filter(Boolean).join(', ');
    } else {
      const parsed = readNamedFilters(search.value);
      // Preserve a plain, all-field search as a named customer criterion when expanding.
      const values = parsed ?? ['', search.value, '', ''];
      [search, ...filterInputs].forEach((input, index) => { input.value = values[index]; });
    }
    filtersExpanded = !filtersExpanded;
    extraFilters.classList.toggle('expanded', filtersExpanded);
    extraFilters.inert = !filtersExpanded;
    extraFilters.setAttribute('aria-hidden', String(!filtersExpanded));
    filterToggle.setAttribute('aria-expanded', String(filtersExpanded));
    filterToggle.textContent = filtersExpanded ? 'Collapse filters' : 'Expand filters';
    find('reservation-search-label').textContent = filtersExpanded ? 'Rental ID' : 'Search reservations';
    search.placeholder = filtersExpanded ? 'Rental ID' : 'Rental ID, customer, vehicle, or registration';
    resetSearchPage();
  });
  matchStartToggle.addEventListener('click', () => {
    matchFromStart = !matchFromStart;
    matchStartToggle.setAttribute('aria-pressed', String(matchFromStart));
    resetSearchPage();
  });
  find('clear-reservation-filters').addEventListener('click', () => {
    [search, ...filterInputs].forEach(input => { input.value = ''; });
    resetSearchPage();
    search.focus();
  });

  statusFilter.addEventListener('change', () => {
    page = 1;
    render();
  });

  find('reservation-prev-page').addEventListener('click', () => {
    if (!busy && page > 1) {
      page -= 1;
      render();
    }
  });

  find('reservation-next-page').addEventListener('click', () => {
    if (!busy && page < pages) {
      page += 1;
      render();
    }
  });

  function showReservations() {
    section.hidden = window.location.hash !== '#reservations';

    if (!section.hidden) {
      run(loadData);
    } else if (editor.open) {
      editor.close();
    }
  }

  window.addEventListener('hashchange', showReservations);
  showReservations();
})();