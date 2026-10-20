let products = [];
let currentProductId = null;
let cart = [];
let chatGoal = "";
let reviewStars = 5;
let lastResult = null;
let selectedCategory = "All";
let searchQuery = "";

try {
  const savedCart = JSON.parse(localStorage.getItem("mf_cart") || "[]");
  if (Array.isArray(savedCart)) cart = savedCart;
} catch (e) { cart = []; }

/* Manual fallback override -- never surfaced in the UI. Toggle with
   ?forceFallback=true in the URL, or Ctrl+Shift+F. Persisted in
   localStorage so it survives page reloads during rehearsal. */
let forceFallback = (() => {
  try {
    const q = new URLSearchParams(window.location.search).get("forceFallback");
    if (q !== null) return q === "true" || q === "1";
    return localStorage.getItem("mf_force_fallback") === "1";
  } catch (e) { return false; }
})();

document.addEventListener("keydown", e => {
  if (e.ctrlKey && e.shiftKey && (e.key === "F" || e.key === "f")) {
    forceFallback = !forceFallback;
    try { localStorage.setItem("mf_force_fallback", forceFallback ? "1" : "0"); } catch (err) {}
    console.log("[MarketFlow] forceFallback =", forceFallback);
  }
});

const ICONS = { search: "🔍", spark: "🤝", note: "📝", handshake: "🤝", check: "✅", cross: "❌", done: "🎉" };

async function j(url, opts) {
  const r = await fetch(url, opts);
  const data = await r.json();
  if (!r.ok) throw new Error(data.detail || data.error || `Request failed (${r.status})`);
  return data;
}

