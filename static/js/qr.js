// qr code encoder (byte mode, error correction L or M, versions 1 to 40), no dependencies.
// follows ISO/IEC 18004 and the layout steps of Project Nayuki's MIT-licensed qr generator.
// alles uses it to show a scan-to-set-up code for Obsidian, so nothing is fetched from a server.

const LEVELS = {
  L: {
    bits: 1,
    perBlock: [-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28, 28, 28, 28, 30, 30, 26, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
    blocks: [-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8, 8, 9, 9, 10, 12, 12, 12, 13, 14, 15, 16, 17, 18, 19, 19, 20, 21, 22, 24, 25],
  },
  M: {
    bits: 0,
    perBlock: [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26, 26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28],
    blocks: [-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16, 17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49],
  },
};

const rawModules = ver => {
  let n = (16 * ver + 128) * ver + 64;
  if (ver >= 2) {
    const align = Math.floor(ver / 7) + 2;
    n -= (25 * align - 10) * align - 55;
    if (ver >= 7) n -= 36;
  }
  return n;
};

const dataCodewords = (ver, level) =>
  Math.floor(rawModules(ver) / 8) - level.perBlock[ver] * level.blocks[ver];

// reed-solomon over GF(256), polynomial 0x11D
const gfMul = (x, y) => {
  let z = 0;
  for (let i = 7; i >= 0; i--) {
    z = (z << 1) ^ ((z >>> 7) * 0x11d);
    z ^= ((y >>> i) & 1) * x;
  }
  return z;
};

const rsDivisor = degree => {
  const out = new Array(degree).fill(0);
  out[degree - 1] = 1;
  let root = 1;
  for (let i = 0; i < degree; i++) {
    for (let j = 0; j < degree; j++) {
      out[j] = gfMul(out[j], root);
      if (j + 1 < degree) out[j] ^= out[j + 1];
    }
    root = gfMul(root, 0x02);
  }
  return out;
};

const rsRemainder = (data, divisor) => {
  const out = divisor.map(() => 0);
  for (const byte of data) {
    const factor = byte ^ out.shift();
    out.push(0);
    divisor.forEach((coef, i) => { out[i] ^= gfMul(coef, factor); });
  }
  return out;
};

const alignPositions = ver => {
  if (ver === 1) return [];
  const count = Math.floor(ver / 7) + 2;
  const step = ver === 32 ? 26 : Math.ceil((ver * 4 + 4) / (count * 2 - 2)) * 2;
  const out = [6];
  for (let pos = ver * 4 + 10; out.length < count; pos -= step) out.splice(1, 0, pos);
  return out;
};

const MASKS = [
  (x, y) => (x + y) % 2 === 0,
  (x, y) => y % 2 === 0,
  (x, y) => x % 3 === 0,
  (x, y) => (x + y) % 3 === 0,
  (x, y) => (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0,
  (x, y) => ((x * y) % 2) + ((x * y) % 3) === 0,
  (x, y) => (((x * y) % 2) + ((x * y) % 3)) % 2 === 0,
  (x, y) => ((((x + y) % 2) + ((x * y) % 3)) % 2) === 0,
];

const penalty = (m, size) => {
  let score = 0;
  const lines = [];
  for (let a = 0; a < size; a++) {
    lines.push(m[a].slice());
    lines.push(m.map(row => row[a]));
  }
  const finderLike = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0];
  for (const line of lines) {
    let run = 1;
    for (let i = 1; i <= size; i++) {
      if (i < size && line[i] === line[i - 1]) run++;
      else { if (run >= 5) score += run - 2; run = 1; }
    }
    for (let i = 0; i + 11 <= size; i++) {
      let fwd = true, back = true;
      for (let k = 0; k < 11; k++) {
        if ((line[i + k] ? 1 : 0) !== finderLike[k]) fwd = false;
        if ((line[i + k] ? 1 : 0) !== finderLike[10 - k]) back = false;
      }
      if (fwd) score += 40;
      if (back) score += 40;
    }
  }
  let dark = 0;
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      if (m[y][x]) dark++;
      if (x + 1 < size && y + 1 < size && m[y][x] === m[y][x + 1] && m[y][x] === m[y + 1][x] && m[y][x] === m[y + 1][x + 1]) score += 3;
    }
  }
  const total = size * size;
  score += Math.floor(Math.abs(dark * 20 - total * 10) / total) * 10;
  return score;
};

