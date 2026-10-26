// Store admin: confirm destructive forms and suggest URL slugs.
(() => {
    document.addEventListener("submit", (event) => {
        const message = event.target.dataset.confirm;
        if (message && !window.confirm(message)) {
            event.preventDefault();
        }
    });

    // Fill an empty slug from the name until the admin edits the slug.
    const source = document.querySelector("[data-slug-source]");
    const target = document.querySelector("[data-slug-target]");
    if (!source || !target) return;
    let automatic = target.value === "";
    target.addEventListener("input", () => {
        automatic = target.value === "";
    });
    source.addEventListener("input", () => {
        if (!automatic) return;
        target.value = source.value
            .toLowerCase()
            .normalize("NFKD")
            .replace(/[^a-z0-9]+/g, "-")
            .replace(/^-+|-+$/g, "");
    });
})();
