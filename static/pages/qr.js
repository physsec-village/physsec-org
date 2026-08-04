// Original dependency-free QR Code encoder for small client-side payloads.
// It emits byte-mode QR matrices by selecting a version, constructing the
// codeword stream, adding Reed-Solomon error correction, placing modules,
// evaluating all eight masks, and writing the required QR metadata bits.

const RS = {
  1: [[[1,26,19]],[[1,26,16]],[[1,26,13]],[[1,26,9]]],
  2: [[[1,44,34]],[[1,44,28]],[[1,44,22]],[[1,44,16]]],
  3: [[[1,70,55]],[[1,70,44]],[[2,35,17]],[[2,35,13]]],
  4: [[[1,100,80]],[[2,50,32]],[[2,50,24]],[[4,25,9]]],
  5: [[[1,134,108]],[[2,67,43]],[[2,33,15],[2,34,16]],[[2,33,11],[2,34,12]]],
  6: [[[2,86,68]],[[4,43,27]],[[4,43,19]],[[4,43,15]]],
  7: [[[2,98,78]],[[4,49,31]],[[2,32,14],[4,33,15]],[[4,39,13],[1,40,14]]],
  8: [[[2,121,97]],[[2,60,38],[2,61,39]],[[4,40,18],[2,41,19]],[[4,40,14],[2,41,15]]],
  9: [[[2,146,116]],[[3,58,36],[2,59,37]],[[4,36,16],[4,37,17]],[[4,36,12],[4,37,13]]],
  10: [[[2,86,68],[2,87,69]],[[4,69,43],[1,70,44]],[[6,43,19],[2,44,20]],[[6,43,15],[2,44,16]]],
  11: [[[4,101,81]],[[1,80,50],[4,81,51]],[[4,50,22],[4,51,23]],[[3,36,12],[8,37,13]]],
  12: [[[2,116,92],[2,117,93]],[[6,58,36],[2,59,37]],[[4,46,20],[6,47,21]],[[7,42,14],[4,43,15]]],
  13: [[[4,133,107]],[[8,59,37],[1,60,38]],[[8,44,20],[4,45,21]],[[12,33,11],[4,34,12]]],
  14: [[[3,145,115],[1,146,116]],[[4,64,40],[5,65,41]],[[11,36,16],[5,37,17]],[[11,36,12],[5,37,13]]],
  15: [[[5,109,87],[1,110,88]],[[5,65,41],[5,66,42]],[[5,54,24],[7,55,25]],[[11,36,12],[7,37,13]]],
  16: [[[5,122,98],[1,123,99]],[[7,73,45],[3,74,46]],[[15,43,19],[2,44,20]],[[3,45,15],[13,46,16]]],
  17: [[[1,135,107],[5,136,108]],[[10,74,46],[1,75,47]],[[1,50,22],[15,51,23]],[[2,42,14],[17,43,15]]],
  18: [[[5,150,120],[1,151,121]],[[9,69,43],[4,70,44]],[[17,50,22],[1,51,23]],[[2,42,14],[19,43,15]]],
  19: [[[3,141,113],[4,142,114]],[[3,70,44],[11,71,45]],[[17,47,21],[4,48,22]],[[9,39,13],[16,40,14]]],
  20: [[[3,135,107],[5,136,108]],[[3,67,41],[13,68,42]],[[15,54,24],[5,55,25]],[[15,43,15],[10,44,16]]],
};
const ALIGN = {1:[],2:[6,18],3:[6,22],4:[6,26],5:[6,30],6:[6,34],7:[6,22,38],8:[6,24,42],9:[6,26,46],10:[6,28,50],11:[6,30,54],12:[6,32,58],13:[6,34,62],14:[6,26,46,66],15:[6,26,48,70],16:[6,26,50,74],17:[6,30,54,78],18:[6,30,56,82],19:[6,30,58,86],20:[6,34,62,90]};
const ECC_INDEX = {L:0, M:1, Q:2, H:3};
const FORMAT_ECC = {M:0, L:1, H:2, Q:3};
const EXP = Array(512), LOG = Array(256).fill(0);
for (let x = 1, i = 0; i < 255; i++) {
  EXP[i] = x; LOG[x] = i; x <<= 1; if (x & 0x100) x ^= 0x11D;
}
for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255];

