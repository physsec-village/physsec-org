(function () {
    const STORAGE_KEY = "psv-cart";

    function readCart() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return { items: [] };
            const data = JSON.parse(raw);
            if (!Array.isArray(data.items)) return { items: [] };
            return data;
        } catch {
            return { items: [] };
        }
    }

    function writeCart(cart) {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(cart));
        updateBadge();
        updateDropdown();
    }

    function formatCents(cents) {
        return "$" + (cents / 100).toFixed(2);
    }

    function getItems() {
        return readCart().items;
    }

    function addItem(slug, name, priceCents, priceDisplay) {
        const cart = readCart();
        const existing = cart.items.find((i) => i.slug === slug);
        if (existing) {
            existing.quantity += 1;
        } else {
            cart.items.push({
                slug: slug,
                name: name,
                price_cents: priceCents,
                price_display: priceDisplay,
                quantity: 1,
            });
        }
        writeCart(cart);
    }

    function removeItem(slug) {
        const cart = readCart();
        cart.items = cart.items.filter((i) => i.slug !== slug);
        writeCart(cart);
    }

    function updateQuantity(slug, quantity) {
        if (quantity < 1) {
            removeItem(slug);
            return;
        }
        const cart = readCart();
        const item = cart.items.find((i) => i.slug === slug);
        if (item) {
            item.quantity = quantity;
            writeCart(cart);
        }
    }

    function clear() {
        writeCart({ items: [] });
    }

    function getCount() {
        return getItems().reduce((sum, i) => sum + i.quantity, 0);
    }

    function getSubtotalCents() {
        return getItems().reduce((sum, i) => sum + i.price_cents * i.quantity, 0);
    }

    function updateBadge() {
        const badge = document.getElementById("cartBadge");
        if (!badge) return;
        const count = getCount();
        if (count > 0) {
            badge.textContent = count > 99 ? "99+" : count;
            badge.style.display = "flex";
        } else {
            badge.style.display = "none";
        }
    }

    function updateDropdown() {
        const container = document.getElementById("cartDropdown");
        if (!container) return;

        const items = getItems();
        if (items.length === 0) {
            container.innerHTML = `
                <div class="cart-dd-empty">Your cart is empty</div>
                <a href="/store" class="cart-dd-browse">Browse store</a>
            `;
            return;
        }

        const itemsHtml = items
            .slice(0, 5)
            .map(
                (i) => `
                <div class="cart-dd-item">
                    <span class="cart-dd-name">${i.name}</span>
                    <span class="cart-dd-qty">${i.quantity} &times; ${i.price_display}</span>
                </div>
            `,
            )
            .join("");

        const moreCount = items.length - 5;
        const moreHtml =
            moreCount > 0
                ? `<div class="cart-dd-more">+${moreCount} more item${moreCount > 1 ? "s" : ""}</div>`
                : "";

        container.innerHTML = `
            <div class="cart-dd-header">Cart (${getCount()})</div>
            <div class="cart-dd-items">${itemsHtml}${moreHtml}</div>
            <div class="cart-dd-footer">
                <div class="cart-dd-subtotal">Subtotal: ${formatCents(getSubtotalCents())}</div>
                <a href="/store/cart" class="btn btn-primary cart-dd-checkout">View Cart</a>
            </div>
        `;
    }

    document.addEventListener("DOMContentLoaded", function () {
        updateBadge();
        updateDropdown();
    });

    window.PSVCart = {
        getItems: getItems,
        addItem: addItem,
        removeItem: removeItem,
        updateQuantity: updateQuantity,
        clear: clear,
        getCount: getCount,
        getSubtotalCents: getSubtotalCents,
        formatCents: formatCents,
    };
})();
