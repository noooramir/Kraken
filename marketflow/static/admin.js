let products = [];
let orders = [];
let editingId = null;
const statuses = ["Processing", "Shipped", "Delivered", "Cancelled"];

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
}

async function request(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || data.error || `Request failed (${response.status})`);
  return data;
}

function notify(message, isError = true) {
  const element = document.getElementById("message");
  element.textContent = message;
  element.style.color = isError ? "var(--danger)" : "#047857";
}

async function loadDashboard() {
  try {
    [products, orders] = await Promise.all([request("/api/admin/products"), request("/api/orders")]);
    renderProducts();
    renderOrders();
    document.getElementById("stat-products").textContent = products.filter(product => product.active !== false).length;
    document.getElementById("stat-orders").textContent = orders.length;
    document.getElementById("stat-sales").textContent = `$${orders.reduce((sum, order) => sum + Number(order.final_price || 0), 0).toFixed(2)}`;
  } catch (error) {
    notify(`Dashboard could not be loaded: ${error.message}`);
  }
}

function renderProducts() {
  const body = document.getElementById("products-table");
  body.innerHTML = products.length ? products.map(product => `
    <tr>
      <td><img src="${escapeHtml(product.image)}" alt="" /></td>
      <td><strong>${escapeHtml(product.name)}</strong><div class="muted">${escapeHtml(product.brand)}</div></td>
      <td>${escapeHtml(product.category || product.noun || "Other")}</td>
      <td>$${Number(product.list_price).toFixed(2)}</td>
      <td><span class="status ${product.active === false ? "archived" : ""}">${product.active === false ? "Archived" : "Active"}</span></td>
      <td class="actions"><button data-action="edit" data-id="${escapeHtml(product.id)}">Edit</button>
        <button class="${product.active === false ? "" : "danger"}" data-action="archive" data-id="${escapeHtml(product.id)}">${product.active === false ? "Restore" : "Archive"}</button></td>
    </tr>`).join("") : `<tr><td class="empty" colspan="6">No products yet.</td></tr>`;
  body.querySelectorAll("button").forEach(button => button.addEventListener("click", () => {
    const product = products.find(item => item.id === button.dataset.id);
    if (button.dataset.action === "edit") openProductForm(product);
    else archiveProduct(product.id);
  }));
}

function renderOrders() {
  const body = document.getElementById("orders-table");
  body.innerHTML = orders.length ? [...orders].reverse().map(order => {
    const product = products.find(item => item.id === order.product_id);
    const current = statuses.includes(order.status) ? order.status : "Processing";
    return `<tr>
      <td>#${escapeHtml(order.order_id)}</td>
      <td>${escapeHtml(order.customer_name || "Demo customer")}<div class="muted">${escapeHtml(order.customer_email || "")}</div></td>
      <td>${escapeHtml(product ? product.name : order.product_id)}</td>
      <td>$${Number(order.final_price || 0).toFixed(2)}</td>
      <td>${escapeHtml(current)}</td>
      <td><select data-order-id="${escapeHtml(order.order_id)}" aria-label="Update status for order ${escapeHtml(order.order_id)}">
        ${statuses.map(status => `<option ${status === current ? "selected" : ""}>${status}</option>`).join("")}
      </select></td>
    </tr>`;
  }).join("") : `<tr><td class="empty" colspan="6">No demo orders yet.</td></tr>`;
  body.querySelectorAll("select").forEach(select => select.addEventListener("change", () => updateStatus(select)));
}

function openProductForm(product = null) {
  editingId = product ? product.id : null;
  document.getElementById("product-form").reset();
  document.getElementById("product-name").value = product ? product.name : "";
  document.getElementById("product-brand").value = product ? product.brand : "";
  document.getElementById("product-category").value = product ? (product.category || product.noun || "") : "";
  document.getElementById("product-price").value = product ? product.list_price : "";
  document.getElementById("product-image").value = product ? product.image : "";
  document.getElementById("product-description").value = product ? product.description : "";
  document.getElementById("save-product").textContent = editingId ? "Save changes" : "Create product";
  document.getElementById("product-form-wrap").classList.remove("hidden");
  document.getElementById("product-name").focus();
}

async function saveProduct(event) {
  event.preventDefault();
  const data = {
    name: document.getElementById("product-name").value.trim(),
    brand: document.getElementById("product-brand").value.trim(),
    category: document.getElementById("product-category").value.trim(),
    list_price: Number(document.getElementById("product-price").value),
    image: document.getElementById("product-image").value.trim(),
    description: document.getElementById("product-description").value.trim()
  };
  try {
    await request(editingId ? `/api/admin/products/${encodeURIComponent(editingId)}` : "/api/admin/products", {
      method: editingId ? "PUT" : "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify(data)
    });
    document.getElementById("product-form-wrap").classList.add("hidden");
    notify(editingId ? "Product updated." : "Product created.", false);
    await loadDashboard();
  } catch (error) {
    notify(`Product could not be saved: ${error.message}`);
  }
}

async function archiveProduct(productId) {
  try {
    const result = await request(`/api/admin/products/${encodeURIComponent(productId)}`, {method:"DELETE"});
    notify(result.active ? "Product restored to the storefront." : "Product archived from the storefront.", false);
    await loadDashboard();
  } catch (error) {
    notify(`Product could not be updated: ${error.message}`);
  }
}

async function updateStatus(select) {
  try {
    await request(`/api/admin/orders/${encodeURIComponent(select.dataset.orderId)}`, {
      method:"PATCH",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({status:select.value})
    });
    notify("Order status updated.", false);
    await loadDashboard();
  } catch (error) {
    notify(`Order could not be updated: ${error.message}`);
    await loadDashboard();
  }
}

document.getElementById("new-product").addEventListener("click", () => openProductForm());
document.getElementById("cancel-product").addEventListener("click", () => document.getElementById("product-form-wrap").classList.add("hidden"));
document.getElementById("product-form").addEventListener("submit", saveProduct);
loadDashboard();