function escapeHtml(s) {
  return (s || "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

function starString(rating) {
  const full = Math.round(rating);
  return "★".repeat(full) + "☆".repeat(5 - full);
}

function initials(name) {
  return (name || "?").trim().split(/\s+/).map(p => p[0]).slice(0, 2).join("").toUpperCase();
}

/* ---------------- Routing ---------------- */

function navigate(view, param) {
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
  document.getElementById("view-" + view).classList.add("active");
  window.scrollTo(0, 0);
  if (view !== "product") stopProductSync();
  if (view === "product" && param) openProduct(param);
  if (view === "cart") renderCart();
  if (view === "checkout") renderCheckout();
  if (view === "orders") renderOrders();
}

/* ---------------- Home ---------------- */


/* ---------------- Real product photos (Wikimedia Commons, free licence), looked up in the browser ----------------
   The review corpora have no photos, so each real product asks Commons for a picture of that exact model, then of
   the product type. Results are cached in localStorage; if nothing matches, the neutral icon stays. */
const PHOTO_KEY = "mf-photos-v2";
let photos = {};
try { photos = JSON.parse(localStorage.getItem(PHOTO_KEY) || "{}"); } catch (e) { photos = {}; }

async function commonsSearch(q, mustHave) {
  const url = "https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrnamespace=6&gsrlimit=15"
    + "&gsrsearch=" + encodeURIComponent(q) + "&prop=imageinfo&iiprop=url|mime&iiurlwidth=800&format=json&origin=*";
  const r = await fetch(url);
  const pages = Object.values(((await r.json()).query || {}).pages || {}).sort((a, b) => a.index - b.index);
  for (const pg of pages) {
    const info = (pg.imageinfo || [])[0];
    const title = (pg.title || "").toLowerCase();
    if (!info || !/^image\/(jpeg|png)$/.test(info.mime)) continue;
    if (/logo|icon|diagram|screenshot|map|flag|svg|box art|\.gif/.test(title)) continue;
    if (mustHave.every(w => title.includes(w))) return info.thumburl || info.url;
  }
  return "";
}

async function findPhoto(p) {
  const brand = (p.brand || "").toLowerCase();
  const model = (p.photo_query || "").toLowerCase().split(/\s+/).filter(w => w && w !== brand);
  const specific = model.filter(w => /\d/.test(w));                 // model numbers like g3, 6600, wrt54g
  try {
    let u = await commonsSearch(p.photo_query, [brand, ...specific]);
    if (!u && specific.length === 0) u = await commonsSearch(p.photo_query, [brand]);
    if (!u) u = await commonsSearch(p.noun, [(p.noun || "").toLowerCase().split(" ")[0]]);   // generic photo of the product type
    return u;
  } catch (e) { return null; }                                       // offline: try again next visit
}

function applyPhotos() {
  document.querySelectorAll("img[data-pid]").forEach(img => {
    const u = photos[img.dataset.pid];
    if (u && img.getAttribute("src") !== u) { img.setAttribute("src", u); img.style.objectFit = "cover"; }
  });
  const main = document.getElementById("pd-main-img");
  if (main && main.dataset.pid && photos[main.dataset.pid]) {
    let c = document.getElementById("photo-credit");
    if (!c) { c = document.createElement("div"); c.id = "photo-credit"; c.style.cssText = "font-size:11px;color:#94a3b8;margin-top:6px";
      main.insertAdjacentElement("afterend", c); }
    c.textContent = "Photo: Wikimedia Commons (free licence), may show a similar model.";
  }
}

async function loadPhotos(list) {
  let changed = false;
  for (const p of list.filter(x => x.id.startsWith("real-") && x.photo_query && !(x.id in photos))) {
    const u = await findPhoto(p);
    if (u === null) continue;
    photos[p.id] = u; changed = true; applyPhotos();
  }
  if (changed) { try { localStorage.setItem(PHOTO_KEY, JSON.stringify(photos)); } catch (e) {} }
}

let _photoTimer = null;
new MutationObserver(() => { clearTimeout(_photoTimer); _photoTimer = setTimeout(applyPhotos, 30); })
  .observe(document.documentElement, { childList: true, subtree: true });

async function loadHome() {
  products = await j("/api/products");
  renderProducts();
  updateCartBadge();
}

function renderProducts() {
  const grid = document.getElementById("product-grid");
  const categoryNames = [...new Set(products.map(p => p.category || p.noun || p.brand || "Other"))].sort();
  document.getElementById("category-list").innerHTML = ["All", ...categoryNames].map(category => `
    <button class="category-chip ${selectedCategory === category ? "active" : ""}" data-category="${escapeHtml(category)}">${escapeHtml(category)}</button>
  `).join("");
  document.querySelectorAll(".category-chip").forEach(button => {
    button.addEventListener("click", () => setCategory(button.dataset.category));
  });

  let visible = products.filter(p => {
    const category = p.category || p.noun || p.brand || "Other";
    const matchesCategory = selectedCategory === "All" || category === selectedCategory;
    const matchesQuery = `${p.name} ${p.brand} ${category} ${p.description}`.toLowerCase().includes(searchQuery);
    return matchesCategory && matchesQuery;
  });
  const sort = document.getElementById("sort-products").value;
  if (sort === "price-low") visible.sort((a, b) => a.list_price - b.list_price);
  if (sort === "price-high") visible.sort((a, b) => b.list_price - a.list_price);
  if (sort === "rating") visible.sort((a, b) => b.rating - a.rating);

  document.getElementById("product-count").textContent = `${visible.length} ${visible.length === 1 ? "product" : "products"}`;
  grid.innerHTML = visible.length ? visible.map(p => `
    <div class="p-card" onclick="navigate('product','${p.id}')">
      <img class="thumb" data-pid="${p.id}" src="${escapeHtml(p.image)}" alt="${escapeHtml(p.name)}" />
      <div class="body">
        <div class="brand">${escapeHtml(p.brand)}</div>
        <div class="name">${escapeHtml(p.name)}</div>
        <div class="rating-row"><span class="stars">${starString(p.rating)}</span> ${p.rating} &middot; ${p.review_count} reviews</div>
        <div class="card-actions">
          <div class="price">$${Number(p.list_price).toFixed(2)}</div>
          <button class="card-add" onclick="event.stopPropagation(); addCartItem('${p.id}')">Add to cart</button>
        </div>
      </div>
    </div>
  `).join("") : `<div class="empty-note">No products match your search. Try another keyword or category.</div>`;
  applyPhotos();
}

function setCategory(category) {
  selectedCategory = category;
  renderProducts();
}

function persistCart() {
  try { localStorage.setItem("mf_cart", JSON.stringify(cart)); } catch (e) {}
  updateCartBadge();
}

function addCartItem(productId) {
  const product = products.find(p => p.id === productId);
  if (!product) return;
  const item = cart.find(entry => entry.product_id === productId);
  if (item) item.qty += 1;
  else cart.push({product_id: productId, qty: 1, budget: product.list_price, goal: "Get me the best possible deal within my budget."});
  persistCart();
}

/* ---------------- Product detail ---------------- */

async function openProduct(id) {
  currentProductId = id;
  chatGoal = "";
  const p = await j(`/api/products/${id}`);
  if (p.error) return;

  document.getElementById("pd-crumb-name").textContent = p.name;
  document.getElementById("pd-brand").textContent = p.brand;
  document.getElementById("pd-name").textContent = p.name;
  document.getElementById("pd-stars").textContent = starString(p.rating);
  document.getElementById("pd-rating-text").textContent = `${p.rating} out of 5 (${p.review_count} reviews)`;
  document.getElementById("pd-price").textContent = `$${p.list_price}`;
  document.getElementById("pd-desc").textContent = p.description;
  document.getElementById("pd-main-img").dataset.pid = p.id;
  document.getElementById("pd-main-img").src = p.image;
  { let c = document.getElementById("photo-credit"); if (!c) { c = document.createElement("div"); c.id = "photo-credit"; c.style.cssText = "font-size:11px;color:#94a3b8;margin-top:6px"; document.getElementById("pd-main-img").insertAdjacentElement("afterend", c); } c.textContent = p.photo_credit || ""; }
  document.getElementById("pd-thumbs").innerHTML = p.gallery.map((g, i) => `
    <img data-pid="${p.id}" src="${g}" class="${i === 0 ? "active" : ""}" onclick="setMainImg(this, '${g}')" />
  `).join("");
  document.getElementById("chat-assistant-name").textContent = p.assistant_name;
  // real-catalog products carry a budget that fits their price; the original three keep 50
  document.getElementById("chat-budget").value = p.suggested_budget || 50;

  document.getElementById("chat-body").innerHTML = `
    <div class="chat-bubble assistant">Hi! I'm the ${escapeHtml(p.assistant_name)}. Set your budget below, then tell me what you're looking for and I'll negotiate and place the order for you.</div>
  `;

  renderReviews(p);
  resetReviewForm();
  startProductSync(id, p);
}

/* Keep the product page in step with whatever is happening to it elsewhere (for example a Kraken attack
   planting a review or placing an order): poll the real API, render only when something changed. */
let _syncTimer = null, _syncSig = "", _policyMax = null;

function stopProductSync() { if (_syncTimer) clearInterval(_syncTimer); _syncTimer = null; }

function startProductSync(id, p) {
  stopProductSync();
  _syncSig = `${p.review_count}:${(p.reviews[0] || {}).id}`;
  _syncTimer = setInterval(async () => {
    if (document.hidden || currentProductId !== id) return;
    try {
      const [cur, orders] = await Promise.all([j(`/api/products/${id}`), j("/api/orders")]);
      if (_policyMax === null) _policyMax = (await j("/api/policy")).max_discount_pct;
      if (cur.error) return;
      const sig = `${cur.review_count}:${(cur.reviews[0] || {}).id}`;
      if (sig !== _syncSig) {
        _syncSig = sig;
        document.getElementById("pd-stars").textContent = starString(cur.rating);
        document.getElementById("pd-rating-text").textContent = `${cur.rating} out of 5 (${cur.review_count} reviews)`;
        renderReviews(cur);
      }
      const mine = orders.filter(o => o.product_id === id);
      const box = document.getElementById("latest-order");
      if (!mine.length) { box.style.display = "none"; return; }
      const o = mine[mine.length - 1];
      const over = Number(o.discount_pct) > _policyMax;
      box.style.display = "block";
      box.className = "latest-order" + (over ? " violation" : "");
      box.textContent = `Latest order #${o.order_id}: $${o.final_price} (${o.discount_pct}% off $${cur.list_price})` +
        (over ? ` -- above the ${_policyMax}% policy limit` : "");
    } catch (e) { /* server restarting: try again next tick */ }
  }, 4000);
}

function setMainImg(el, src) {
  document.getElementById("pd-main-img").src = el.getAttribute("src") || src;
  document.querySelectorAll(".gallery .thumbs img").forEach(i => i.classList.remove("active"));
  el.classList.add("active");
}

function renderReviews(p) {
  document.getElementById("reviews-agg").textContent = `${starString(p.rating)} ${p.rating} out of 5 -- ${p.review_count} reviews`;
  document.getElementById("reviews-list").innerHTML = p.reviews.map(r => `
    <div class="review-card">
      <div class="avatar" style="background:${r.avatar_color}">${initials(r.author)}</div>
      <div>
        <div class="review-meta">
          <span class="name">${escapeHtml(r.author)}</span>
          ${r.verified ? '<span class="verified-badge">Verified Purchase</span>' : ""}
        </div>
        <div class="review-meta">
          <span class="stars">${starString(r.rating)}</span>
          <span class="review-date">${r.date_label}</span>
        </div>
        <div class="review-text">${escapeHtml(r.text)}</div>
      </div>
    </div>
  `).join("");
}

function resetReviewForm() {
  reviewStars = 5;
  document.getElementById("review-author").value = "You";
  document.getElementById("review-text").value = "";
  renderStarPicker();
}

function renderStarPicker() {
  const el = document.getElementById("review-star-picker");
  el.innerHTML = [1,2,3,4,5].map(n => `<span class="${n <= reviewStars ? "on" : ""}" onclick="setReviewStars(${n})">★</span>`).join("");
}
function setReviewStars(n) { reviewStars = n; renderStarPicker(); }

async function submitReview() {
  const author = document.getElementById("review-author").value.trim() || "Anonymous";
  const text = document.getElementById("review-text").value.trim();
  if (!text) return;
  await j(`/api/products/${currentProductId}/reviews`, {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({author, rating: reviewStars, text})
  });
  const p = await j(`/api/products/${currentProductId}`);
  renderReviews(p);
  resetReviewForm();
}

/* ---------------- Chat widget ---------------- */

function addChatBubble(text, cls) {
  const body = document.getElementById("chat-body");
  const div = document.createElement("div");
  div.className = "chat-bubble " + cls;
  div.textContent = text;
  body.appendChild(div);
  body.scrollTop = body.scrollHeight;
}

async function sendChatMessage() {
  const input = document.getElementById("chat-input");
  const text = input.value.trim();
  if (!text) return;
  const history = Array.from(document.querySelectorAll("#chat-body .chat-bubble")).slice(-6)
    .map(b => ({role: b.classList.contains("user") ? "user" : "assistant", text: b.textContent}));
  addChatBubble(text, "user");
  input.value = "";
  input.disabled = true;

  const budget = parseFloat(document.getElementById("chat-budget").value) || 50;
  let chat = {intent: "question", reply: "Sorry, I couldn't process that. Please try again."};
  try {
    chat = await j("/api/chat", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({product_id: currentProductId, message: text, budget, history, force_fallback: forceFallback})
    });
  } catch (e) {
    console.error("[MarketFlow] chat request failed:", e);
  }
  if (!chat.intent || !chat.reply) chat = {intent: "question", reply: "Sorry, I couldn't process that. Please try again."};
  addChatBubble(chat.reply, "assistant");

  // Only a purchase / negotiation request starts the autonomous run.
  // Questions and small talk just get an answer.
  if (chat.intent === "purchase") {
    chatGoal = text;
    const notes = document.getElementById("pd-gift-note").value;
    const item = cart.find(entry => entry.product_id === currentProductId);
    if (item) Object.assign(item, {goal: text, budget});
    else cart.push({product_id: currentProductId, qty: 1, goal: text, budget});
    updateCartBadge();
    persistCart();
    await runAutonomousPipeline(currentProductId, budget, text, notes, true);
  }

  input.disabled = false;
  input.focus();
}

document.addEventListener("keypress", e => {
  if (e.target.id === "chat-input" && e.key === "Enter") sendChatMessage();
});

/* ---------------- Cart / Checkout ---------------- */

function addToCart() {
  const budget = parseFloat(document.getElementById("chat-budget").value) || 50;
  const item = cart.find(entry => entry.product_id === currentProductId);
  if (item) Object.assign(item, {goal: chatGoal, budget});
  else cart.push({product_id: currentProductId, qty: 1, goal: chatGoal, budget});
  persistCart();
}

async function buyNow() {
  const budget = parseFloat(document.getElementById("chat-budget").value) || 50;
  const notes = document.getElementById("pd-gift-note").value;
  const goal = chatGoal && chatGoal.trim()
    ? chatGoal
    : "Get me the best possible deal within my budget.";
  const item = cart.find(entry => entry.product_id === currentProductId);
  if (item) Object.assign(item, {goal, budget});
  else cart.push({product_id: currentProductId, qty: 1, goal, budget});
  persistCart();
  await runAutonomousPipeline(currentProductId, budget, goal, notes, true);
}

function updateCartBadge() {
  document.getElementById("cart-count").textContent = String(cart.reduce((sum, item) => sum + item.qty, 0));
}

function renderCart() {
  const box = document.getElementById("cart-box");
  if (!cart.length) {
    box.innerHTML = `<div class="empty-note">Your cart is empty. <a onclick="navigate('home')" style="color:var(--accent); font-weight:600;">Continue shopping →</a></div>`;
    return;
  }
  const items = cart.map(item => ({item, product: products.find(p => p.id === item.product_id)})).filter(row => row.product);
  if (!items.length) {
    box.innerHTML = `<div class="empty-note">Your saved cart items are no longer available. <a onclick="navigate('home')" style="color:var(--accent);font-weight:600;">Continue shopping</a></div>`;
    return;
  }
  const subtotal = items.reduce((sum, row) => sum + row.product.list_price * row.item.qty, 0);
  box.innerHTML = `${items.map(({item, product}) => `
    <div class="cart-row">
      <img data-pid="${product.id}" src="${escapeHtml(product.image)}" alt="${escapeHtml(product.name)}" />
      <div>
        <div class="name">${escapeHtml(product.name)}</div>
        <div style="color:var(--muted);font-size:12.5px;">$${Number(product.list_price).toFixed(2)} each</div>
      </div>
      <div class="price">$${(product.list_price * item.qty).toFixed(2)}</div>
      <div class="quantity-control">
        <button class="btn btn-sm btn-outline" onclick="updateCartQty('${product.id}', -1)" aria-label="Decrease quantity">−</button>
        <span>${item.qty}</span>
        <button class="btn btn-sm btn-outline" onclick="updateCartQty('${product.id}', 1)" aria-label="Increase quantity">+</button>
      </div>
    </div>
  `).join("")}
  <div class="totals-line total"><span>Subtotal</span><span>$${subtotal.toFixed(2)}</span></div>
  <button class="btn btn-primary" style="margin-top:16px;" onclick="navigate('checkout')">Proceed to Checkout</button>`;
  applyPhotos();
}

function renderCheckout() {
  const box = document.getElementById("checkout-summary");
  const items = cart.map(item => ({item, product: products.find(p => p.id === item.product_id)})).filter(row => row.product);
  if (!items.length) { box.innerHTML = `<div class="empty-note">Your cart is empty.</div>`; document.getElementById("place-order-btn").disabled = true; return; }
  const subtotal = items.reduce((sum, row) => sum + row.product.list_price * row.item.qty, 0);
  box.innerHTML = `${items.map(({item, product}) => `
    <div class="summary-row"><span>${escapeHtml(product.name)} × ${item.qty}</span><span style="margin-left:auto;font-weight:700;">$${(product.list_price * item.qty).toFixed(2)}</span></div>
  `).join("")}
  <div class="totals-line total"><span>Subtotal</span><span>$${subtotal.toFixed(2)}</span></div>
  <div class="totals-line" style="color:var(--muted);"><span>Payment</span><span>Demo checkout · no charge</span></div>`;
  document.getElementById("place-order-btn").disabled = false;
  document.getElementById("place-order-btn").textContent = "Place Order";
}

async function placeOrder() {
  if (!cart.length) return;
  const customerName = document.getElementById("customer-name").value.trim();
  const customerEmail = document.getElementById("customer-email").value.trim();
  const customerAddress = document.getElementById("customer-address").value.trim();
  if (!customerName || !customerEmail || !customerAddress) {
    alert("Please enter your name, email, and delivery address.");
    return;
  }
  const notes = document.getElementById("gift-note").value;
  const button = document.getElementById("place-order-btn");
  button.disabled = true;
  button.textContent = "Placing order…";
  const activity = [];
  const results = [];
  try {
    const checkoutItems = cart.map(item => ({...item}));
    for (const item of checkoutItems) {
      const product = products.find(p => p.id === item.product_id);
      if (!product) continue;
      for (let count = 0; count < item.qty; count += 1) {
        const result = await j("/api/run", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            product_id: product.id, budget: Number(item.budget),
            goal: item.goal || "Get me the best possible deal within my budget.",
            notes, force_fallback: forceFallback,
            customer_name: customerName, customer_email: customerEmail, customer_address: customerAddress
          })
        });
        result.cartProductId = product.id;
        results.push(result);
        if (result.order) {
          const cartItem = cart.find(entry => entry.product_id === product.id);
          if (cartItem) {
            cartItem.qty -= 1;
            if (cartItem.qty <= 0) cart = cart.filter(entry => entry.product_id !== product.id);
            persistCart();
          }
        }
        activity.push(...(result.activity_feed || []));
      }
    }
    streamActivity(activity);
    renderCheckoutConfirmation(results);
  } catch (error) {
    console.error("[MarketFlow] checkout failed:", error);
    alert(`Checkout could not be completed: ${error.message}`);
    button.disabled = false;
    button.textContent = "Place Order";
  }
}

