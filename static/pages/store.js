(() => {
    "use strict";

    const dataEl = document.getElementById("psv-catalog");
    if (!dataEl) return;
    const CATALOG = JSON.parse(dataEl.textContent);
    const CART_KEY = "psv-cart";
    const CHECKOUT_KEY = "psv-checkout-id";
    const SKU_MAP = {};
    const normalizeSku = (sku) => String(sku || "").trim().toUpperCase();

    for (const [productId, product] of Object.entries(CATALOG)) {
        for (const variant of product.variants) {
            const sku = normalizeSku(variant.sku);
            SKU_MAP[sku] = {
                productId,
                name: product.name,
                variantLabel: variant.label,
                priceCents: variant.price_cents,
                stock: variant.available_stock,
            };
        }
    }

    function normalizeQty(value) {
        const qty = Math.floor(Number(value));
        return Number.isFinite(qty) && qty > 0 ? qty : 0;
    }

    function readCart() {
        try {
            const stored = JSON.parse(window.localStorage.getItem(CART_KEY));
            const cleaned = {};
            if (Array.isArray(stored)) {
                for (const item of stored) {
                    const sku = normalizeSku(item && item.sku);
                    const qty = normalizeQty(item && item.qty);
                    if (SKU_MAP[sku] && qty) {
                        cleaned[sku] = Math.min(
                            (cleaned[sku] || 0) + qty,
                            SKU_MAP[sku].stock,
                        );
                    }
                }
                return cleaned;
            }

            // One-time migration from the design-only productId||variantCode cart.
            if (stored && typeof stored === "object") {
                for (const [key, rawQty] of Object.entries(stored)) {
                    const [productId, code] = key.split("||");
                    const product = CATALOG[productId];
                    const variant = product && product.variants.find(
                        (candidate) => candidate.code === code,
                    );
                    const qty = normalizeQty(rawQty);
                    if (variant && qty) {
                        const sku = normalizeSku(variant.sku);
                        cleaned[sku] = Math.min(
                            (cleaned[sku] || 0) + qty,
                            variant.available_stock,
                        );
                    }
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
            .filter(([sku, qty]) => SKU_MAP[sku] && qty > 0)
            .map(([sku, qty]) => ({ sku, qty }));
    }

    function saveCart() {
        window.localStorage.setItem(CART_KEY, JSON.stringify(cartPayload()));
    }

    saveCart();
    const money = (cents) => "$" + (cents / 100).toFixed(2);

    function cartEntries() {
        return cartPayload().map(({ sku, qty }) => {
            const item = SKU_MAP[sku];
            return {
                sku,
                qty,
                name: item.name,
                variantLabel: item.variantLabel,
                lineTotalCents: item.priceCents * qty,
                stock: item.stock,
            };
        });
    }

    function cartSubtotal() {
        return cartEntries().reduce((sum, item) => sum + item.lineTotalCents, 0);
    }

    function addToCart(sku, qty) {
        sku = normalizeSku(sku);
        const item = SKU_MAP[sku];
        if (!item || item.stock <= 0) return;
        cart[sku] = Math.min((cart[sku] || 0) + qty, item.stock);
        window.sessionStorage.removeItem(CHECKOUT_KEY);
        saveCart();
        renderAll();
        openCart();
    }

    function bumpQty(sku, delta) {
        sku = normalizeSku(sku);
        const item = SKU_MAP[sku];
        if (!item) return;
        cart[sku] = Math.min((cart[sku] || 0) + delta, item.stock);
        if (!Number.isFinite(cart[sku]) || cart[sku] <= 0) delete cart[sku];
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
    }

    function closeCart() {
        if (!drawer) return;
        overlay.hidden = true;
        drawer.hidden = true;
        if (cartButton) cartButton.setAttribute("aria-expanded", "false");
    }

    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function thumbIcon() {
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("viewBox", "0 0 24 24");
        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute(
            "d",
            "M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z",
        );
        svg.appendChild(path);
        return svg;
    }

    function renderCartItem(item, summary = false) {
        const row = el("div", summary ? "summary-item" : "cart-item");
        const thumb = el("div", summary ? "summary-item-thumb" : "cart-item-thumb");
        thumb.appendChild(thumbIcon());
        const info = el("div", summary ? "summary-item-info" : "cart-item-info");
        info.appendChild(el("div", summary ? "summary-item-name" : "cart-item-name", item.name));
        if (item.variantLabel) {
            info.appendChild(el("div", summary ? "summary-item-variant" : "cart-item-variant", item.variantLabel));
        }
        if (summary) {
            info.appendChild(el("div", "summary-item-qty", "Qty " + item.qty));
            row.append(thumb, info, el("span", "summary-item-total", money(item.lineTotalCents)));
            return row;
        }
        const qty = el("div", "cart-item-qty");
        const dec = el("button", "", "–");
        dec.type = "button";
        dec.addEventListener("click", () => bumpQty(item.sku, -1));
        const inc = el("button", "", "+");
        inc.type = "button";
        inc.disabled = item.qty >= item.stock;
        inc.addEventListener("click", () => bumpQty(item.sku, 1));
        qty.append(dec, el("span", "", String(item.qty)), inc);
        info.appendChild(qty);
        const side = el("div", "cart-item-side");
        side.appendChild(el("span", "cart-item-total", money(item.lineTotalCents)));
        const remove = el("button", "cart-item-remove", "Remove");
        remove.type = "button";
        remove.addEventListener("click", () => bumpQty(item.sku, -Infinity));
        side.appendChild(remove);
        row.append(thumb, info, side);
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
        if (event.key === "Escape" && drawer && !drawer.hidden) closeCart();
    });

    document.addEventListener("click", (event) => {
        const button = event.target.closest("[data-add]");
        if (!button || button.disabled) return;
        const qtyNode = document.getElementById("qtyValue");
        const qty = button.hasAttribute("data-detail") && qtyNode
            ? normalizeQty(qtyNode.textContent) || 1
            : 1;
        addToCart(button.dataset.sku, qty);
    });

    const qtyValue = document.getElementById("qtyValue");
    if (qtyValue) {
        document.getElementById("qtyDec").addEventListener("click", () => {
            qtyValue.textContent = String(Math.max(1, normalizeQty(qtyValue.textContent) - 1));
        });
        document.getElementById("qtyInc").addEventListener("click", () => {
            const sku = document.querySelector("[data-add][data-detail]").dataset.sku;
            qtyValue.textContent = String(Math.min(normalizeQty(qtyValue.textContent) + 1, SKU_MAP[sku].stock));
        });
    }

    const variantSelect = document.getElementById("variantSelect");
    if (variantSelect) {
        variantSelect.addEventListener("change", () => {
            const option = variantSelect.selectedOptions[0];
            if (!option) return;
            document.getElementById("specSku").textContent = option.dataset.sku;
            document.getElementById("specUpc").textContent = option.dataset.upc;
            const add = document.querySelector("[data-add][data-detail]");
            add.dataset.sku = option.value;
            add.disabled = Number(option.dataset.stock) <= 0;
            qtyValue.textContent = "1";
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

    const grid = document.getElementById("productGrid");
    if (grid) {
        const cells = Array.from(grid.querySelectorAll(".product-cell"));
        const chips = Array.from(document.querySelectorAll("#catalogFilters .filter-btn"));
        const search = document.getElementById("storeSearch");
        let activeCat = (chips.find((chip) => chip.classList.contains("active")) || chips[0]).dataset.cat;
        function applyFilters() {
            const query = search.value.trim().toLowerCase();
            let visible = 0;
            const counts = { All: 0 };
            for (const chip of chips) counts[chip.dataset.cat] = 0;
            for (const cell of cells) {
                const matches = !query || cell.dataset.search.includes(query);
                if (matches) {
                    counts.All += 1;
                    counts[cell.dataset.cat] += 1;
                }
                const show = matches && (activeCat === "All" || cell.dataset.cat === activeCat);
                cell.hidden = !show;
                if (show) visible += 1;
            }
            for (const chip of chips) {
                chip.classList.toggle("active", chip.dataset.cat === activeCat);
                chip.querySelector(".filter-count").textContent = String(counts[chip.dataset.cat]);
            }
            document.getElementById("resultCount").textContent = visible + " products";
            document.getElementById("keysNote").hidden = activeCat !== "KYS";
            document.getElementById("storeEmpty").hidden = visible > 0;
            document.getElementById("emptyQuery").textContent = query;
            const active = chips.find((chip) => chip.dataset.cat === activeCat);
            document.getElementById("catalogCrumb").textContent = active.dataset.label;
            document.getElementById("catalogTitle").textContent = active.dataset.label;
            document.getElementById("catalogBlurb").textContent = active.dataset.blurb;
        }
        for (const chip of chips) chip.addEventListener("click", () => {
            activeCat = chip.dataset.cat;
            applyFilters();
        });
        search.addEventListener("input", applyFilters);
    }

    renderAll();
})();
