// Store menu: search filtering, and a list ("cart") kept in localStorage that
// renders a QR code for the register to scan. Everything stays on the device;
// there is no store backend behind this page.

import { qrMatrix } from "./qr.js";

const STORAGE_KEY = "psv-menu-list-v1";
const PAYLOAD_PREFIX = "PSV34";

const rows = Array.from(document.querySelectorAll(".menu-row"));
const groups = Array.from(document.querySelectorAll(".menu-group"));
const sections = Array.from(document.querySelectorAll(".menu-section"));

const search = document.getElementById("menuSearch");
const empty = document.getElementById("menuEmpty");
const emptyQuery = document.getElementById("menuEmptyQuery");

const panel = document.getElementById("cartPanel");
const backdrop = document.getElementById("cartBackdrop");
const openButton = document.getElementById("cartOpen");
const closeButton = document.getElementById("cartClose");
const clearButton = document.getElementById("cartClear");
const linesEl = document.getElementById("cartLines");
const emptyEl = document.getElementById("cartEmpty");
const footEl = document.getElementById("cartFoot");
const totalEl = document.getElementById("cartTotal");
const countEl = document.getElementById("cartCount");
const symbolEl = document.getElementById("cartCodeSymbol");
const codeTextEl = document.getElementById("cartCodeText");

// code -> {name, price} for everything on the page, read straight from the
// markup so the catalogue never has to be duplicated in JS.
const catalogue = new Map();
for (const button of document.querySelectorAll("[data-add]")) {
    catalogue.set(button.dataset.add, {
        name: button.dataset.name,
        price: Number(button.dataset.price),
    });
}

/* ---------------- search ---------------- */

const haystacks = new Map(
    rows.map((row) => [row, row.textContent.toLowerCase().replace(/\s+/g, " ")]),
);

function filter() {
    const query = search.value.trim().toLowerCase();
    let shown = 0;

    for (const row of rows) {
        const match = !query || haystacks.get(row).includes(query);
        row.hidden = !match;
        if (match) shown += 1;
    }

    // Sub-headings, intro copy and reference tables live in the group next to
    // their rows, so hide the whole group once none of its rows survive.
    for (const group of groups) {
        group.hidden = Boolean(query) && !group.querySelector(".menu-row:not([hidden])");
    }
    for (const section of sections) {
        section.hidden = Boolean(query) && !section.querySelector(".menu-row:not([hidden])");
    }

    emptyQuery.textContent = search.value.trim();
    empty.hidden = shown !== 0;
}

search.addEventListener("input", filter);

/* ---------------- list state ---------------- */

/** @type {Map<string, number>} code -> quantity */
let list = new Map();

function load() {
    let stored = null;
    try {
        stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "{}");
    } catch {
        stored = null;
    }
    list = new Map();
    if (stored && typeof stored === "object") {
        for (const [code, qty] of Object.entries(stored)) {
            // Drop anything that is no longer on the menu, so a stale list from
            // a previous year cannot resurrect a discontinued item.
            if (catalogue.has(code) && Number.isFinite(qty) && qty > 0) {
                list.set(code, Math.min(Math.floor(qty), 99));
            }
        }
    }
}

function save() {
    try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(Object.fromEntries(list)));
    } catch {
        // Private browsing or a full quota: the list still works for this page
        // view, it just will not survive a reload.
    }
}

function itemCount() {
    let n = 0;
    for (const qty of list.values()) n += qty;
    return n;
}

function total() {
    let sum = 0;
    for (const [code, qty] of list) sum += catalogue.get(code).price * qty;
    return sum;
}

function setQuantity(code, qty) {
    if (qty > 0) list.set(code, Math.min(qty, 99));
    else list.delete(code);
    save();
    render();
}

/* ---------------- payload + symbol ---------------- */

// `PSV34|KYS016001*2|BYP014002*1|T220` — compacted SKUs (the PSV- prefix and
// dashes are implied) so the symbol stays low-density enough to scan off a
// phone screen. T is the estimated total in whole dollars.
function payload() {
    const parts = [PAYLOAD_PREFIX];
    for (const [code, qty] of list) parts.push(qty === 1 ? code : `${code}*${qty}`);
    parts.push(`T${total()}`);
    return parts.join("|");
}