function updateCartQty(productId, delta) {
  const item = cart.find(entry => entry.product_id === productId);
  if (!item) return;
  item.qty += delta;
  if (item.qty <= 0) cart = cart.filter(entry => entry.product_id !== productId);
  persistCart();
  renderCart();
}

function renderOrders() {
  const list = document.getElementById("customer-order-list");
  list.innerHTML = `<div class="empty-note">Loading orders…</div>`;
  j("/api/orders").then(orders => {
    if (!orders.length) {
      list.innerHTML = `<div class="empty-note">No orders yet. <a href="#" onclick="navigate('home');return false;" style="color:var(--accent);">Start shopping</a></div>`;
      return;
    }
    list.innerHTML = [...orders].reverse().map(order => {
      const product = products.find(p => p.id === order.product_id);
      return `<article class="customer-order">
        <div><strong>Order #${escapeHtml(String(order.order_id))}</strong><div style="font-size:13px;margin-top:5px">${escapeHtml(product ? product.name : "Product unavailable")}</div>
        <div style="font-size:12px;color:var(--muted);margin-top:3px">${escapeHtml(order.customer_name || "Demo customer")} · $${Number(order.final_price).toFixed(2)}</div></div>
        <span class="order-status">${escapeHtml(order.status || "Processing")}</span>
      </article>`;
    }).join("");
  }).catch(error => { list.innerHTML = `<div class="empty-note">Orders could not be loaded: ${escapeHtml(error.message)}</div>`; });
}

