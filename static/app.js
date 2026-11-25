const section = document.querySelector('#customers-section');
const form = document.querySelector('#customer-form');
const editor = document.querySelector('#customer-editor');
const message = document.querySelector('#customer-message');
const formError = document.querySelector('#customer-form-error');
const listStatus = document.querySelector('#customer-list-status');
const table = document.querySelector('#customer-table');
const rows = document.querySelector('#customer-rows');
const search = document.querySelector('#customer-search');
const matchStartToggle = document.querySelector('#customer-match-start');
let matchFromStart = false;
const filterToggle = document.querySelector('#toggle-customer-filters');
const extraFilters = document.querySelector('#customer-extra-filters');
const filterInputs = ['filter-last-name', 'filter-email', 'filter-phone', 'filter-license'].map(id => document.getElementById(id));
let filtersExpanded = false;
const addButton = document.querySelector('#add-customer');
const refreshButton = document.querySelector('#refresh-customers');
const pagination = document.querySelector('#customer-pagination');
const previousPage = document.querySelector('#customer-prev-page');
const nextPage = document.querySelector('#customer-next-page');
const pageInfo = document.querySelector('#customer-page-info');
const pageSize = 15;
let currentPage = 1;
let totalPages = 1;
const fields = ['full_name', 'email', 'phone', 'driver_license_no'];
let customers = [];
let editingId = null;
let editorTrigger = null;
let busy = false;
let loading = false;
let messageTimer;

function showMessage(text = '', kind = '') {
  window.clearTimeout(messageTimer);
  message.textContent = text;
  message.dataset.kind = kind;
  if (text && kind === 'success') {
    messageTimer = window.setTimeout(() => {
      message.textContent = '';
      delete message.dataset.kind;
    }, 4000);
  }
}

