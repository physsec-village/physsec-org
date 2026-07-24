(() => {
    "use strict";

    const dataEl = document.getElementById("psv-catalog");
    if (!dataEl) return;
    const CATALOG = JSON.parse(dataEl.textContent);
    const CART_KEY = "psv-cart";
    const NO_VARIANT = "_";

    // ---- cart state (localStorage, keyed "productId||variantCode") ----

    function readCart() {
        try {
            const stored = JSON.parse(window.localStorage.getItem(CART_KEY));
            if (!stored || typeof stored !== "object") return {};
            const cleaned = {};
            for (const [key, qty] of Object.entries(stored)) {
                const id = key.split("||")[0];
                if (CATALOG[id] && Number.isInteger(qty) && qty > 0) {
                    cleaned[key] = qty;
                }
            }
            return cleaned;
        } catch {
            return {};
        }
    }

    let cart = readCart();

    function saveCart() {
        window.localStorage.setItem(CART_KEY, JSON.stringify(cart));
    }

    const money = (n) => "$" + n.toFixed(2);

    // Variant picked on the product detail page (id -> code); adds elsewhere
    // use the first variant, matching the design behavior.
    const selectedVariant = {};

    function defaultCode(id) {
        const product = CATALOG[id];
        if (!product || !product.variants.length) return NO_VARIANT;
        return selectedVariant[id] || product.variants[0].code;
    }

    function cartEntries() {
        return Object.entries(cart)
            .map(([key, qty]) => {
                const [id, code] = key.split("||");
                const product = CATALOG[id];
                if (!product) return null;
                const variant = product.variants.find((v) => v.code === code);
                return {
                    key,
                    qty,
                    name: product.name,
                    variantLabel: variant ? variant.label : "",
                    lineTotal: product.price * qty,
                };
            })
            .filter(Boolean);
    }

    function cartSubtotal() {
        return cartEntries().reduce((sum, it) => sum + it.lineTotal, 0);
    }

    function cartCount() {
        return cartEntries().reduce((sum, it) => sum + it.qty, 0);
    }

    function addToCart(id, qty) {
        const key = id + "||" + defaultCode(id);
        cart[key] = (cart[key] || 0) + qty;
        saveCart();
        renderAll();
        openCart();
    }

    function bumpQty(key, delta) {
        cart[key] = (cart[key] || 0) + delta;
        if (cart[key] <= 0) delete cart[key];
        saveCart();
        renderAll();
    }

    // ---- cart drawer ----

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

    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function renderCartItem(item) {
        const row = el("div", "cart-item");

        const thumb = el("div", "cart-item-thumb");
        thumb.appendChild(thumbIcon());

        const info = el("div", "cart-item-info");
        info.appendChild(el("div", "cart-item-name", item.name));
        if (item.variantLabel) {
            info.appendChild(el("div", "cart-item-variant", item.variantLabel));
        }
        const qty = el("div", "cart-item-qty");
        const dec = el("button", "", "–");
        dec.type = "button";
        dec.setAttribute("aria-label", "Decrease quantity of " + item.name);
        dec.addEventListener("click", () => bumpQty(item.key, -1));
        const count = el("span", "", String(item.qty));
        const inc = el("button", "", "+");
        inc.type = "button";
        inc.setAttribute("aria-label", "Increase quantity of " + item.name);
        inc.addEventListener("click", () => bumpQty(item.key, 1));
        qty.append(dec, count, inc);
        info.appendChild(qty);

        const side = el("div", "cart-item-side");
        side.appendChild(el("span", "cart-item-total", money(item.lineTotal)));
        const remove = el("button", "cart-item-remove", "Remove");
        remove.type = "button";
        remove.setAttribute("aria-label", "Remove " + item.name + " from cart");
        remove.addEventListener("click", () => bumpQty(item.key, -Infinity));
        side.appendChild(remove);

        row.append(thumb, info, side);
        return row;
    }

    function renderCart() {
        const itemsBox = document.getElementById("cartItems");
        if (!itemsBox) return;
        const emptyBox = document.getElementById("cartEmpty");
        const foot = document.getElementById("cartFoot");
        const entries = cartEntries();

        itemsBox.replaceChildren(...entries.map(renderCartItem));
        emptyBox.hidden = entries.length > 0;
        foot.hidden = entries.length === 0;

        const subtotal = money(cartSubtotal());
        document.getElementById("cartSubtotal").textContent = subtotal;
        document.getElementById("cartCheckoutTotal").textContent = subtotal;
    }

    function renderBadge() {
        const badge = document.getElementById("cartCount");
        if (!badge) return;
        const count = cartCount();
        badge.textContent = String(count);
        badge.hidden = count === 0;
    }

    if (cartButton) cartButton.addEventListener("click", openCart);
    if (overlay) overlay.addEventListener("click", closeCart);
    const cartClose = document.getElementById("cartClose");
    if (cartClose) cartClose.addEventListener("click", closeCart);
    const cartClear = document.getElementById("cartClear");
    if (cartClear) {
        cartClear.addEventListener("click", () => {
            cart = {};
            saveCart();
            renderAll();
        });
    }
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && drawer && !drawer.hidden) closeCart();
    });

    // ---- add buttons ----

    document.addEventListener("click", (event) => {
        const button = event.target.closest("[data-add]");
        if (!button) return;
        const qtyValue = document.getElementById("qtyValue");
        const qty =
            button.hasAttribute("data-detail") && qtyValue
                ? parseInt(qtyValue.textContent, 10) || 1
                : 1;
        addToCart(button.dataset.id, qty);
    });

    // ---- product detail: qty stepper + variant select ----

    const qtyValue = document.getElementById("qtyValue");
    if (qtyValue) {
        document.getElementById("qtyDec").addEventListener("click", () => {
            qtyValue.textContent = String(
                Math.max(1, (parseInt(qtyValue.textContent, 10) || 1) - 1),
            );
        });
        document.getElementById("qtyInc").addEventListener("click", () => {
            qtyValue.textContent = String(
                (parseInt(qtyValue.textContent, 10) || 1) + 1,
            );
        });
    }

    const variantSelect = document.getElementById("variantSelect");
    if (variantSelect) {
        variantSelect.addEventListener("change", () => {
            const option = variantSelect.selectedOptions[0];
            if (!option) return;
            document.getElementById("specSku").textContent = option.dataset.sku;
            document.getElementById("specUpc").textContent = option.dataset.upc;
            const detailAdd = document.querySelector("[data-add][data-detail]");
            if (detailAdd) {
                selectedVariant[detailAdd.dataset.id] = variantSelect.value;
            }
        });
    }

    // ---- catalog filtering ----

    const grid = document.getElementById("productGrid");
    if (grid) {
        const cells = Array.from(grid.querySelectorAll(".product-cell"));
        const chips = Array.from(
            document.querySelectorAll("#catalogFilters .filter-btn"),
        );
        const search = document.getElementById("storeSearch");
        let activeCat =
            (chips.find((c) => c.classList.contains("active")) || chips[0])
                .dataset.cat;

        function applyFilters() {
            const query = search.value.trim().toLowerCase();
            let visible = 0;
            const searchCounts = { All: 0 };
            for (const chip of chips) searchCounts[chip.dataset.cat] = 0;

            for (const cell of cells) {
                const matchesQuery =
                    !query || cell.dataset.search.includes(query);
                if (matchesQuery) {
                    searchCounts.All += 1;
                    searchCounts[cell.dataset.cat] += 1;
                }
                const show =
                    matchesQuery &&
                    (activeCat === "All" || cell.dataset.cat === activeCat);
                cell.hidden = !show;
                if (show) visible += 1;
            }

            for (const chip of chips) {
                chip.classList.toggle("active", chip.dataset.cat === activeCat);
                chip.querySelector(".filter-count").textContent = String(
                    searchCounts[chip.dataset.cat],
                );
            }

            document.getElementById("resultCount").textContent =
                visible + " products";
            document.getElementById("keysNote").hidden = activeCat !== "KYS";

            const emptyBox = document.getElementById("storeEmpty");
            emptyBox.hidden = visible > 0;
            document.getElementById("emptyQuery").textContent = query;

            const activeChip = chips.find(
                (c) => c.dataset.cat === activeCat,
            );
            document.getElementById("catalogCrumb").textContent =
                activeChip.dataset.label;
            document.getElementById("catalogTitle").textContent =
                activeChip.dataset.label;
            document.getElementById("catalogBlurb").textContent =
                activeChip.dataset.blurb;

            const url = new URL(window.location);
            if (activeCat === "All") url.searchParams.delete("cat");
            else url.searchParams.set("cat", activeCat);
            window.history.replaceState(null, "", url);
        }

        for (const chip of chips) {
            chip.addEventListener("click", () => {
                activeCat = chip.dataset.cat;
                applyFilters();
            });
        }
        search.addEventListener("input", applyFilters);
    }

    // ---- checkout ----

    const checkoutForm = document.getElementById("checkoutForm");

    function renderSummary() {
        if (!checkoutForm) return;
        const itemsBox = document.getElementById("summaryItems");
        const entries = cartEntries();

        itemsBox.replaceChildren(
            ...entries.map((item) => {
                const row = el("div", "summary-item");
                const thumb = el("div", "summary-item-thumb");
                thumb.appendChild(thumbIcon());
                const info = el("div", "summary-item-info");
                info.appendChild(el("div", "summary-item-name", item.name));
                if (item.variantLabel) {
                    info.appendChild(
                        el("div", "summary-item-variant", item.variantLabel),
                    );
                }
                info.appendChild(
                    el("div", "summary-item-qty", "Qty " + item.qty),
                );
                const total = el(
                    "span",
                    "summary-item-total",
                    money(item.lineTotal),
                );
                row.append(thumb, info, total);
                return row;
            }),
        );

        const hasItems = entries.length > 0;
        document.getElementById("summaryTotals").hidden = !hasItems;
        document.getElementById("placeOrder").hidden = !hasItems;
        document.getElementById("summaryEmpty").hidden = hasItems;

        const subtotal = cartSubtotal();
        const freeThreshold = Number(checkoutForm.dataset.freeShipping);
        const flat = Number(checkoutForm.dataset.flatShipping);
        const shipping =
            subtotal >= freeThreshold || subtotal === 0 ? 0 : flat;
        document.getElementById("summarySubtotal").textContent =
            money(subtotal);
        document.getElementById("summaryShipping").textContent =
            shipping === 0 ? "Free" : money(shipping);
        document.getElementById("summaryTotal").textContent = money(
            subtotal + shipping,
        );
    }

    if (checkoutForm) {
        checkoutForm.addEventListener("submit", (event) => {
            event.preventDefault();
            if (cartEntries().length === 0) return;
            const orderNum =
                "PSV-" + Math.floor(100000 + Math.random() * 900000);
            cart = {};
            saveCart();
            window.location.href =
                "/store/confirmed?order=" + encodeURIComponent(orderNum);
        });
    }

    function renderAll() {
        renderBadge();
        renderCart();
        renderSummary();
    }

    renderAll();
})();
