(function () {
    const CART_STORAGE_KEY = "psv-cart";
    const CURRENCY_STORAGE_KEY = "psv-currency";
    const FX_CACHE_STORAGE_KEY = "psv-usd-cad-rate";
    const DEFAULT_CURRENCY = "usd";
    const FX_RATE_URL =
        "https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json?recent=1";
    const GEO_URLS = [
        "https://ipwho.is/",
        "https://ipapi.co/json/",
    ];

    let currentCurrency = localStorage.getItem(CURRENCY_STORAGE_KEY) || DEFAULT_CURRENCY;
    let usdCadRate = 1;
    let ratePromise = null;

    function readCart() {
        try {
            const raw = localStorage.getItem(CART_STORAGE_KEY);
            if (!raw) return { items: [] };
            const data = JSON.parse(raw);
            if (!Array.isArray(data.items)) return { items: [] };
            return data;
        } catch {
            return { items: [] };
        }
    }

    function writeCart(cart) {
        localStorage.setItem(CART_STORAGE_KEY, JSON.stringify(cart));
        updateBadge();
        updateDropdown();
        emitCurrencyChange();
    }

    function emitCurrencyChange() {
        document.dispatchEvent(
            new CustomEvent("psv:currencychange", {
                detail: {
                    currency: currentCurrency,
                    rate: usdCadRate,
                },
            }),
        );
    }

    function getItems() {
        return readCart().items;
    }

    function addItem(slug, name, priceCents) {
        const cart = readCart();
        const existing = cart.items.find((item) => item.slug === slug);
        if (existing) {
            existing.quantity += 1;
        } else {
            cart.items.push({
                slug: slug,
                name: name,
                price_cents: priceCents,
                quantity: 1,
            });
        }
        writeCart(cart);
    }

    function removeItem(slug) {
        const cart = readCart();
        cart.items = cart.items.filter((item) => item.slug !== slug);
        writeCart(cart);
    }

    function updateQuantity(slug, quantity) {
        if (quantity < 1) {
            removeItem(slug);
            return;
        }
        const cart = readCart();
        const item = cart.items.find((entry) => entry.slug === slug);
        if (item) {
            item.quantity = quantity;
            writeCart(cart);
        }
    }

    function clear() {
        writeCart({ items: [] });
    }

    function getCount() {
        return getItems().reduce((sum, item) => sum + item.quantity, 0);
    }

    function getSubtotalUsdCents() {
        return getItems().reduce(
            (sum, item) => sum + item.price_cents * item.quantity,
            0,
        );
    }

    function roundUsdCentsForCurrency(usdCents, currency) {
        if (currency === "cad") {
            return Math.round(usdCents * usdCadRate);
        }
        return usdCents;
    }

    function formatCents(cents, currency = currentCurrency) {
        const dollars = currency === "cad" ? Math.round(cents * 1.38 / 100) : cents / 100;
        return new Intl.NumberFormat("en", {
            style: "currency",
            currency: "USD",
        }).format(dollars);
    }

    function formatUsdCents(usdCents, currency = currentCurrency) {
        return formatCents(usdCents, currency);
    }

    function getDisplayCurrency() {
        return currentCurrency;
    }

    function getUsdCadRateFromCache() {
        try {
            const raw = localStorage.getItem(FX_CACHE_STORAGE_KEY);
            if (!raw) return null;
            const cached = JSON.parse(raw);
            if (
                cached &&
                typeof cached.rate === "number" &&
                cached.fetched_on === new Date().toISOString().slice(0, 10)
            ) {
                return cached.rate;
            }
        } catch {
            return null;
        }
        return null;
    }

    function cacheUsdCadRate(rate) {
        localStorage.setItem(
            FX_CACHE_STORAGE_KEY,
            JSON.stringify({
                rate: rate,
                fetched_on: new Date().toISOString().slice(0, 10),
            }),
        );
    }

    async function ensureUsdCadRate() {
        if (usdCadRate !== 1) {
            return usdCadRate;
        }

        const cachedRate = getUsdCadRateFromCache();
        if (cachedRate) {
            usdCadRate = cachedRate;
            return usdCadRate;
        }

        if (!ratePromise) {
            ratePromise = fetch(FX_RATE_URL)
                .then((response) => {
                    if (!response.ok) {
                        throw new Error("Failed to fetch USD/CAD rate");
                    }
                    return response.json();
                })
                .then((payload) => {
                    const observations = payload.observations || [];
                    const latest = observations[observations.length - 1] || {};
                    const value = Number(latest.FXUSDCAD && latest.FXUSDCAD.v);
                    if (!Number.isFinite(value) || value <= 0) {
                        throw new Error("Invalid USD/CAD rate returned");
                    }
                    usdCadRate = value;
                    cacheUsdCadRate(value);
                    ratePromise = null;
                    return value;
                })
                .catch((error) => {
                    ratePromise = null;
                    throw error;
                });
        }

        return ratePromise;
    }

    function isCanadaTimeZone(timeZone) {
        return (
            typeof timeZone === "string" &&
            [
                "America/St_Johns",
                "America/Halifax",
                "America/Glace_Bay",
                "America/Moncton",
                "America/Goose_Bay",
                "America/Toronto",
                "America/Iqaluit",
                "America/Winnipeg",
                "America/Resolute",
                "America/Rankin_Inlet",
                "America/Regina",
                "America/Swift_Current",
                "America/Edmonton",
                "America/Cambridge_Bay",
                "America/Inuvik",
                "America/Dawson_Creek",
                "America/Fort_Nelson",
                "America/Vancouver",
                "America/Whitehorse",
                "America/Dawson",
            ].includes(timeZone)
        );
    }

    function detectCurrencyFromLocale() {
        const locale = navigator.language || "";
        if (locale.toLowerCase().includes("-ca")) {
            return "cad";
        }

        const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        if (isCanadaTimeZone(timeZone)) {
            return "cad";
        }

        return "usd";
    }

    async function detectCurrencyFromClientIp() {
        for (const url of GEO_URLS) {
            try {
                const response = await fetch(url);
                if (!response.ok) {
                    continue;
                }

                const payload = await response.json();
                const countryCode = (
                    payload.country_code ||
                    payload.country ||
                    payload.countryCode ||
                    ""
                ).toUpperCase();

                if (countryCode) {
                    return countryCode === "CA" ? "cad" : "usd";
                }
            } catch {
                continue;
            }
        }

        throw new Error("Failed to determine client country");
    }

    function updateCurrencyButtons() {
        const isCad = currentCurrency === "cad";

        document.querySelectorAll(".currency-choice-code").forEach((button) => {
            button.textContent = isCad ? "CAD" : "USD";
            button.classList.add("is-active");
            button.setAttribute("aria-pressed", "true");
            button.setAttribute(
                "aria-label",
                isCad ? "Switch to US dollars" : "Switch to Canadian dollars",
            );
        });

        document.querySelectorAll(".currency-choice-flag").forEach((button) => {
            button.innerHTML = `<span aria-hidden="true">${isCad ? "🇨🇦" : "🇺🇸"}</span>`;
            button.classList.add("is-active");
            button.setAttribute("aria-pressed", "true");
            button.setAttribute(
                "aria-label",
                isCad ? "Switch to US dollars" : "Switch to Canadian dollars",
            );
        });

        document.querySelectorAll(".currency-choice-symbol").forEach((button) => {
            button.textContent = isCad ? "C$" : "$";
            button.classList.add("is-active");
            button.setAttribute("aria-pressed", "true");
            button.setAttribute(
                "aria-label",
                isCad ? "Switch to US dollars" : "Switch to Canadian dollars",
            );
        });
    }

    function updateStoreWidgets() {
        document.querySelectorAll("[data-currency-set]").forEach((btn) => {
            const active = btn.dataset.currencySet === currentCurrency;
            btn.classList.toggle("is-active", active);
            btn.setAttribute("aria-pressed", String(active));
        });
        document.querySelectorAll(".currency-native-select").forEach((sel) => {
            sel.value = currentCurrency;
        });
    }

    function updatePriceNodes() {
        document.querySelectorAll("[data-price-usd-cents]").forEach((node) => {
            const usdCents = Number(node.dataset.priceUsdCents);
            if (!Number.isFinite(usdCents)) return;
            node.textContent = formatUsdCents(usdCents);
        });
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
                (item) => `
                <div class="cart-dd-item">
                    <span class="cart-dd-name">${item.name}</span>
                    <span class="cart-dd-qty">${item.quantity} &times; ${formatUsdCents(item.price_cents)}</span>
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
                <div class="cart-dd-subtotal">Subtotal: ${formatUsdCents(getSubtotalUsdCents())}</div>
                <a href="/store/cart" class="btn btn-primary cart-dd-checkout">View Cart</a>
            </div>
        `;
    }

    async function setCurrency(currency, options = {}) {
        if (currency !== "usd" && currency !== "cad") {
            return;
        }

        currentCurrency = currency;

        if (currency === "cad") {
            try {
                await ensureUsdCadRate();
            } catch {
                currentCurrency = "usd";
            }
        }

        localStorage.setItem(CURRENCY_STORAGE_KEY, currentCurrency);

        updateCurrencyButtons();
        updateStoreWidgets();
        updatePriceNodes();
        updateDropdown();
        emitCurrencyChange();
    }

    async function initializeCurrency() {
        updateCurrencyButtons();

        if (!localStorage.getItem(CURRENCY_STORAGE_KEY)) {
            try {
                const detectedCurrency = await detectCurrencyFromClientIp();
                await setCurrency(detectedCurrency, { silent: true });
                return;
            } catch {
                await setCurrency(detectCurrencyFromLocale(), { silent: true });
                return;
            }
        }

        await setCurrency(currentCurrency, { silent: true });
    }

    async function checkout() {
        const items = getItems().map((item) => ({
            slug: item.slug,
            quantity: item.quantity,
        }));
        if (items.length === 0) return null;

        const response = await fetch("/store/checkout", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                items: items,
                currency: getDisplayCurrency(),
            }),
        });
        return response;
    }

    document.addEventListener("click", (event) => {
        const toggle = event.target.closest("[data-currency-toggle]");
        if (toggle) {
            setCurrency(currentCurrency === "usd" ? "cad" : "usd");
            return;
        }
        const setter = event.target.closest("[data-currency-set]");
        if (setter) {
            setCurrency(setter.dataset.currencySet);
        }
    });

    document.addEventListener("change", (event) => {
        if (event.target.matches(".currency-native-select")) {
            setCurrency(event.target.value);
        }
    });

    document.addEventListener("DOMContentLoaded", () => {
        updateBadge();
        updateDropdown();
        initializeCurrency();
    });

    window.PSVCart = {
        getItems: getItems,
        addItem: addItem,
        removeItem: removeItem,
        updateQuantity: updateQuantity,
        clear: clear,
        getCount: getCount,
        getSubtotalCents: getSubtotalUsdCents,
        formatCents: formatCents,
        formatUsdCents: formatUsdCents,
        getDisplayCurrency: getDisplayCurrency,
        setCurrency: setCurrency,
        updatePriceNodes: updatePriceNodes,
        checkout: checkout,
    };
})();