// the matrix as rows of booleans (true = dark)
export function qrMatrix(text, { level = 'M' } = {}) {
  const lv = LEVELS[level];
  if (!lv) throw new Error('level must be L or M');
  const bytes = [...new TextEncoder().encode(text)];

  let ver = 1;
  for (;; ver++) {
    if (ver > 40) throw new Error('text is too long for a qr code');
    const need = 4 + (ver < 10 ? 8 : 16) + bytes.length * 8;
    if (need <= dataCodewords(ver, lv) * 8) break;
  }

  const bits = [];
  const put = (value, len) => { for (let i = len - 1; i >= 0; i--) bits.push((value >>> i) & 1); };
  put(0b0100, 4);
  put(bytes.length, ver < 10 ? 8 : 16);
  bytes.forEach(b => put(b, 8));
  const capacity = dataCodewords(ver, lv) * 8;
  put(0, Math.min(4, capacity - bits.length));
  put(0, (8 - (bits.length % 8)) % 8);
  for (let pad = 0xec; bits.length < capacity; pad ^= 0xec ^ 0x11) put(pad, 8);
  const data = [];
  for (let i = 0; i < bits.length; i += 8) data.push(parseInt(bits.slice(i, i + 8).join(''), 2));

  // split into blocks, add error correction, interleave
  const nBlocks = lv.blocks[ver], eccLen = lv.perBlock[ver];
  const raw = Math.floor(rawModules(ver) / 8);
  const short = nBlocks - (raw % nBlocks), shortLen = Math.floor(raw / nBlocks);
  const divisor = rsDivisor(eccLen);
  const blocks = [];
  for (let i = 0, k = 0; i < nBlocks; i++) {
    const len = shortLen - eccLen + (i < short ? 0 : 1);
    const part = data.slice(k, k + len);
    k += len;
    const ecc = rsRemainder(part, divisor);
    if (i < short) part.push(0);
    blocks.push(part.concat(ecc));
  }
  const stream = [];
  for (let i = 0; i < blocks[0].length; i++) {
    blocks.forEach((block, j) => { if (i !== shortLen - eccLen || j >= short) stream.push(block[i]); });
  }

  // function patterns
  const size = ver * 4 + 17;
  const mod = Array.from({ length: size }, () => new Array(size).fill(false));
  const fn = Array.from({ length: size }, () => new Array(size).fill(false));
  const set = (x, y, dark) => { mod[y][x] = dark; fn[y][x] = true; };
  for (let i = 0; i < size; i++) { set(6, i, i % 2 === 0); set(i, 6, i % 2 === 0); }
  const finder = (cx, cy) => {
    for (let dy = -4; dy <= 4; dy++) {
      for (let dx = -4; dx <= 4; dx++) {
        const x = cx + dx, y = cy + dy, dist = Math.max(Math.abs(dx), Math.abs(dy));
        if (x >= 0 && x < size && y >= 0 && y < size) set(x, y, dist !== 2 && dist !== 4);
      }
    }
  };
  finder(3, 3); finder(size - 4, 3); finder(3, size - 4);
  const pos = alignPositions(ver);
  pos.forEach((cx, i) => pos.forEach((cy, j) => {
    if ((i === 0 && j === 0) || (i === 0 && j === pos.length - 1) || (i === pos.length - 1 && j === 0)) return;
    for (let dy = -2; dy <= 2; dy++) {
      for (let dx = -2; dx <= 2; dx++) set(cx + dx, cy + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
    }
  }));
  const formatBits = mask => {
    const value = (lv.bits << 3) | mask;
    let rem = value;
    for (let i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
    const all = ((value << 10) | rem) ^ 0x5412;
    const bit = i => ((all >>> i) & 1) !== 0;
    for (let i = 0; i <= 5; i++) set(8, i, bit(i));
    set(8, 7, bit(6)); set(8, 8, bit(7)); set(7, 8, bit(8));
    for (let i = 9; i < 15; i++) set(14 - i, 8, bit(i));
    for (let i = 0; i < 8; i++) set(size - 1 - i, 8, bit(i));
    for (let i = 8; i < 15; i++) set(8, size - 15 + i, bit(i));
    set(8, size - 8, true);
  };
  formatBits(0); // reserves the cells; the real mask is written below
  if (ver >= 7) {
    let rem = ver;
    for (let i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1f25);
    const all = (ver << 12) | rem;
    for (let i = 0; i < 18; i++) {
      const dark = ((all >>> i) & 1) !== 0, a = size - 11 + (i % 3), b = Math.floor(i / 3);
      set(a, b, dark); set(b, a, dark);
    }
  }

  // data, in the zigzag order
  let n = 0;
  for (let right = size - 1; right >= 1; right -= 2) {
    if (right === 6) right = 5;
    for (let vert = 0; vert < size; vert++) {
      for (let j = 0; j < 2; j++) {
        const x = right - j;
        const y = ((right + 1) & 2) === 0 ? size - 1 - vert : vert;
        if (!fn[y][x] && n < stream.length * 8) {
          mod[y][x] = ((stream[n >>> 3] >>> (7 - (n & 7))) & 1) !== 0;
          n++;
        }
      }
    }
  }

  // pick the mask with the lowest penalty
  let best = 0, bestScore = Infinity;
  for (let m = 0; m < 8; m++) {
    const test = mod.map((row, y) => row.map((v, x) => (fn[y][x] ? v : v !== MASKS[m](x, y))));
    const score = penalty(test, size);
    if (score < bestScore) { best = m; bestScore = score; }
  }
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) if (!fn[y][x]) mod[y][x] = mod[y][x] !== MASKS[best](x, y);
  }
  formatBits(best);
  return mod;
}

// an svg string: black modules on white, with the 4 module quiet zone scanners need
export function qrSvg(text, { level = 'M', label = '' } = {}) {
  const rows = qrMatrix(text, { level });
  const quiet = 4, dim = rows.length + quiet * 2;
  let path = '';
  rows.forEach((row, y) => {
    for (let x = 0; x < row.length; x++) {
      if (!row[x]) continue;
      let end = x;
      while (end + 1 < row.length && row[end + 1]) end++;
      path += `M${x + quiet} ${y + quiet}h${end - x + 1}v1h-${end - x + 1}z`;
      x = end;
    }
  });
  const name = label ? ` role="img" aria-label="${label.replace(/[<>&"]/g, '')}"` : ' aria-hidden="true"';
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${dim} ${dim}"${name} shape-rendering="crispEdges"><rect width="${dim}" height="${dim}" fill="#fff"/><path d="${path}" fill="#000"/></svg>`;
}