export function qrMatrix(text, { ecc = "M", minVersion = 1, maxVersion = 20 } = {}) {
  if (!(ecc in ECC_INDEX)) throw new Error(`Invalid ECC level: ${ecc}`);
  if (minVersion < 1 || maxVersion > 20 || minVersion > maxVersion)
    throw new Error("Version range must be within 1..20");
  const data = Array.from(new TextEncoder().encode(String(text)));
  let version = 0, blocks = null, dataCodewords = 0;
  for (let v = minVersion; v <= maxVersion; v++) {
    const ccBits = v < 10 ? 8 : 16;
    if (data.length >= (1 << ccBits)) continue;
    const b = RS[v][ECC_INDEX[ecc]];
    const cap = b.reduce((s, g) => s + g[0] * g[2], 0);
    if (4 + ccBits + data.length * 8 <= cap * 8) {
      version = v; blocks = b; dataCodewords = cap; break;
    }
  }
  if (!version) throw new Error(`Data does not fit versions ${minVersion}..${maxVersion} at ECC ${ecc}`);

  const codewords = addEcc(makeDataCodewords(data, version, dataCodewords), blocks);
  const base = makeBase(version);
  let best = null, bestPenalty = Infinity;
  for (let mask = 0; mask < 8; mask++) {
    const m = copy(base.modules);
    placeData(m, base.func, codewords, mask);
    const p = penalty(m);
    if (p < bestPenalty) { bestPenalty = p; best = mask; }
  }
  const modules = copy(base.modules);
  placeData(modules, base.func, codewords, best);
  drawFormat(modules, base.func, ecc, best, false);
  if (version >= 7) drawVersion(modules, base.func, version, false);
  modules[4 * version + 9][8] = true;
  return {size: modules.length, modules, version};
}

function makeDataCodewords(bytes, version, count) {
  const bits = [];
  append(bits, 0b0100, 4);
  append(bits, bytes.length, version < 10 ? 8 : 16);
  for (const b of bytes) append(bits, b, 8);
  const cap = count * 8;
  append(bits, 0, Math.min(4, cap - bits.length));
  while (bits.length % 8) bits.push(0);
  for (let pad = 0xEC; bits.length < cap; pad = pad === 0xEC ? 0x11 : 0xEC)
    append(bits, pad, 8);
  const out = [];
  for (let i = 0; i < bits.length; i += 8)
    out.push(bits.slice(i, i + 8).reduce((v, b) => (v << 1) | b, 0));
  return out;
}

function append(bits, val, len) {
  for (let i = len - 1; i >= 0; i--) bits.push((val >>> i) & 1);
}

function addEcc(data, groups) {
  const blocks = [];
  let pos = 0;
  for (const [num, total, datalen] of groups) for (let i = 0; i < num; i++) {
    const dat = data.slice(pos, pos + datalen); pos += datalen;
    blocks.push({dat, ecc: rsRemainder(dat, total - datalen)});
  }
  const out = [];
  for (let i = 0, n = Math.max(...blocks.map(b => b.dat.length)); i < n; i++)
    for (const b of blocks) if (i < b.dat.length) out.push(b.dat[i]);
  for (let i = 0, n = Math.max(...blocks.map(b => b.ecc.length)); i < n; i++)
    for (const b of blocks) if (i < b.ecc.length) out.push(b.ecc[i]);
  return out;
}

function rsRemainder(data, degree) {
  const gen = generator(degree), rem = Array(degree).fill(0);
  for (const b of data) {
    const factor = b ^ rem.shift(); rem.push(0);
    if (factor) for (let i = 0; i < degree; i++) rem[i] ^= mul(gen[i + 1], factor);
  }
  return rem;
}

function generator(degree) {
  let g = [1];
  for (let i = 0; i < degree; i++) {
    const next = Array(g.length + 1).fill(0);
    for (let j = 0; j < g.length; j++) {
      next[j] ^= g[j];
      next[j + 1] ^= mul(g[j], EXP[i]);
    }
    g = next;
  }
  return g;
}

function mul(a, b) { return a && b ? EXP[LOG[a] + LOG[b]] : 0; }

function makeBase(version) {
  const size = 17 + version * 4;
  const modules = Array.from({length:size}, () => Array(size).fill(false));
  const func = Array.from({length:size}, () => Array(size).fill(false));
  drawFinder(modules, func, 0, 0);
  drawFinder(modules, func, size - 7, 0);
  drawFinder(modules, func, 0, size - 7);
  for (const y of ALIGN[version]) for (const x of ALIGN[version])
    if (!func[y][x]) drawAlign(modules, func, x, y);
  for (let i = 8; i < size - 8; i++) {
    set(modules, func, 6, i, i % 2 === 0);
    set(modules, func, i, 6, i % 2 === 0);
  }
  drawFormat(modules, func, "M", 0, true);
  if (version >= 7) drawVersion(modules, func, version, true);
  modules[size - 8][8] = false; func[size - 8][8] = true;
  return {modules, func};
}

function drawFinder(m, f, x, y) {
  for (let dy = -1; dy <= 7; dy++) for (let dx = -1; dx <= 7; dx++) {
    const xx = x + dx, yy = y + dy;
    if (yy < 0 || yy >= m.length || xx < 0 || xx >= m.length) continue;
    const dark = dx >= 0 && dx <= 6 && dy >= 0 && dy <= 6 &&
      (dx === 0 || dx === 6 || dy === 0 || dy === 6 || (dx >= 2 && dx <= 4 && dy >= 2 && dy <= 4));
    set(m, f, xx, yy, dark);
  }
}