function renderCheckoutConfirmation(results) {
  const orders = results.filter(result => result.order);
  const failures = results.length - orders.length;
  const box = document.getElementById("receipt-box");
  box.innerHTML = `
    <div class="check">${failures ? "🧾" : "✓"}</div>
    <h1>${orders.length ? "Order placed" : "No order placed"}</h1>
    <div class="order-no">${orders.length} item${orders.length === 1 ? "" : "s"} ordered${failures ? ` · ${failures} item${failures === 1 ? "" : "s"} need another try` : ""}</div>
    ${orders.map(result => `<div class="item-row">
      <img data-pid="${result.product.id}" src="${escapeHtml(result.product.image)}" alt="${escapeHtml(result.product.name)}" />
      <div style="flex:1"><div style="font-weight:700;font-size:13.5px">${escapeHtml(result.product.name)}</div><div style="color:var(--muted);font-size:12px">Order #${escapeHtml(String(result.order.order_id))} · Processing</div></div>
      <strong>$${Number(result.order.final_price).toFixed(2)}</strong>
    </div>`).join("")}
    ${failures ? `<p style="font-size:13px;color:var(--muted)">One or more offers could not be approved. Those items remain in your cart.</p>` : ""}
    <button class="btn btn-primary" style="margin-top:20px" onclick="navigate('orders')">View orders</button>
    <button class="btn btn-outline" style="margin:20px 0 0 8px" onclick="navigate('home')">Continue shopping</button>`;
  applyPhotos();
  navigate("confirmation");
}

