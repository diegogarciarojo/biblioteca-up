// Keep original UTF-16 positions so accents/combined marks never shift highlights.
export function normalizeSearch(text) {
  let value = '';
  const starts = [], ends = [];
  let offset = 0;
  for (const character of text) {
    const end = offset + character.length;
    const folded = character.toLowerCase().normalize('NFD').replace(/\p{M}/gu, '').replace(/ß/g, 'ss').replace(/ς/g, 'σ');
    if (!folded && ends.length) ends[ends.length - 1] = end;
    for (const part of folded) {
      const normalized = /\s/u.test(part) ? ' ' : part;
      if (normalized === ' ' && value.endsWith(' ')) {
        ends[ends.length - 1] = end;
      } else {
        value += normalized;
        for (let unit = 0; unit < normalized.length; unit++) {
          starts.push(offset);
          ends.push(end);
        }
      }
    }
    offset = end;
  }
  return { value, starts, ends };
}
