(() => {
    "use strict";

    const dataEl = document.getElementById("psv-catalog");
    if (!dataEl) return;
    const CATALOG = JSON.parse(dataEl.textContent);
    const CART_KEY = "psv-cart-v2-variants";
    const CHECKOUT_KEY = "psv-checkout-v2-id";
    const MAX_QTY = 99;
    function normalizeVariantId(value) {
        const id = Number(value);
        return Number.isSafeInteger(id) && id > 0 ? String(id) : "";
    }

    function normalizeQty(value) {
        const qty = Math.floor(Number(value));
        return Number.isFinite(qty) && qty > 0 ? qty : 0;
    }

    function capQty(variantId, qty) {
        return Math.min(qty, CATALOG[variantId].available_stock, MAX_QTY);
    }

    function readCart() {
        try {
            const stored = JSON.parse(window.localStorage.getItem(CART_KEY));
            const cleaned = {};
            if (!Array.isArray(stored)) return cleaned;
            for (const item of stored) {
                const variantId = normalizeVariantId(item && item.variant_id);
                const qty = normalizeQty(item && item.qty);
                if (CATALOG[variantId] && qty) {
                    cleaned[variantId] = capQty(variantId, (cleaned[variantId] || 0) + qty);
                }
            }
            return cleaned;
        } catch {
            return {};
        }
    }

    let cart = readCart();

    function cartPayload() {
        return Object.entries(cart)
            .filter(([variantId, qty]) => CATALOG[variantId] && qty > 0)
            .map(([variantId, qty]) => ({ variant_id: Number(variantId), qty }));
    }

    function saveCart() {
        window.localStorage.setItem(CART_KEY, JSON.stringify(cartPayload()));
    }

    saveCart();

    function money(cents) {
        const dollars = Math.floor(cents / 100);
        const remainder = cents % 100;
        return remainder === 0
            ? "$" + dollars
            : "$" + dollars + "." + String(remainder).padStart(2, "0");
    }

    function cartEntries() {
        return cartPayload().map(({ variant_id: variantId, qty }) => {
            const item = CATALOG[variantId];
            return {
                variantId,
                qty,
                name: item.variant_name ? item.name + " — " + item.variant_name : item.name,
                image: item.image,
                url: item.url,
                lineTotalCents: item.price_cents * qty,
                stock: item.available_stock,
            };
        });
    }

    function cartSubtotal() {
        return cartEntries().reduce((sum, item) => sum + item.lineTotalCents, 0);
    }

    let toastTimer = 0;
    function toast(message) {
        const node = document.getElementById("storeToast");
        if (!node) return;
        node.textContent = message;
        node.hidden = false;
        window.clearTimeout(toastTimer);
        toastTimer = window.setTimeout(() => {
            node.hidden = true;
        }, 2200);
    }

    function addToCart(variantId, qty) {
        variantId = normalizeVariantId(variantId);
        const item = CATALOG[variantId];
        if (!item || item.available_stock <= 0) return;
        const before = cart[variantId] || 0;
        cart[variantId] = capQty(variantId, before + qty);
        window.sessionStorage.removeItem(CHECKOUT_KEY);
        saveCart();
        renderAll();
        toast(
            cart[variantId] === before
                ? "No more " + item.name + " in stock"
                : "Added " + item.name + " to your cart",
        );
    }

    function bumpQty(variantId, delta) {
        variantId = normalizeVariantId(variantId);
        if (!CATALOG[variantId]) return;
        cart[variantId] = capQty(variantId, (cart[variantId] || 0) + delta);
        if (!Number.isFinite(cart[variantId]) || cart[variantId] <= 0) delete cart[variantId];
        window.sessionStorage.removeItem(CHECKOUT_KEY);
        saveCart();
        renderAll();
    }

    const overlay = document.getElementById("cartOverlay");
    const drawer = document.getElementById("cartDrawer");
    const cartButton = document.getElementById("cartButton");

    function openCart() {
        if (!drawer) return;
        overlay.hidden = false;
        drawer.hidden = false;
        if (cartButton) cartButton.setAttribute("aria-expanded", "true");
        const close = document.getElementById("cartClose");
        if (close) close.focus();
    }

    function closeCart() {
        if (!drawer || drawer.hidden) return;
        overlay.hidden = true;
        drawer.hidden = true;
        if (cartButton) {
            cartButton.setAttribute("aria-expanded", "false");
            cartButton.focus();
        }
    }

    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function thumb(item, className) {
        const box = el("div", className);
        if (item.image) {
            const img = el("img");
            img.src = item.image;
            img.alt = "";
            box.appendChild(img);
            return box;
        }
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("viewBox", "0 0 24 24");
        const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        circle.setAttribute("cx", "7.5");
        circle.setAttribute("cy", "15.5");
        circle.setAttribute("r", "5.5");
        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("d", "m21 2-9.6 9.6M15.5 7.5l3 3L22 7l-3-3");
        svg.append(circle, path);
        box.appendChild(svg);
        return box;
    }

    function renderCartItem(item, summary = false) {
        const row = el("div", summary ? "summary-item" : "cart-item");
        const photo = thumb(item, summary ? "summary-item-thumb" : "cart-item-thumb");
        const info = el("div", summary ? "summary-item-info" : "cart-item-info");
        if (summary) {
            info.appendChild(el("div", "summary-item-name", item.name));
            info.appendChild(el("div", "summary-item-qty", "Qty " + item.qty));
            row.append(photo, info, el("span", "summary-item-total", money(item.lineTotalCents)));
            return row;
        }
        const name = el("a", "cart-item-name", item.name);
        name.href = item.url;
        info.appendChild(name);
        const qty = el("div", "cart-item-qty");
        const dec = el("button", "", "–");
        dec.type = "button";
        dec.setAttribute("aria-label", "Decrease quantity of " + item.name);
        dec.addEventListener("click", () => bumpQty(item.variantId, -1));
        const inc = el("button", "", "+");
        inc.type = "button";
        inc.setAttribute("aria-label", "Increase quantity of " + item.name);
        inc.disabled = item.qty >= Math.min(item.stock, MAX_QTY);
        inc.addEventListener("click", () => bumpQty(item.variantId, 1));
        qty.append(dec, el("span", "", String(item.qty)), inc);
        info.appendChild(qty);
        const side = el("div", "cart-item-side");
        side.appendChild(el("span", "cart-item-total", money(item.lineTotalCents)));
        const remove = el("button", "cart-item-remove", "Remove");
        remove.type = "button";
        remove.setAttribute("aria-label", "Remove " + item.name + " from cart");
        remove.addEventListener("click", () => bumpQty(item.variantId, -Infinity));
        side.appendChild(remove);
        row.append(photo, info, side);
        return row;
    }

    function renderAll() {
        const entries = cartEntries();
        const count = entries.reduce((sum, item) => sum + item.qty, 0);
        const subtotal = money(cartSubtotal());
        const badge = document.getElementById("cartCount");
        if (badge) {
            badge.textContent = String(count);
            badge.hidden = count === 0;
        }
        const itemsBox = document.getElementById("cartItems");
        if (itemsBox) itemsBox.replaceChildren(...entries.map((item) => renderCartItem(item)));
        const emptyBox = document.getElementById("cartEmpty");
        if (emptyBox) emptyBox.hidden = entries.length > 0;
        const foot = document.getElementById("cartFoot");
        if (foot) foot.hidden = entries.length === 0;
        for (const id of ["cartSubtotal", "cartCheckoutTotal", "summarySubtotal"]) {
            const node = document.getElementById(id);
            if (node) node.textContent = subtotal;
        }
        const summary = document.getElementById("summaryItems");
        if (summary) summary.replaceChildren(...entries.map((item) => renderCartItem(item, true)));
        const totals = document.getElementById("summaryTotals");
        if (totals) totals.hidden = entries.length === 0;
        const placeOrder = document.getElementById("placeOrder");
        if (placeOrder) placeOrder.hidden = entries.length === 0;
        const summaryEmpty = document.getElementById("summaryEmpty");
        if (summaryEmpty) summaryEmpty.hidden = entries.length > 0;
    }

    if (cartButton) cartButton.addEventListener("click", openCart);
    if (overlay) overlay.addEventListener("click", closeCart);
    const closeButton = document.getElementById("cartClose");
    if (closeButton) closeButton.addEventListener("click", closeCart);
    const clearButton = document.getElementById("cartClear");
    if (clearButton) clearButton.addEventListener("click", () => {
        cart = {};
        window.sessionStorage.removeItem(CHECKOUT_KEY);
        saveCart();
        renderAll();
    });
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") closeCart();
    });

    const qtyValue = document.getElementById("qtyValue");
    const stepper = qtyValue ? qtyValue.closest(".qty-stepper") : null;
    const detailButton = document.querySelector("[data-detail]");
    const variantSelect = document.getElementById("productVariant");
    let qtyMax = stepper ? normalizeQty(stepper.dataset.max) : 0;

    function updateQuantityButtons() {
        if (!qtyValue) return;
        const qty = normalizeQty(qtyValue.textContent);
        document.getElementById("qtyDec").disabled = qty <= 1;
        document.getElementById("qtyInc").disabled = qty >= qtyMax;
    }

    function selectVariant() {
        if (!variantSelect || !detailButton) return;
        const id = normalizeVariantId(variantSelect.value);
        const variant = CATALOG[id];
        if (!variant) return;
        qtyMax = Math.min(variant.available_stock, MAX_QTY);
        stepper.hidden = qtyMax <= 0;
        qtyValue.textContent = String(Math.max(1, Math.min(qtyMax, normalizeQty(qtyValue.textContent))));
        detailButton.dataset.variantId = id;
        detailButton.disabled = qtyMax <= 0;
        detailButton.textContent = qtyMax > 0 ? "Add to cart" : "Sold out";
        detailButton.classList.toggle("btn-primary", qtyMax > 0);
        detailButton.classList.toggle("btn-ghost", qtyMax <= 0);
        document.getElementById("productPrice").textContent = money(variant.price_cents);
        const option = variantSelect.selectedOptions[0];
        const sku = option.dataset.sku || "";
        document.getElementById("productSku").textContent = sku;
        document.getElementById("productSkuRow").hidden = !sku;
        updateQuantityButtons();
    }

    if (variantSelect) {
        variantSelect.addEventListener("change", selectVariant);
        selectVariant();
    }

    document.addEventListener("click", (event) => {
        const button = event.target.closest("[data-add]");
        if (!button || button.disabled) return;
        const qty = button.hasAttribute("data-detail") && qtyValue
            ? normalizeQty(qtyValue.textContent) || 1
            : 1;
        addToCart(button.dataset.variantId, qty);
        if (button.hasAttribute("data-detail")) openCart();
    });

    if (qtyValue) {
        document.getElementById("qtyDec").addEventListener("click", () => {
            qtyValue.textContent = String(Math.max(1, normalizeQty(qtyValue.textContent) - 1));
            updateQuantityButtons();
        });
        document.getElementById("qtyInc").addEventListener("click", () => {
            qtyValue.textContent = String(Math.max(1, Math.min(qtyMax, normalizeQty(qtyValue.textContent) + 1)));
            updateQuantityButtons();
        });
    }

    const checkoutForm = document.getElementById("checkoutForm");
    if (checkoutForm) {
        checkoutForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            if (!cartPayload().length) return;
            const button = document.getElementById("placeOrder");
            const error = document.getElementById("checkoutError");
            button.disabled = true;
            error.hidden = true;
            const checkoutId = window.sessionStorage.getItem(CHECKOUT_KEY);
            const controller = new AbortController();
            const timeout = window.setTimeout(() => controller.abort(), 20000);
            try {
                const response = await fetch("/store/checkout", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    signal: controller.signal,
                    body: JSON.stringify({
                        items: cartPayload(),
                        checkout_id: checkoutId || null,
                    }),
                });
                const result = await response.json().catch(() => ({}));
                if (result.checkout_id) {
                    window.sessionStorage.setItem(CHECKOUT_KEY, result.checkout_id);
                }
                if (!response.ok) {
                    if (response.status === 409 && !result.checkout_id) {
                        window.sessionStorage.removeItem(CHECKOUT_KEY);
                    }
                    throw new Error(
                        result.detail || "Checkout could not be started.",
                    );
                }
                if (typeof result.url !== "string" || !result.url) {
                    throw new Error("Checkout could not be started.");
                }
                window.location.assign(result.url);
            } catch (failure) {
                error.textContent =
                    failure.name === "AbortError"
                        ? "Checkout timed out. Please try again."
                        : failure.message || "Checkout could not be started.";
                error.hidden = false;
                button.disabled = false;
            } finally {
                window.clearTimeout(timeout);
            }
        });
    }

    const confirmation = document.querySelector("[data-order-confirmed='true']");
    if (confirmation) {
        cart = {};
        window.sessionStorage.removeItem(CHECKOUT_KEY);
        saveCart();
    }

    renderAll();
})();
