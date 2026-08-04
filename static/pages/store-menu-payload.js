import { qrMatrix } from "./qr.js";

const PAYLOAD_PREFIX = "PSV34";
export const MAX_QR_VERSION = 6;
// Verified against qrMatrix: version 6 with ECC M holds 106 byte-mode bytes.
const MAX_PAYLOAD_BYTES = 106;
const encoder = new TextEncoder();

function pagePayload(tokens, total, index, pageCount) {
    return [PAYLOAD_PREFIX, `Q${index}/${pageCount}`, ...tokens, `T${total}`].join("|");
}

function fits(text) {
    if (encoder.encode(text).length <= MAX_PAYLOAD_BYTES) return true;
    try {
        qrMatrix(text, { ecc: "M", maxVersion: MAX_QR_VERSION });
    } catch {
        return false;
    }
    return true;
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
