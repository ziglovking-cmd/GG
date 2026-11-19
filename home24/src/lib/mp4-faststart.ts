import fs from "fs";

function readU32(buf: Buffer, i: number) {
  return buf.readUInt32BE(i);
}

function readU64(buf: Buffer, i: number) {
  return Number(buf.readBigUInt64BE(i));
}

type Box = { i: number; size: number; hdr: number; typ: string };

function boxes(buf: Buffer, start = 0, end = buf.length): Box[] {
  const out: Box[] = [];
  let i = start;
  while (i + 8 <= end) {
    let size = readU32(buf, i);
    const typ = buf.subarray(i + 4, i + 8).toString("latin1");
    let hdr = 8;
    if (size === 1) {
      if (i + 16 > end) break;
      size = readU64(buf, i + 8);
      hdr = 16;
    } else if (size === 0) {
      size = end - i;
    }
    if (size < hdr || i + size > end) break;
    out.push({ i, size, hdr, typ });
    i += size;
  }
  return out;
}

function patchOffsets(moov: Buffer, delta: number) {
  const stack: [number, number][] = [[0, moov.length]];
  while (stack.length) {
    const [start, end] = stack.pop()!;
    for (const b of boxes(moov, start, end)) {
      if (["trak", "mdia", "minf", "stbl", "edts", "moov"].includes(b.typ)) {
        stack.push([b.i + b.hdr, b.i + b.size]);
      } else if (b.typ === "stco") {
        const count = readU32(moov, b.i + b.hdr + 4);
        let p = b.i + b.hdr + 8;
        for (let n = 0; n < count; n++, p += 4) {
          moov.writeUInt32BE(readU32(moov, p) + delta, p);
        }
      } else if (b.typ === "co64") {
        const count = readU32(moov, b.i + b.hdr + 4);
        let p = b.i + b.hdr + 8;
        for (let n = 0; n < count; n++, p += 8) {
          moov.writeBigUInt64BE(moov.readBigUInt64BE(p) + BigInt(delta), p);
        }
      }
    }
  }
}

export function faststartBuffer(data: Buffer) {
  const all = boxes(data);
  const ftyp = all.find((b) => b.typ === "ftyp");
  const moov = all.find((b) => b.typ === "moov");
  const mdat = all.find((b) => b.typ === "mdat");
  if (!ftyp || !moov || !mdat || moov.i < mdat.i) return data;
  const ftypBlob = data.subarray(ftyp.i, ftyp.i + ftyp.size);
  const moovBlob = Buffer.from(data.subarray(moov.i, moov.i + moov.size));
  const mdatBlob = data.subarray(mdat.i, mdat.i + mdat.size);
  const rest = all.filter((b) => !["ftyp", "moov", "mdat"].includes(b.typ)).map((b) => data.subarray(b.i, b.i + b.size));
  const newMdat = ftypBlob.length + moovBlob.length;
  patchOffsets(moovBlob, newMdat - mdat.i);
  return Buffer.concat([ftypBlob, moovBlob, ...rest, mdatBlob]);
}

export function faststartFile(abs: string) {
  const raw = fs.readFileSync(abs);
  const out = faststartBuffer(raw);
  if (out.equals(raw)) return false;
  fs.writeFileSync(abs, out);
  return true;
}
