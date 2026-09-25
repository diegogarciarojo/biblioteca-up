import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeSearch } from '../static/js/search-text.js';

test('accent insensitive phrases retain exact original highlight positions', () => {
  const text = 'Árbol: Seccio\u0301n\n  2.3; SECCIÓN 2.3';
  const normalized = normalizeSearch(text);
  for (const query of ['Seccion 2.3', 'Sección 2.3', 'SECCIO\u0301N 2.3']) {
    const needle = normalizeSearch(query).value;
    const first = normalized.value.indexOf(needle);
    const second = normalized.value.indexOf(needle, first + needle.length);
    assert.equal(text.slice(normalized.starts[first], normalized.ends[first + needle.length - 1]), 'Seccio\u0301n\n  2.3');
    assert.equal(text.slice(normalized.starts[second], normalized.ends[second + needle.length - 1]), 'SECCIÓN 2.3');
  }
});

test('highlight offsets survive surrogate pairs and a trailing combining mark', () => {
  const text = '📚 cafe\u0301';
  const result = normalizeSearch(text);
  const start = result.value.indexOf('cafe');
  assert.equal(text.slice(result.starts[start], result.ends[start + 3]), 'cafe\u0301');
});
