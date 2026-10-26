// Store admin sign-in and sign-out through Clerk's browser SDK.
//
// clerk.browser.js is loaded from the Clerk Frontend API with the publishable
// key in its data attribute (see store/admin/base.html). It keeps the
// __session cookie fresh while a page is open; the server verifies that
// cookie on every admin request.
(function () {
    "use strict";

    function showError(message) {
        const main = document.querySelector(".admin-main");
        if (!main) return;
        const error = document.createElement("p");
        error.className = "admin-error";
        error.setAttribute("role", "alert");
        error.textContent = message;
        main.prepend(error);
    }

    window.addEventListener("load", async () => {
        if (!window.Clerk) {
            showError("Sign-in could not be loaded. Check your connection and reload.");
            return;
        }
        try {
            await window.Clerk.load();
        } catch (error) {
            console.error(error);
            showError("Sign-in could not be loaded. Reload to try again.");
            return;
        }

        // Set while the login page bounces a signed-in browser to the
        // dashboard, so a server that keeps rejecting the session (wrong
        // origin or keys) cannot cause a redirect loop.
        const REDIRECTED = "storeAdminRedirected";
        const mount = document.getElementById("clerk-sign-in");
        if (!mount) {
            sessionStorage.removeItem(REDIRECTED);
        } else {
            const afterSignInUrl = mount.dataset.afterSignInUrl;
            if (window.Clerk.user && !sessionStorage.getItem(REDIRECTED)) {
                // The browser already holds a Clerk session (for example the
                // cookie expired in an idle tab); load() refreshed it.
                sessionStorage.setItem(REDIRECTED, "1");
                window.location.replace(afterSignInUrl);
                return;
            }
            if (window.Clerk.user) {
                sessionStorage.removeItem(REDIRECTED);
                showError("The server rejected your session. Please sign in again.");
                await window.Clerk.signOut();
            }
            // Match the admin theme; the page's dark colour scheme otherwise
            // renders native inputs dark inside Clerk's light card.
            const theme = getComputedStyle(document.documentElement);
            const color = (name) => theme.getPropertyValue(name).trim();
            window.Clerk.mountSignIn(mount, {
                forceRedirectUrl: afterSignInUrl,
                appearance: {
                    variables: {
                        colorPrimary: color("--accent"),
                        colorBackground: color("--surface-raised"),
                        colorText: color("--text"),
                        colorTextSecondary: color("--muted"),
                        colorInputBackground: color("--bg"),
                        colorInputText: color("--text"),
                        colorNeutral: color("--text"),
                        borderRadius: color("--radius-xs"),
                    },
                },
            });
        }

        for (const button of document.querySelectorAll("[data-sign-out]")) {
            button.addEventListener("click", () => {
                window.Clerk.signOut({ redirectUrl: button.dataset.signOut });
            });
        }
    });
})();

// Confirm destructive forms and suggest URL slugs.
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