function renderSymbol(text) {
    symbolEl.replaceChildren();
    let matrix;
    try {
        matrix = qrMatrix(text, { ecc: "M" });
    } catch {
        const fallback = document.createElement("p");
        fallback.className = "cart-code-hint";
        fallback.textContent = "List is too long to encode — read it out instead.";
        symbolEl.append(fallback);
        return;
    }

    const { size, modules } = matrix;
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${size} ${size}`);
    svg.setAttribute("shape-rendering", "crispEdges");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "QR code for your list");

    // One path for every dark module keeps the DOM small and the edges sharp.
    let d = "";
    for (let y = 0; y < size; y += 1) {
        for (let x = 0; x < size; x += 1) {
            if (modules[y][x]) d += `M${x} ${y}h1v1h-1z`;
        }
    }
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", d);
    path.setAttribute("fill", "#000");
    svg.append(path);
    symbolEl.append(svg);
}

/* ---------------- rendering ---------------- */

// Rebuilding the lines replaces the button the user is standing on, which would
// drop keyboard focus mid-adjustment. Remember where focus was and put it back.
function focusToken() {
    const active = document.activeElement;
    const line = active?.closest?.(".cart-line");
    if (!line || !active.dataset.step) return null;
    return `${line.dataset.code}:${active.dataset.step}`;
}

function restoreFocus(token) {
    if (!token) return;
    const [code, step] = token.split(":");
    const line = linesEl.querySelector(`.cart-line[data-code="${CSS.escape(code)}"]`);
    const button = line?.querySelector(`[data-step="${step}"]`);
    // The line is gone once its quantity hits zero; fall back to the panel.
    (button || closeButton).focus();
}

function render() {
    const token = focusToken();
    const count = itemCount();
    countEl.hidden = count === 0;
    countEl.textContent = String(count);

    for (const button of document.querySelectorAll("[data-add]")) {
        button.classList.toggle("is-added", list.has(button.dataset.add));
    }

    linesEl.replaceChildren();
    emptyEl.hidden = count !== 0;
    footEl.hidden = count === 0;

    if (count === 0) {
        symbolEl.replaceChildren();
        return;
    }

    for (const [code, qty] of list) {
        const item = catalogue.get(code);
        const li = document.createElement("li");
        li.className = "cart-line";
        li.dataset.code = code;

        const name = document.createElement("span");
        name.className = "cart-line-name";
        name.textContent = item.name;

        const lineTotal = document.createElement("span");
        lineTotal.className = "cart-line-total";
        lineTotal.textContent = `$${item.price * qty}`;

        const qtyWrap = document.createElement("div");
        qtyWrap.className = "cart-qty";
        const minus = document.createElement("button");
        minus.type = "button";
        minus.textContent = "−";
        minus.dataset.step = "down";
        minus.setAttribute("aria-label", `One fewer ${item.name}`);
        minus.addEventListener("click", () => setQuantity(code, qty - 1));
        const shown = document.createElement("span");
        shown.textContent = String(qty);
        const plus = document.createElement("button");
        plus.type = "button";
        plus.textContent = "+";
        plus.dataset.step = "up";
        plus.setAttribute("aria-label", `One more ${item.name}`);
        plus.addEventListener("click", () => setQuantity(code, qty + 1));
        qtyWrap.append(minus, shown, plus);

        li.append(name, lineTotal, qtyWrap);
        linesEl.append(li);
    }

    totalEl.textContent = `$${total()}`;
    const text = payload();
    codeTextEl.textContent = text;
    renderSymbol(text);
    restoreFocus(token);
}

/* ---------------- panel plumbing ---------------- */

function openPanel() {
    panel.hidden = false;
    backdrop.hidden = false;
    closeButton.focus();
}

function closePanel() {
    panel.hidden = true;
    backdrop.hidden = true;
    openButton.focus();
}

openButton.addEventListener("click", openPanel);
closeButton.addEventListener("click", closePanel);
backdrop.addEventListener("click", closePanel);
document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !panel.hidden) closePanel();
});

clearButton.addEventListener("click", () => {
    list.clear();
    save();
    render();
});

for (const button of document.querySelectorAll("[data-add]")) {
    button.addEventListener("click", () => {
        const code = button.dataset.add;
        setQuantity(code, (list.get(code) || 0) + 1);
    });
}

load();
render();
