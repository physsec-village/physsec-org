// Client-side search for the server-rendered DEF CON store menu.

const rows = Array.from(document.querySelectorAll(".menu-row"));
const groups = Array.from(document.querySelectorAll(".menu-group"));
const sections = Array.from(document.querySelectorAll(".menu-section"));
const search = document.getElementById("menuSearch");
const empty = document.getElementById("menuEmpty");
const emptyQuery = document.getElementById("menuEmptyQuery");

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
