// Readers for the exported files (docs/API.md §5), without extra dependencies:
// CSV (RFC 4180, all fields quoted) and the cell values of an XLSX sheet.
import { inflateRawSync } from 'node:zlib';

/** Rows of a CSV text (without a byte order mark). */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = '';
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const char = text.charAt(i);
    if (quoted) {
      if (char === '"' && text.charAt(i + 1) === '"') {
        field += '"';
        i += 1;
      } else if (char === '"') quoted = false;
      else field += char;
    } else if (char === '"') quoted = true;
    else if (char === ',') {
      row.push(field);
      field = '';
    } else if (char === '\n' || char === '\r') {
      if (char === '\r' && text.charAt(i + 1) === '\n') i += 1;
      row.push(field);
      rows.push(row);
      row = [];
      field = '';
    } else field += char;
  }
  if (field !== '' || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

/** The entries of a ZIP archive, read from its central directory. */
export function unzip(archive: Buffer): Map<string, Buffer> {
  const END_OF_CENTRAL_DIRECTORY = 0x06054b50;
  let end = -1;
  for (let i = archive.length - 22; i >= Math.max(0, archive.length - 65_557); i -= 1) {
    if (archive.readUInt32LE(i) === END_OF_CENTRAL_DIRECTORY) {
      end = i;
      break;
    }
  }
  if (end < 0) throw new Error('Not a ZIP archive');
  const entries = new Map<string, Buffer>();
  let offset = archive.readUInt32LE(end + 16);
  for (let n = archive.readUInt16LE(end + 10); n > 0; n -= 1) {
    if (archive.readUInt32LE(offset) !== 0x02014b50) throw new Error('Malformed ZIP central directory');
    const method = archive.readUInt16LE(offset + 10);
    const compressedSize = archive.readUInt32LE(offset + 20);
    const nameLength = archive.readUInt16LE(offset + 28);
    const extraLength = archive.readUInt16LE(offset + 30);
    const commentLength = archive.readUInt16LE(offset + 32);
    const localHeader = archive.readUInt32LE(offset + 42);
    const name = archive.toString('utf8', offset + 46, offset + 46 + nameLength);
    const start = localHeader + 30 + archive.readUInt16LE(localHeader + 26) + archive.readUInt16LE(localHeader + 28);
    const data = archive.subarray(start, start + compressedSize);
    entries.set(name, method === 8 ? inflateRawSync(data) : Buffer.from(data));
    offset += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}

const XML_ENTITIES: Readonly<Record<string, string>> = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" };

function decodeXml(text: string): string {
  return text.replace(/&(#x[0-9a-fA-F]+|#[0-9]+|[a-z]+);/g, (entity, name: string) => {
    if (name.startsWith('#x')) return String.fromCodePoint(parseInt(name.slice(2), 16));
    if (name.startsWith('#')) return String.fromCodePoint(parseInt(name.slice(1), 10));
    return XML_ENTITIES[name] ?? entity;
  });
}

/** The text of every <t> element in an XML fragment, joined (shared and inline strings). */
const textOf = (xml: string): string =>
  [...xml.matchAll(/<t(?:\s[^>]*)?>([^<]*)<\/t>/g)].map((match) => decodeXml(match[1] ?? '')).join('');

/** Column index of a cell reference such as "C7" (A = 0). */
function columnIndex(reference: string): number {
  const letters = /^[A-Z]+/.exec(reference)?.[0] ?? 'A';
  let index = 0;
  for (let i = 0; i < letters.length; i += 1) index = index * 26 + letters.charCodeAt(i) - 64;
  return index - 1;
}

/** Cell values of the first worksheet as text: strings, numbers ("1"), booleans ("1"/"0"). */
export function readXlsx(archive: Buffer): string[][] {
  const entries = unzip(archive);
  const sheet = entries.get('xl/worksheets/sheet1.xml')?.toString('utf8');
  if (sheet === undefined) throw new Error('The workbook has no first worksheet');
  const sharedXml = entries.get('xl/sharedStrings.xml')?.toString('utf8') ?? '';
  const shared = [...sharedXml.matchAll(/<si>([\s\S]*?)<\/si>/g)].map((match) => textOf(match[1] ?? ''));
  return [...sheet.matchAll(/<row\b[^>]*>([\s\S]*?)<\/row>/g)].map((rowMatch) => {
    const row: string[] = [];
    for (const cell of (rowMatch[1] ?? '').matchAll(/<c\b([^>]*?)(?:\/>|>([\s\S]*?)<\/c>)/g)) {
      const attributes = cell[1] ?? '';
      const body = cell[2] ?? '';
      const reference = /\br="([A-Z]+[0-9]+)"/.exec(attributes)?.[1] ?? '';
      const type = /\bt="([a-zA-Z]+)"/.exec(attributes)?.[1] ?? 'n';
      const raw = decodeXml(/<v>([^<]*)<\/v>/.exec(body)?.[1] ?? '');
      let value = raw;
      if (type === 's') value = shared[Number(raw)] ?? '';
      else if (type === 'inlineStr') value = textOf(body);
      const index = reference ? columnIndex(reference) : row.length;
      while (row.length < index) row.push('');
      row[index] = value;
    }
    return row;
  });
}
