let products = [];
let currentProductId = null;
let cart = null; // {product_id, qty}
let chatGoal = "";
let reviewStars = 5;
let lastResult = null;

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
  return r.json();
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
  if (view === "product" && param) openProduct(param);
  if (view === "cart") renderCart();
  if (view === "checkout") renderCheckout();
}

/* ---------------- Home ---------------- */

async function loadHome() {
  products = await j("/api/products");
  const grid = document.getElementById("product-grid");
  grid.innerHTML = products.map(p => `
    <div class="p-card" onclick="navigate('product','${p.id}')">
      <img class="thumb" src="${p.image}" alt="${escapeHtml(p.name)}" />
      <div class="body">
        <div class="brand">${escapeHtml(p.brand)}</div>
        <div class="name">${escapeHtml(p.name)}</div>
        <div class="rating-row"><span class="stars">${starString(p.rating)}</span> ${p.rating} &middot; ${p.review_count} reviews</div>
        <div class="price">$${p.list_price}</div>
      </div>
    </div>
  `).join("");
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
  document.getElementById("pd-main-img").src = p.image;
  document.getElementById("pd-thumbs").innerHTML = p.gallery.map((g, i) => `
    <img src="${g}" class="${i === 0 ? "active" : ""}" onclick="setMainImg(this, '${g}')" />
  `).join("");
  document.getElementById("chat-assistant-name").textContent = p.assistant_name;
  document.getElementById("chat-budget").value = 50;

  document.getElementById("chat-body").innerHTML = `
    <div class="chat-bubble assistant">Hi! I'm the ${escapeHtml(p.assistant_name)}. Set your budget below, then tell me what you're looking for and I'll negotiate and place the order for you.</div>
  `;

  renderReviews(p);
  resetReviewForm();
}

function setMainImg(el, src) {
  document.getElementById("pd-main-img").src = src;
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
    cart = {product_id: currentProductId, qty: 1, goal: text, budget};
    updateCartBadge();
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
  cart = {product_id: currentProductId, qty: 1, goal: chatGoal, budget};
  updateCartBadge();
}

async function buyNow() {
  const budget = parseFloat(document.getElementById("chat-budget").value) || 50;
  const notes = document.getElementById("pd-gift-note").value;
  const goal = chatGoal && chatGoal.trim()
    ? chatGoal
    : "Get me the best possible deal within my budget.";
  cart = {product_id: currentProductId, qty: 1, goal, budget};
  updateCartBadge();
  await runAutonomousPipeline(cart.product_id, budget, goal, notes, true);
}

function updateCartBadge() {
  document.getElementById("cart-count").textContent = cart ? "1" : "0";
}

function renderCart() {
  const box = document.getElementById("cart-box");
  if (!cart) {
    box.innerHTML = `<div class="empty-note">Your cart is empty. <a onclick="navigate('home')" style="color:var(--accent); font-weight:600;">Continue shopping →</a></div>`;
    return;
  }
  const p = products.find(x => x.id === cart.product_id);
  box.innerHTML = `
    <div class="cart-row">
      <img src="${p.image}" />
      <div>
        <div class="name">${escapeHtml(p.name)}</div>
        <div style="color:var(--muted); font-size:12.5px;">Qty: 1</div>
      </div>
      <div class="price">$${p.list_price}</div>
    </div>
    <div class="totals-line total"><span>Subtotal</span><span>$${p.list_price}</span></div>
    <button class="btn btn-primary" style="margin-top:16px;" onclick="navigate('checkout')">Proceed to Checkout</button>
  `;
}

function renderCheckout() {
  const box = document.getElementById("checkout-summary");
  if (!cart) { box.innerHTML = `<div class="empty-note">Your cart is empty.</div>`; return; }
  const p = products.find(x => x.id === cart.product_id);
  box.innerHTML = `
    <div class="summary-row"><span>${escapeHtml(p.name)}</span><span style="margin-left:auto; font-weight:700;">$${p.list_price}</span></div>
    <div class="totals-line"><span>Subtotal</span><span>$${p.list_price}</span></div>
    <div class="totals-line" style="color:var(--muted);"><span>Your budget</span><span>$${cart.budget}</span></div>
  `;
  document.getElementById("place-order-btn").disabled = false;
  document.getElementById("place-order-btn").textContent = "Place Order";
}

async function placeOrder() {
  if (!cart) return;
  const notes = document.getElementById("gift-note") ? document.getElementById("gift-note").value : "";
  await runAutonomousPipeline(cart.product_id, cart.budget, cart.goal, notes);
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
    cart = null;
    updateCartBadge();
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
        <img src="${p.image}" />
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

  cart = null;
  updateCartBadge();
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
  cart = null;
  lastResult = null;
  updateCartBadge();
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

loadHome();