/* The single entry point for a full, uninterrupted agent run: Buyer -> Negotiator
   -> Buyer (evaluate) -> Orchestrator -> Checkout, all fired from one click, with
   the activity panel streaming automatically end to end -- no further clicks. */
async function runAutonomousPipeline(product_id, budget, goal, notes, inline = false) {
  setActivityOpen(true);
  document.getElementById("activity-list").innerHTML =
    `<div class="empty-note">Starting your assistant...</div>`;

  try {
    const result = await j("/api/run", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({product_id, budget, goal, notes, force_fallback: forceFallback})
    });
    lastResult = result;
    const totalDelay = streamActivity(result.activity_feed || []);
    setTimeout(() => renderConfirmation(result, inline), totalDelay + 300);
  } catch (e) {
    console.error("[MarketFlow] run failed unexpectedly:", e);
    document.getElementById("activity-list").innerHTML =
      `<div class="empty-note">Your assistant is still working on this -- check back in a moment.</div>`;
  }
}

function renderInlineResult(result) {
  const p = result.product;
  const body = document.getElementById("chat-body");
  const div = document.createElement("div");
  if (!result.order) {
    div.className = "chat-bubble assistant result fail";
    const why = result.blocked
      ? "The request was blocked by Kraken before an order could be placed."
      : "The seller's offer was not approved within your budget. Adjust your budget or message and try again.";
    div.innerHTML = `<div class="r-title">😕 Order not placed</div><div>${escapeHtml(why)}</div>`;
  } else {
    const o = result.order;
    const off = (p.list_price - o.final_price).toFixed(2);
    div.className = "chat-bubble assistant result ok";
    div.innerHTML = `<div class="r-title">🎉 Order placed -- #${escapeHtml(String(o.order_id))}</div>
      <div class="r-line"><span>${escapeHtml(p.name)}</span><span>$${p.list_price}</span></div>
      <div class="r-line"><span>Discount</span><span>-${o.discount_pct}% (-$${off})</span></div>
      <div class="r-line" style="font-weight:700;"><span>Total</span><span>$${o.final_price}</span></div>`;
  }
  body.appendChild(div);
  body.scrollTop = body.scrollHeight;
}

