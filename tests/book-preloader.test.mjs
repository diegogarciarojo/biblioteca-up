import assert from 'node:assert/strict';
import { test } from 'node:test';
import { BookPreloader } from '../static/js/book-preloader.js';

function fixture(total = 12) {
  const data = new Map();
  const calls = [];
  const states = [];
  let concurrent = 0;
  let maximum = 0;
  const cache = {
    keys: async () => [...data.keys()].map(url => ({ url })),
    match: async url => data.get(url)?.clone(),
    put: async (url, response) => { data.set(url, response.clone()); },
  };
  const options = {
    total, name: 'test', url: n => `https://library.test/page/${n}?v=1`,
    storage: { open: async () => cache }, onProgress: state => states.push(state),
    fetcher: async (url, { signal }) => {
      calls.push(url);
      maximum = Math.max(maximum, ++concurrent);
      try {
        await new Promise(resolve => setTimeout(resolve, 5));
        signal.throwIfAborted();
        return new Response(`%PDF-1.7 ${url}`);
      } finally { concurrent--; }
    },
  };
  return { data, calls, states, cache, options, maximum: () => maximum };
}

test('downloads every page with bounded concurrency and reads an arbitrary page without network', async () => {
  const f = fixture(40);
  const loader = new BookPreloader(f.options);
  await loader.start();
  assert.equal(f.maximum(), 2);
  assert.equal(f.data.size, 40);
  assert.equal(f.states.at(-1).complete, true);
  const before = f.calls.length;
  const page = await loader.bytes(35);
  assert.match(new TextDecoder().decode(page), /page\/35/);
  // PDF.js transfers the input buffer; disk data remains intact.
  structuredClone(page.buffer, { transfer: [page.buffer] });
  assert.match(new TextDecoder().decode(await loader.bytes(35)), /page\/35/);
  assert.equal(f.calls.length, before);
});

test('reopening resumes missing pages and never repeats saved downloads', async () => {
  const f = fixture();
  const first = new BookPreloader(f.options);
  await first.bytes(9);
  await first.bytes(12);
  const second = new BookPreloader(f.options);
  await second.ready;
  assert.equal(second.saved.size, 2);
  await second.start();
  assert.equal(f.calls.length, 12);
  assert.equal(new Set(f.calls).size, 12);
});

test('disk quota failure never reports completion and foreground reading still works', async () => {
  const f = fixture();
  f.cache.put = async () => { throw new DOMException('full', 'QuotaExceededError'); };
  const loader = new BookPreloader(f.options);
  await loader.start();
  assert.equal(f.states.at(-1).complete, false);
  assert.match(f.states.at(-1).problem, /espacio/);
  assert.match(new TextDecoder().decode(await loader.bytes(10)), /page\/10/);
});

test('failed or invalid responses are not counted; resume retries only failures', async () => {
  const f = fixture(3);
  const fetcher = f.options.fetcher;
  let fail = true;
  f.options.fetcher = (url, options) => fail && url.includes('/2?')
    ? Promise.resolve(new Response('not a PDF')) : fetcher(url, options);
  const loader = new BookPreloader(f.options);
  await loader.start();
  assert.equal(loader.saved.size, 2);
  assert.equal(loader.paused, true);
  assert.equal(f.states.at(-1).complete, false);
  fail = false;
  loader.toggle();
  while (loader.running || loader.saved.size < 3) await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(f.states.at(-1).complete, true);
  assert.equal(f.calls.filter(url => url.includes('/1?')).length, 1);
});

test('cancelled navigation aborts its transfer and a subsequent request can retry', async () => {
  const f = fixture();
  const loader = new BookPreloader(f.options);
  await loader.ready;
  const controller = new AbortController();
  const cancelled = loader.bytes(10, controller.signal);
  await new Promise(resolve => setTimeout(resolve, 1));
  controller.abort();
  await assert.rejects(cancelled, { name: 'AbortError' });
  assert.match(new TextDecoder().decode(await loader.bytes(10)), /page\/10/);
});

test('without persistent storage, the reader still opens individual pages', async () => {
  const f = fixture();
  f.options.storage = null;
  const loader = new BookPreloader(f.options);
  await loader.start();
  assert.equal(f.calls.length, 0);
  assert.match(new TextDecoder().decode(await loader.bytes(1)), /page\/1/);
  assert.equal(f.states.at(-1).available, false);
  assert.equal(f.states.at(-1).complete, false);
});
