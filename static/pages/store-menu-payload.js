import { qrMatrix } from "./qr.js";

const PAYLOAD_PREFIX = "PSV34";

function pagePayload(tokens, total, index, pageCount) {
    return [PAYLOAD_PREFIX, `Q${index}/${pageCount}`, ...tokens, `T${total}`].join("|");
}

function fits(text) {
    try {
        qrMatrix(text, { ecc: "M", maxVersion: 20 });
        return true;
    } catch {
        return false;
    }
}

/**
 * Split item tokens across scannable payloads. Tokens are indivisible: a
 * quantity such as KYS016001*2 always stays in one symbol.
 */
export function payloads(tokens, total) {
    if (tokens.length === 0) return [];

    // The page-count field itself affects capacity. Repack until its value
    // agrees with the number of pages it produced (normally one or two passes).
    let pageCount = 1;
    for (;;) {
        const pages = [];
        let current = [];

        for (const token of tokens) {
            const candidate = [...current, token];
            const index = pages.length + 1;
            if (fits(pagePayload(candidate, total, index, pageCount))) {
                current = candidate;
                continue;
            }

            if (current.length === 0) {
                throw new Error(`Item token is too long to encode: ${token}`);
            }
            pages.push(current);
            current = [token];
            if (!fits(pagePayload(current, total, pages.length + 1, pageCount))) {
                throw new Error(`Item token is too long to encode: ${token}`);
            }
        }
        if (current.length) pages.push(current);

        const actualCount = pages.length;
        if (actualCount === pageCount) {
            return pages.map((page, offset) =>
                pagePayload(page, total, offset + 1, actualCount),
            );
        }
        pageCount = actualCount;
    }
}
