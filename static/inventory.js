(() => {
  const find = id => document.getElementById(id);
  const section = find('inventory-section');
  const message = find('inventory-message');
  const categoryForm = find('category-form');
  const vehicleForm = find('vehicle-form');
  const availabilityForm = find('availability-form');

  let categoryRecords = [];
  let vehicleRecords = [];
  let editingCategoryId = null;
  let editingVehicleId = null;
  let availabilityVehicleId = null;
  let busy = false;

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

  function jsonOptions(method, data) {
    return {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    };
  }

  function rateText(cents) {
    const value = BigInt(cents);
    return `${value / 100n}.${String(value % 100n).padStart(2, '0')}`;
  }

  function parseRate(value) {
    const text = value.trim();

    if (!/^\d+(\.\d{1,2})?$/.test(text)) {
      throw new Error(
        'Enter a positive daily rate with at most two decimal places.'
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

  function integerValue(form, name, label) {
    const text = form.elements.namedItem(name).value.trim();

    if (!/^\d+$/.test(text)) {
      throw new Error(`${label} must be a nonnegative whole number.`);
    }

    const value = Number(text);

    if (!Number.isSafeInteger(value)) {
      throw new Error(`${label} is outside the supported range.`);
    }

    return value;
  }

  async function run(action, errorTarget = message) {
    if (busy) return;

    busy = true;
    errorTarget.textContent = '';

    const buttons = [...section.querySelectorAll('button')];
    const previousStates = buttons.map(button => button.disabled);
    buttons.forEach(button => { button.disabled = true; });

    try {
      await action();
    } catch (error) {
      errorTarget.textContent = error.message;
    } finally {
      buttons.forEach((button, index) => {
        button.disabled = previousStates[index];
      });
      busy = false;
    }
  }

  function addCell(row, value) {
    const cell = document.createElement('td');
    cell.textContent = String(value);
    row.append(cell);
    return cell;
  }

  function actionButton(cell, label, action) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.addEventListener('click', action);
    cell.append(button);
  }

  function emptyRow(body, columnCount, text) {
    const row = document.createElement('tr');
    const cell = addCell(row, text);
    cell.colSpan = columnCount;
    body.append(row);
  }

  function render() {
    const categoryRows = find('category-rows');
    const vehicleRows = find('vehicle-rows');
    categoryRows.replaceChildren();
    vehicleRows.replaceChildren();

    for (const category of categoryRecords) {
      const row = document.createElement('tr');
      addCell(row, category.category_name);
      addCell(row, `$${rateText(category.standard_daily_rate_cents)}`);

      const actions = addCell(row, '');
      actions.className = 'row-actions';
      actionButton(actions, 'Edit', () => openCategory(category));
      actionButton(actions, 'Delete', () => {
        removeRecord(
          'categories',
          category.category_id,
          category.category_name
        );
      });

      categoryRows.append(row);
    }

    for (const vehicle of vehicleRecords) {
      const row = document.createElement('tr');
      addCell(
        row,
        `${vehicle.model_year} ${vehicle.make} ${vehicle.model}`
      );
      addCell(row, vehicle.category_name);
      addCell(row, vehicle.vin);
      addCell(row, vehicle.registration_no);
      addCell(row, vehicle.odometer_km);

      const actions = addCell(row, '');
      actions.className = 'row-actions';
      actionButton(actions, 'Edit', () => openVehicle(vehicle));
      actionButton(actions, 'Delete', () => {
        removeRecord('vehicles', vehicle.vehicle_id, vehicle.registration_no);
      });
      actionButton(actions, 'Availability', () => {
        openAvailability(vehicle);
      });

      vehicleRows.append(row);
    }

    if (!categoryRecords.length) {
      emptyRow(categoryRows, 3, 'No categories yet. Add a category first.');
    }

    if (!vehicleRecords.length) {
      emptyRow(vehicleRows, 6, 'No vehicles yet.');
    }
  }

  async function loadInventory() {
    const [categories, vehicles] = await Promise.all([
      api('/categories'),
      api('/vehicles'),
    ]);

    categoryRecords = categories.categories;
    vehicleRecords = vehicles.vehicles;
    render();
  }

  function openCategory(category = null) {
    if (busy) return;

    editingCategoryId = category?.category_id ?? null;
    categoryForm.reset();
    find('category-form-error').textContent = '';
    find('category-editor-heading').textContent =
      category ? 'Edit category' : 'Add category';

    if (category) {
      categoryForm.elements.namedItem('category_name').value =
        category.category_name;
      categoryForm.elements.namedItem('daily_rate').value =
        rateText(category.standard_daily_rate_cents);
    }

    find('category-editor').showModal();
  }

  function openVehicle(vehicle = null) {
    if (busy) return;

    if (!categoryRecords.length) {
      message.textContent = 'Add a category before adding a vehicle.';
      return;
    }

    editingVehicleId = vehicle?.vehicle_id ?? null;
    vehicleForm.reset();
    find('vehicle-form-error').textContent = '';
    find('vehicle-editor-heading').textContent =
      vehicle ? 'Edit vehicle' : 'Add vehicle';

    const select = vehicleForm.elements.namedItem('category_id');
    select.replaceChildren();

    for (const category of categoryRecords) {
      select.add(new Option(
        category.category_name,
        String(category.category_id)
      ));
    }

    if (vehicle) {
      for (const field of [
        'category_id', 'vin', 'registration_no',
        'make', 'model', 'model_year', 'odometer_km',
      ]) {
        vehicleForm.elements.namedItem(field).value = vehicle[field];
      }
    } else {
      vehicleForm.elements.namedItem('odometer_km').value = '0';
    }

    find('vehicle-editor').showModal();
  }

  async function refreshAfterSave(text) {
    message.textContent = text;

    try {
      await loadInventory();
    } catch (error) {
      message.textContent =
        `${text} Refresh failed: ${error.message} Click Refresh to retry.`;
    }
  }

  categoryForm.addEventListener('submit', event => {
    event.preventDefault();

    run(async () => {
      const data = {
        category_name:
          categoryForm.elements.namedItem('category_name').value.trim(),
        standard_daily_rate_cents:
          parseRate(categoryForm.elements.namedItem('daily_rate').value),
      };

      const path = editingCategoryId === null
        ? '/categories'
        : `/categories/${editingCategoryId}`;

      const result = await api(
        path,
        jsonOptions(editingCategoryId === null ? 'POST' : 'PUT', data)
      );

      find('category-editor').close();
      await refreshAfterSave(result.message);
    }, find('category-form-error'));
  });

  vehicleForm.addEventListener('submit', event => {
    event.preventDefault();

    run(async () => {
      const data = {};

      for (const field of ['vin', 'registration_no', 'make', 'model']) {
        data[field] = vehicleForm.elements.namedItem(field).value.trim();
      }

      data.category_id = integerValue(vehicleForm, 'category_id', 'Category');
      data.model_year = integerValue(vehicleForm, 'model_year', 'Model year');
      data.odometer_km = integerValue(vehicleForm, 'odometer_km', 'Odometer');

      const path = editingVehicleId === null
        ? '/vehicles'
        : `/vehicles/${editingVehicleId}`;

      const result = await api(
        path,
        jsonOptions(editingVehicleId === null ? 'POST' : 'PUT', data)
      );

      find('vehicle-editor').close();
      await refreshAfterSave(result.message);
    }, find('vehicle-form-error'));
  });

  function removeRecord(resource, id, label) {
    if (busy || !window.confirm(`Delete "${label}"?`)) return;

    run(async () => {
      const result = await api(`/${resource}/${id}`, { method: 'DELETE' });
      await refreshAfterSave(result.message);
    });
  }

  function openAvailability(vehicle) {
    if (busy) return;

    availabilityVehicleId = vehicle.vehicle_id;
    availabilityForm.reset();
    find('availability-result').textContent = '';
    find('availability-heading').textContent =
      `Availability: ${vehicle.registration_no}`;
    find('availability-editor').showModal();
  }

  function timestamp(value) {
    const normalized = value.replace('T', ' ');
    return normalized.length === 16 ? `${normalized}:00` : normalized;
  }

  availabilityForm.addEventListener('submit', event => {
    event.preventDefault();

    run(async () => {
      const query = new URLSearchParams({
        pickup_at: timestamp(
          availabilityForm.elements.namedItem('pickup_at').value
        ),
        due_at: timestamp(
          availabilityForm.elements.namedItem('due_at').value
        ),
      });

      const result = await api(
        `/vehicles/${availabilityVehicleId}/availability?${query}`
      );
      const availability = result.availability;
      const notes = [];

      if (availability.available_for_reservation) {
        notes.push('No rental conflicts for the selected period.');
      } else {
        notes.push(
          'Conflicting rental IDs: '
          + availability.conflicting_rental_ids.join(', ') + '.'
        );
      }

      if (availability.other_active_rental_id !== null) {
        notes.push(
          `Rental ${availability.other_active_rental_id} is still active. `
          + 'Pickup is blocked until it is completed.'
        );
      }

      if (availability.unfinished_maintenance_id !== null) {
        notes.push(
          'Unfinished maintenance blocks pickup until completed.'
        );
      }

      notes.push('Availability must be rechecked at pickup.');
      find('availability-result').textContent = notes.join(' ');
    }, find('availability-result'));
  });

  find('add-category').addEventListener('click', () => openCategory());
  find('add-vehicle').addEventListener('click', () => openVehicle());
  find('refresh-inventory').addEventListener('click', () => {
    run(loadInventory);
  });

  for (const [buttonId, dialogId] of [
    ['cancel-category', 'category-editor'],
    ['cancel-vehicle', 'vehicle-editor'],
    ['close-availability', 'availability-editor'],
  ]) {
    find(buttonId).addEventListener('click', () => {
      if (!busy) find(dialogId).close();
    });

    find(dialogId).addEventListener('cancel', event => {
      if (busy) event.preventDefault();
    });
  }

  function showInventory() {
    section.hidden = window.location.hash !== '#inventory';

    if (!section.hidden) {
      run(loadInventory);
    } else {
      for (const dialog of section.querySelectorAll('dialog[open]')) {
        dialog.close();
      }
    }
  }

  window.addEventListener('hashchange', showInventory);
  showInventory();
})();