function drawAlign(m, f, x, y) {
  for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++)
    set(m, f, x + dx, y + dy, Math.max(Math.abs(dx), Math.abs(dy)) === 2 || (dx === 0 && dy === 0));
}

function drawFormat(m, f, ecc, mask, blank) {
  const size = m.length, bits = blank ? 0 : bchFormat((FORMAT_ECC[ecc] << 3) | mask);
  for (let i = 0; i < 15; i++) {
    const bit = ((bits >>> i) & 1) !== 0;
    if (i < 6) set(m, f, 8, i, bit);
    else if (i < 8) set(m, f, 8, i + 1, bit);
    else set(m, f, 8, size - 15 + i, bit);
    if (i < 8) set(m, f, size - 1 - i, 8, bit);
    else if (i === 8) set(m, f, 7, 8, bit);
    else set(m, f, 14 - i, 8, bit);
  }
}

function drawVersion(m, f, version, blank) {
  const size = m.length, bits = blank ? 0 : bchVersion(version);
  for (let i = 0; i < 18; i++) {
    const bit = ((bits >>> i) & 1) !== 0, a = size - 11 + (i % 3), b = Math.floor(i / 3);
    set(m, f, a, b, bit); set(m, f, b, a, bit);
  }
}

function set(m, f, x, y, dark) { m[y][x] = dark; f[y][x] = true; }

function bchFormat(data) {
  let v = data << 10;
  for (let i = bitLen(v) - 1; i >= 10; i--) if ((v >>> i) & 1) v ^= 0x537 << (i - 10);
  return ((data << 10) | v) ^ 0x5412;
}

function bchVersion(version) {
  let v = version << 12;
  for (let i = bitLen(v) - 1; i >= 12; i--) if ((v >>> i) & 1) v ^= 0x1F25 << (i - 12);
  return (version << 12) | v;
}

function bitLen(v) { let n = 0; while (v) { n++; v >>>= 1; } return n; }

function placeData(m, f, data, mask) {
  let bit = 0, upward = true;
  for (let right = m.length - 1; right > 0; right -= 2) {
    if (right === 6) right--;
    for (let vert = 0; vert < m.length; vert++) {
      const y = upward ? m.length - 1 - vert : vert;
      for (let j = 0; j < 2; j++) {
        const x = right - j;
        if (!f[y][x]) {
          let dark = bit < data.length * 8 && ((data[bit >>> 3] >>> (7 - (bit & 7))) & 1) !== 0;
          if (maskBit(mask, y, x)) dark = !dark;
          m[y][x] = dark; bit++;
        }
      }
    }
    upward = !upward;
  }
}

function maskBit(mask, r, c) {
  if (mask === 0) return (r + c) % 2 === 0;
  if (mask === 1) return r % 2 === 0;
  if (mask === 2) return c % 3 === 0;
  if (mask === 3) return (r + c) % 3 === 0;
  if (mask === 4) return (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0;
  if (mask === 5) return ((r * c) % 2 + (r * c) % 3) === 0;
  if (mask === 6) return ((r * c) % 2 + (r * c) % 3) % 2 === 0;
  return ((r * c) % 3 + (r + c) % 2) % 2 === 0;
}

function penalty(m) {
  const n = m.length;
  let p = runs(m) + runs(transpose(m));
  for (let y = 0; y < n - 1; y++) for (let x = 0; x < n - 1; x++)
    if (m[y][x] === m[y][x + 1] && m[y][x] === m[y + 1][x] && m[y][x] === m[y + 1][x + 1]) p += 3;
  p += finderPenalty(m) + finderPenalty(transpose(m));
  const dark = m.flat().filter(Boolean).length;
  return p + Math.floor(Math.abs(dark * 100 / (n * n) - 50) / 5) * 10;
}

function runs(rows) {
  let p = 0;
  for (const row of rows) {
    let run = 1;
    for (let i = 1; i <= row.length; i++) {
      if (i < row.length && row[i] === row[i - 1]) run++;
      else { if (run >= 5) p += 3 + run - 5; run = 1; }
    }
  }
  return p;
}

function finderPenalty(rows) {
  let p = 0;
  for (const row of rows) for (let x = 0; x <= row.length - 11; x++) {
    if (!row[x + 1] && row[x + 4] && !row[x + 5] && row[x + 6] && !row[x + 9] &&
      ((row[x] && row[x + 2] && row[x + 3] && !row[x + 7] && !row[x + 8] && !row[x + 10]) ||
       (!row[x] && !row[x + 2] && !row[x + 3] && row[x + 7] && row[x + 8] && row[x + 10]))) {
      p += 40;
    }
    if (row[x + 10]) x++;
  }
  return p;
}

function transpose(m) { return m[0].map((_, x) => m.map(row => row[x])); }
function copy(m) { return m.map(row => row.slice()); }