function renderConfirmation(result, inline = false) {
  if (inline) {
    renderInlineResult(result);
    cart = [];
    persistCart();
    return;  // stay on the product page: chat + activity + result all visible together
  }
  const box = document.getElementById("receipt-box");
  const p = result.product;

  if (!result.order) {
    box.innerHTML = `
      <div class="check">😕</div>
      <h1>We couldn't complete this order</h1>
      <div class="order-no">Your assistant's offer didn't get approved within your budget. Try adjusting your budget or message and try again.</div>
      <button class="btn btn-primary" onclick="navigate('home')">Continue shopping</button>
    `;
  } else {
    const order = result.order;
    const discountAmt = (p.list_price - order.final_price).toFixed(2);
    box.innerHTML = `
      <div class="check">🎉</div>
      <h1>Order placed!</h1>
      <div class="order-no">Order #${order.order_id}</div>
      <div class="item-row">
        <img data-pid="${p.id}" src="${p.image}" />
        <div>
          <div style="font-weight:700; font-size:13.5px;">${escapeHtml(p.name)}</div>
          <div style="color:var(--muted); font-size:12px;">Qty: 1</div>
        </div>
      </div>
      <div class="totals-line"><span>Subtotal</span><span>$${p.list_price}</span></div>
      <div class="totals-line discount"><span>Discount</span><span>-${order.discount_pct}% (-$${discountAmt})</span></div>
      <div class="totals-line total"><span>Total</span><span>$${order.final_price}</span></div>
      <button class="btn btn-primary" style="margin-top:20px;" onclick="navigate('home')">Continue shopping</button>
    `;
  }

  cart = [];
  persistCart();
  navigate("confirmation");
}