async function api(path = '', options = {}) {
  let response;
  try {
    response = await fetch(`/api/customers${path}`, options);
  } catch {
    throw new Error('Cannot connect to the application. Check that Flask is running and try again.');
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(data?.error || 'Unable to complete the request. Please try again.');
  if (!data) throw new Error('The application returned an unexpected response. Please try again.');
  return data;
}

function setBusy(value) {
  busy = value;
  section.querySelectorAll('button, #customer-form input').forEach(control => {
    control.disabled = value;
  });
  refreshButton.disabled = value || loading;
  form.setAttribute('aria-busy', String(value));
  updatePageButtons();
}

function updatePageButtons() {
  previousPage.disabled = busy || loading || currentPage <= 1;
  nextPage.disabled = busy || loading || currentPage >= totalPages;
}

function resetSearchPage() {
  currentPage = 1;
  if (!loading) renderCustomers();
}

const filterNames = ['first', 'last', 'email', 'phone', 'license'];

function readNamedFilters(text) {
  if (!text.trim()) return ['', '', '', '', ''];
  const values = ['', '', '', '', ''];
  const pattern = /\s*(first|last|email|phone|license)\s*:\s*("(?:\\.|[^"\\])*")\s*(,|$)/giy;
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

function writeNamedFilters(values) {
  return values.map((value, index) => value.trim() ? `${filterNames[index]}: ${JSON.stringify(value.trim())}` : '')
    .filter(Boolean).join(', ');
}

function matchesSearch(value, query) {
  const text = value.toLowerCase();
  return matchFromStart ? text.startsWith(query) : text.includes(query);
}

function renderCustomers() {
  rows.replaceChildren();
  const query = search.value.trim().toLowerCase();
  const activeFilters = filtersExpanded ? [search.value, ...filterInputs.map(input => input.value)] : readNamedFilters(search.value);
  const matches = customers.filter(customer => {
    if (activeFilters === null) return fields.some(field => matchesSearch(customer[field], query));
    // The model stores a full name: use its first word as first name and the remainder as last name.
    const [firstName, ...lastName] = customer.full_name.trim().split(/\s+/);
    const values = [firstName, lastName.join(' '), customer.email, customer.phone, customer.driver_license_no];
    const queries = activeFilters.map(value => value.trim().toLowerCase());
    return queries.every((value, index) => matchesSearch(values[index], value));
  });
  totalPages = Math.max(1, Math.ceil(matches.length / pageSize));
  currentPage = Math.min(currentPage, totalPages);
  const start = (currentPage - 1) * pageSize;
  const pageCustomers = matches.slice(start, start + pageSize);
  pagination.hidden = matches.length === 0;
  pageInfo.textContent = `Page ${currentPage} of ${totalPages}`;
  updatePageButtons();
  table.hidden = matches.length === 0;
  listStatus.textContent = matches.length ? `Showing ${start + 1}–${start + pageCustomers.length} of ${matches.length} customer${matches.length === 1 ? '' : 's'}` :
    (customers.length ? 'No customers match your search.' : 'No customers yet. Add a customer to get started.');
  pageCustomers.forEach(customer => {
    const row = document.createElement('tr');
    fields.forEach(field => {
      const cell = document.createElement('td');
      cell.textContent = customer[field];
      row.append(cell);
    });
    const actions = document.createElement('td');
    actions.className = 'row-actions';
    ['Edit', 'Delete'].forEach(action => {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = action;
      button.setAttribute('aria-label', `${action} ${customer.full_name}`);
      button.disabled = busy;
      button.addEventListener('click', () => action === 'Edit' ? openEditor(customer) : deleteCustomer(customer));
      actions.append(button);
    });
    row.append(actions);
    rows.append(row);
  });
}

async function loadCustomers() {
  if (loading) return;
  loading = true;
  refreshButton.disabled = true;
  listStatus.textContent = 'Loading customers…';
  table.setAttribute('aria-busy', 'true');
  try {
    const data = await api();
    customers = data.customers;
    renderCustomers();
  } catch (error) {
    table.hidden = true;
    pagination.hidden = true;
    listStatus.textContent = `${error.message} Use Refresh to retry.`;
  } finally {
    loading = false;
    refreshButton.disabled = busy;
    updatePageButtons();
    table.removeAttribute('aria-busy');
  }
}

function openEditor(customer = null) {
  if (busy) return;
  editorTrigger = document.activeElement;
  editingId = customer?.customer_id ?? null;
  form.reset();
  fields.forEach(field => { form.elements[field].value = customer?.[field] ?? ''; });
  document.querySelector('#editor-heading').textContent = customer ? 'Edit customer' : 'Add customer';
  formError.textContent = '';
  form.elements.email.removeAttribute('aria-invalid');
  form.elements.email.removeAttribute('aria-describedby');
  showMessage();
  editor.showModal();
  form.elements.full_name.focus();
}

function closeEditor() {
  editor.close();
  editingId = null;
  form.reset();
  if (editorTrigger?.isConnected) editorTrigger.focus();
  else addButton.focus();
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  if (busy) return;
  const data = Object.fromEntries(fields.map(field => [field, form.elements[field].value.trim()]));
  formError.textContent = '';
  const blank = fields.find(field => !data[field]);
  if (blank) {
    formError.textContent = 'Complete all customer fields.';
    form.elements[blank].focus();
    return;
  }
  const emailInput = form.elements.email;
  if (emailInput.validity.typeMismatch) {
    formError.textContent = 'Enter a valid email address, such as jane@example.com.';
    emailInput.setAttribute('aria-invalid', 'true');
    emailInput.setAttribute('aria-describedby', 'customer-form-error');
    emailInput.focus();
    return;
  }
  emailInput.removeAttribute('aria-invalid');
  emailInput.removeAttribute('aria-describedby');
  setBusy(true);
  let saved = false;
  try {
    const result = await api(editingId === null ? '' : `/${editingId}`, {
      method: editingId === null ? 'POST' : 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    showMessage(result.message, 'success');
    saved = true;
    await loadCustomers();
  } catch (error) {
    formError.textContent = error.message;
  } finally {
    setBusy(false);
    if (saved) closeEditor();
  }
});

async function deleteCustomer(customer) {
  if (busy || !window.confirm(`Delete ${customer.full_name}? This cannot be undone. Customers with rental history cannot be deleted.`)) return;
  setBusy(true);
  showMessage();
  try {
    const result = await api(`/${customer.customer_id}`, { method: 'DELETE' });
    showMessage(result.message, 'success');
    if (editingId === customer.customer_id) closeEditor();
    await loadCustomers();
  } catch (error) {
    showMessage(error.message, 'error');
  } finally {
    setBusy(false);
    refreshButton.focus();
  }
}

function showSection() {
  const hash = window.location.hash || '#dashboard';
  document.querySelectorAll('.nav-item').forEach(tab => {
    const active = tab.getAttribute('href') === hash;
    tab.classList.toggle('active', active);
    if (active) tab.setAttribute('aria-current', 'page');
    else tab.removeAttribute('aria-current');
  });
  section.hidden = hash !== '#customers';
  if (!section.hidden) loadCustomers();
}

addButton.addEventListener('click', () => openEditor());
document.querySelector('#cancel-customer').addEventListener('click', closeEditor);
refreshButton.addEventListener('click', loadCustomers);
search.addEventListener('input', resetSearchPage);
window.addEventListener('hashchange', showSection);
showSection();

filterToggle.addEventListener('click', () => {
  if (filtersExpanded) {
    search.value = writeNamedFilters([search.value, ...filterInputs.map(input => input.value)]);
  } else {
    const values = readNamedFilters(search.value) ?? [search.value, '', '', '', ''];
    [search, ...filterInputs].forEach((input, index) => { input.value = values[index]; });
  }
  filtersExpanded = !filtersExpanded;
  extraFilters.classList.toggle('expanded', filtersExpanded);
  extraFilters.inert = !filtersExpanded;
  extraFilters.setAttribute('aria-hidden', String(!filtersExpanded));
  filterToggle.setAttribute('aria-expanded', String(filtersExpanded));
  filterToggle.textContent = filtersExpanded ? 'Collapse filters' : 'Expand filters';
  document.querySelector('#customer-search-label').textContent = filtersExpanded ? 'First Name' : 'Search customers';
  search.placeholder = filtersExpanded ? 'First name' : 'Name, email, phone, or license';
  resetSearchPage();
});
filterInputs.forEach(input => input.addEventListener('input', resetSearchPage));
document.querySelector('#clear-customer-filters').addEventListener('click', () => {
  [search, ...filterInputs].forEach(input => { input.value = ''; });
  resetSearchPage();
  search.focus();
});

editor.addEventListener('cancel', event => {
  event.preventDefault();
  if (!busy) closeEditor();
});

// Keep wheel and keyboard gestures inside the editor while it is open.
document.addEventListener('wheel', event => {
  if (editor.open && (event.ctrlKey || !editor.contains(event.target))) {
    event.preventDefault();
  }
}, { passive: false });
document.addEventListener('keydown', event => {
  if (editor.open && (event.ctrlKey || event.metaKey) && ['+', '-', '=', '0'].includes(event.key)) {
    event.preventDefault();
  }
});

previousPage.addEventListener('click', () => {
  if (busy || loading || currentPage <= 1) return;
  currentPage -= 1;
  renderCustomers();
});
nextPage.addEventListener('click', () => {
  if (busy || loading || currentPage >= totalPages) return;
  currentPage += 1;
  renderCustomers();
});

matchStartToggle.addEventListener('click', () => {
  matchFromStart = !matchFromStart;
  matchStartToggle.setAttribute('aria-pressed', String(matchFromStart));
  resetSearchPage();
});