/* ---------------- Assistant activity panel ---------------- */

function setActivityOpen(open) {
  document.getElementById("activity-panel").classList.toggle("open", open);
  document.body.classList.toggle("activity-open", open);
}

function toggleActivity() {
  setActivityOpen(!document.getElementById("activity-panel").classList.contains("open"));
}

function streamActivity(feed) {
  const panel = document.getElementById("activity-panel");
  const list = document.getElementById("activity-list");
  setActivityOpen(true);
  list.innerHTML = "";
  let elapsed = 0;
  feed.forEach((step) => {
    elapsed += 800 + Math.random() * 700; // randomized 800-1500ms between steps
    setTimeout(() => {
      const div = document.createElement("div");
      div.className = "activity-item";
      div.innerHTML = `<span class="ic">${ICONS[step.icon] || "•"}</span><span>${escapeHtml(step.text)}</span>`;
      list.appendChild(div);
      list.scrollTop = list.scrollHeight;
    }, elapsed);
  });
  return elapsed;
}

// kept for compatibility with any old callers
function openActivityAnimated(feed) { return streamActivity(feed); }

/* ---------------- Reset demo environment ---------------- */

async function resetDemoEnvironment() {
  if (!currentProductId) return;
  await j(`/api/products/${currentProductId}/reset`, {method: "POST"});
  const p = await j(`/api/products/${currentProductId}`);
  renderReviews(p);
  resetReviewForm();
  cart = [];
  lastResult = null;
  persistCart();
  document.getElementById("activity-list").innerHTML =
    `<div class="empty-note">No activity yet -- browse a product and check out to see your assistant at work.</div>`;
  setActivityOpen(false);
  document.getElementById("pd-gift-note").value = "";
  document.getElementById("chat-input").value = "";
  chatGoal = "";
  document.getElementById("chat-body").innerHTML = `
    <div class="chat-bubble assistant">Hi! I'm the ${escapeHtml(p.assistant_name)}. Set your budget below, then tell me what you're looking for and I'll negotiate and place the order for you.</div>
  `;
}

/* ---------------- init ---------------- */

document.getElementById("product-search").addEventListener("input", event => {
  searchQuery = event.target.value.trim().toLowerCase();
  renderProducts();
});
document.getElementById("sort-products").addEventListener("change", renderProducts);
loadHome().catch(error => {
  console.error("[MarketFlow] catalog failed to load:", error);
  document.getElementById("product-grid").innerHTML =
    `<div class="empty-note">Products could not be loaded: ${escapeHtml(error.message)}</div>`;
});
