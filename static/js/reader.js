import * as pdfjsLib from '../pdfjs/pdf.mjs';
import { BookPreloader } from './book-preloader.js';
import { normalizeSearch } from './search-text.js';

const root = document.getElementById('reader');
const pagesElement = document.getElementById('pdf-pages');
const status = document.getElementById('reader-status');
const pageInput = document.getElementById('page-input');
const zoomSelect = document.getElementById('zoom-select');
const previous = document.getElementById('previous-page');
const next = document.getElementById('next-page');
const findToggle = document.getElementById('find-toggle');
const findbar = document.getElementById('reader-findbar');
const findInput = document.getElementById('find-input');
const findCount = document.getElementById('find-count');
const findPrevious = document.getElementById('find-previous');
const findNext = document.getElementById('find-next');
const findClose = document.getElementById('find-close');
pdfjsLib.GlobalWorkerOptions.workerSrc = root.dataset.workerUrl;

const pdf = { numPages: Number(root.dataset.pages) };
let activePage = 1;
let renderGeneration = 0;
let searchMatches = [];
let searchTotal = 0;
let selectedMatch = -1;
let pendingMatchPage = null;
let searchQuery = '';
let pendingQuery = null;
let searchBusy = false;
let searchTimer;
const rendering = new Map();
const rendered = new Set();
const documents = new Map();
const pageSizes = new Map();
const previews = new Map();
const previewing = new Map();
const worker = new pdfjsLib.PDFWorker();
let zoom = 1;
let zoomTimer;
let zoomPending = false;
let pinch = null;
let fastScrolling = false;
let scrollIdleTimer;
let lastScrollTop = pagesElement.scrollTop;
let lastScrollTime = performance.now();
let queue = [];
let layoutWidth = pagesElement.clientWidth;
pageInput.max = pdf.numPages;
const preloadLabel = document.getElementById('preload-label');
const preloadProgress = document.getElementById('preload-progress');
const preloadToggle = document.getElementById('preload-toggle');
let progressTimer;
let preloadState;
const preloader = new BookPreloader({
  total: pdf.numPages,
  name: `biblioteca-book-v1-${root.dataset.bookId}-${root.dataset.version}`,
  url: number => {
    const url = new URL(root.dataset.pageUrlTemplate.replace('123456789', String(number)), location.href);
    url.searchParams.set('v', root.dataset.version);
    return url.href;
  },
  busy: () => fastScrolling || zoomPending || rendering.size > 0,
  prepare: (number, response, cache) => prepareVisual(number, response, cache),
  onProgress: state => {
    preloadState = state;
    if (state.complete || state.problem || state.paused) {
      clearTimeout(progressTimer);
      progressTimer = null;
    }
    if (progressTimer) return;
    progressTimer = setTimeout(() => {
      progressTimer = null;
      const state = preloadState;
      preloadProgress.value = state.loaded;
      preloadLabel.textContent = state.complete ? `Libro completo preparado · ${state.total} páginas`
        : state.problem || (state.failed ? `${state.loaded}/${state.total} páginas · Algunas fallaron. Reanuda para reintentar.`
          : `${state.paused ? 'En pausa' : 'Preparando todas las páginas'} · ${state.loaded}/${state.total}`);
      preloadToggle.hidden = state.complete || !state.available;
      preloadToggle.textContent = state.paused ? 'Reanudar' : 'Pausar';
    }, state.complete || state.problem || state.paused ? 0 : 150);
  },
});
preloadToggle.addEventListener('click', () => preloader.toggle());
const preloadPanel = document.getElementById('preload-panel');
const preloadMinimize = document.getElementById('preload-minimize');
preloadMinimize.addEventListener('click', () => {
  const minimized = preloadPanel.classList.toggle('is-minimized');
  preloadMinimize.textContent = minimized ? 'Carga del libro' : '−';
  preloadMinimize.setAttribute('aria-expanded', String(!minimized));
  preloadMinimize.setAttribute('aria-label', minimized ? 'Mostrar preparación del libro' : 'Minimizar preparación del libro');
});
window.addEventListener('pagehide', () => preloader.stop());
window.addEventListener('pageshow', event => {
  if (event.persisted) { preloader.stopped = false; preloader.start(); }
});

function setStatus(message) { status.textContent = message; }

function placeholder(number) {
  const span = document.createElement('span');
  span.className = 'page-placeholder';
  span.textContent = `Página ${number}`;
  return span;
}

function updatePage(number) {
  if (number !== activePage) preloader.prioritize(number);
  activePage = number;
  // Reassigning an unchanged value resets selection while the user types a jump.
  if (pageInput.value !== String(number) && document.activeElement !== pageInput) pageInput.value = number;
  previous.disabled = number <= 1;
  next.disabled = number >= pdf.numPages;
  if (rendered.delete(number)) rendered.add(number);
  for (const [item, job] of rendering) {
    if (Math.abs(item - number) > 1) {
      job.cancelled = true;
      job.renderTask?.cancel();
      const entry = documents.get(item);
      if (entry && !entry.page) discardDocument(item);
    }
  }
}

function discardDocument(number) {
  const entry = documents.get(number);
  documents.delete(number);
  entry?.controller.abort();
  entry?.task?.destroy().catch(() => {});
}

function trimCache() {
  let pixels = 0;
  for (const number of rendered) {
    const canvas = document.getElementById(`page-${number}`).querySelector('canvas');
    pixels += canvas ? canvas.width * canvas.height : 0;
  }
  for (const number of rendered) {
    if (rendered.size <= 6 && pixels <= 24000000) break;
    if (number === activePage || rendering.has(number)) continue;
    // Never replace a visited page with an empty placeholder while it redraws.
    const preview = previews.get(number);
    if (!preview) continue;
    const shell = document.getElementById(`page-${number}`);
    const canvas = shell.querySelector('canvas');
    pixels -= canvas ? canvas.width * canvas.height : 0;
    shell.replaceChildren(preview.image);
    rendered.delete(number);
  }
  for (const number of documents.keys()) {
    if (documents.size <= 8) break;
    if (number !== activePage && !rendering.has(number)) discardDocument(number);
  }
}

function previewUrl(number) {
  return `${preloader.url(number)}&preview=2`;
}

function prepareVisual(number, response, cache, sourceCanvas = null) {
  if (previewing.has(number)) return previewing.get(number);
  const promise = (async () => {
    let cached = cache ? await cache.match(previewUrl(number)) : null;
    let natural;
    let blob;
    let task;
    try {
      if (cached) {
        natural = { width: Number(cached.headers.get('X-PDF-Width')), height: Number(cached.headers.get('X-PDF-Height')) };
        if (!(natural.width > 0 && natural.height > 0)) cached = null;
      }
      if (cached) {
        blob = await cached.blob();
      } else {
        let canvas = sourceCanvas;
        natural = pageSizes.get(number);
        if (!canvas) {
          const data = new Uint8Array(await response.arrayBuffer());
          task = pdfjsLib.getDocument({ data, worker,
            cMapUrl: root.dataset.cmapUrl, cMapPacked: true,
            standardFontDataUrl: root.dataset.fontUrl });
          const pageDocument = await task.promise;
          const page = await pageDocument.getPage(1);
          natural = page.getViewport({ scale: 1 });
          const viewport = page.getViewport({ scale: Math.min(640 / natural.width, 880 / natural.height) });
          canvas = document.createElement('canvas');
          canvas.width = Math.ceil(viewport.width);
          canvas.height = Math.ceil(viewport.height);
          await page.render({ canvas, canvasContext: canvas.getContext('2d', { alpha: false }), viewport }).promise;
        }
        const small = document.createElement('canvas');
        const scale = Math.min(1, 640 / canvas.width, 880 / canvas.height);
        small.width = Math.max(1, Math.round(canvas.width * scale));
        small.height = Math.max(1, Math.round(canvas.height * scale));
        small.getContext('2d', { alpha: false }).drawImage(canvas, 0, 0, small.width, small.height);
        blob = await new Promise(resolve => small.toBlob(resolve, 'image/jpeg', 0.85));
        if (!blob) throw new Error('No se pudo preparar la vista previa');
        if (cache) await cache.put(previewUrl(number), new Response(blob, { headers: {
          'Content-Type': 'image/jpeg', 'X-PDF-Width': String(natural.width), 'X-PDF-Height': String(natural.height),
        } }));
      }
      if (previews.has(number)) return;
      const url = URL.createObjectURL(blob);
      const image = new Image();
      image.className = 'pdf-page-preview';
      image.alt = '';
      image.setAttribute('aria-hidden', 'true');
      image.src = url;
      try { await image.decode(); } catch (error) { URL.revokeObjectURL(url); throw error; }
      // Do not change page geometry underneath an active two-finger gesture.
      while (pinch) await pinch.finished;
      const anchor = captureAnchor();
      const shell = document.getElementById(`page-${number}`);
      pageSizes.set(number, natural);
      const width = Math.min(Math.max(280, pagesElement.clientWidth - 28) / natural.width, 1.6) * zoom * natural.width;
      shell.style.width = `${width}px`;
      shell.style.height = `${width * natural.height / natural.width}px`;
      shell.querySelector('.page-placeholder')?.remove();
      shell.prepend(image);
      previews.set(number, { image, url });
      restoreAnchor(anchor);
      trimCache();
    } finally {
      await task?.destroy().catch(() => {});
    }
  })();
  previewing.set(number, promise);
  promise.finally(() => previewing.delete(number)).catch(() => {});
  return promise;
}

function capturePreview(number, canvas) {
  if (previews.has(number)) return;
  prepareVisual(number, null, preloader.cache, canvas).catch(() => {});
}
async function getPage(number) {
  let entry = documents.get(number);
  if (!entry) {
    entry = { controller: new AbortController() };
    entry.promise = (async () => {
      const data = await preloader.bytes(number, entry.controller.signal);
      entry.controller.signal.throwIfAborted();
      entry.task = pdfjsLib.getDocument({
        data, worker,
        cMapUrl: root.dataset.cmapUrl,
        cMapPacked: true,
        standardFontDataUrl: root.dataset.fontUrl,
      });
      const doc = await entry.task.promise;
      return (entry.page = await doc.getPage(1));
    })();
    documents.set(number, entry);
  } else {
    documents.delete(number);
    documents.set(number, entry);
  }
  return entry.promise;
}

function viewportFor(page) {
  const natural = page.getViewport({ scale: 1 });
  return page.getViewport({ scale: Math.min(Math.max(280, pagesElement.clientWidth - 28) / natural.width, 1.6) * zoom });
}

// Only two jobs run at once. A jump replaces the queue with its destination.
function requestPages() {
  queue = [activePage, activePage + 1, activePage - 1].filter(number => number >= 1 && number <= pdf.numPages);
  pumpQueue();
}

function pumpQueue() {
  if (zoomPending || fastScrolling) return;
  // A scroll event must not let prefetch overtake the selected page.
  if (rendering.has(activePage) && !rendering.get(activePage).cancelled) return;
  while (rendering.size < 2 && queue.length) {
    const number = queue.shift();
    const shell = document.getElementById(`page-${number}`);
    if (rendering.has(number) || (rendered.has(number) && Number(shell.dataset.generation) === renderGeneration)) continue;
    renderPage(number);
    // Finish the destination before starting speculative work.
    if (number === activePage) break;
  }
}

function findTextPosition(nodes, offset) {
  let low = 0;
  let high = nodes.length - 1;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (nodes[middle].end <= offset) low = middle + 1;
    else high = middle;
  }
  return { node: nodes[low].node, offset: offset - nodes[low].start };
}

function paintMatches(number) {
  const shell = document.getElementById(`page-${number}`);
  shell.querySelector('.search-highlights')?.remove();
  if (!searchQuery || !searchMatches.includes(number)) return;
  const layer = shell.querySelector('.textLayer');
  if (!layer) return;
  const walker = document.createTreeWalker(layer, NodeFilter.SHOW_TEXT);
  const nodes = [];
  let content = '';
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (!node.length) continue;
    nodes.push({ node, start: content.length, end: content.length + node.length });
    content += node.textContent;
  }
  if (!nodes.length) return;
  const query = normalizeSearch(searchQuery).value;
  if (!query) return;
  const normalized = normalizeSearch(content);
  const searchable = normalized.value;
  const overlay = document.createElement('div');
  overlay.className = 'search-highlights';
  overlay.setAttribute('aria-hidden', 'true');
  const shellRect = shell.getBoundingClientRect();
  let ordinal = 0;
  let selectedOrdinal = 0;
  for (let i = 0; i < selectedMatch; i++) {
    if (searchMatches[i] === number) selectedOrdinal++;
  }
  for (let start = 0; ordinal < 300;) {
    const index = searchable.indexOf(query, start);
    if (index === -1) break;
    const first = findTextPosition(nodes, normalized.starts[index]);
    const last = findTextPosition(nodes, normalized.ends[index + query.length - 1] - 1);
    const range = document.createRange();
    range.setStart(first.node, first.offset);
    range.setEnd(last.node, last.offset + 1);
    for (const rect of range.getClientRects()) {
      if (!rect.width || !rect.height) continue;
      const mark = document.createElement('span');
      mark.className = `search-hit${ordinal === selectedOrdinal && searchMatches[selectedMatch] === number ? ' is-current' : ''}`;
      mark.style.left = `${rect.left - shellRect.left}px`;
      mark.style.top = `${rect.top - shellRect.top}px`;
      mark.style.width = `${rect.width}px`;
      mark.style.height = `${rect.height}px`;
      overlay.append(mark);
    }
    ordinal++;
    start = index + query.length;
  }
  shell.append(overlay);
}

async function renderPage(number, generation = renderGeneration) {
  const shell = document.getElementById(`page-${number}`);
  const job = { cancelled: false };
  rendering.set(number, job);
  const obsolete = () => job.cancelled || generation !== renderGeneration;
  try {
    const page = await getPage(number);
    if (obsolete()) return;
    const viewport = viewportFor(page);
    pageSizes.set(number, page.getViewport({ scale: 1 }));
    // Cap backing-store memory even at 300% on high-DPI screens.
    const pixelRatio = Math.min(window.devicePixelRatio || 1, 2, Math.sqrt(6000000 / (viewport.width * viewport.height)));
    const content = document.createElement('div');
    content.className = 'pdf-page-content';
    content.style.width = `${viewport.width}px`;
    content.style.height = `${viewport.height}px`;
    content.style.setProperty('--total-scale-factor', String(viewport.scale));
    const canvas = document.createElement('canvas');
    canvas.width = Math.floor(viewport.width * pixelRatio);
    canvas.height = Math.floor(viewport.height * pixelRatio);
    canvas.style.width = `${viewport.width}px`;
    canvas.style.height = `${viewport.height}px`;
    const context = canvas.getContext('2d', { alpha: false });
    if (!context) throw new Error('El dispositivo no permite dibujar páginas PDF.');
    job.renderTask = page.render({ canvasContext: context, canvas, viewport, transform: [pixelRatio, 0, 0, pixelRatio, 0, 0] });
    await job.renderTask.promise;
    if (obsolete()) return;
    content.append(canvas);
    const textContent = await page.getTextContent();
    if (obsolete()) return;
    const textDiv = document.createElement('div');
    textDiv.className = 'textLayer';
    const textLayer = new pdfjsLib.TextLayer({ textContentSource: textContent, container: textDiv, viewport });
    textDiv.style.width = `${viewport.width}px`;
    textDiv.style.height = `${viewport.height}px`;
    content.append(textDiv);
    await textLayer.render();
    if (obsolete()) return;
    const anchor = captureAnchor();
    shell.style.width = `${viewport.width}px`;
    shell.style.height = `${viewport.height}px`;
    const preview = previews.get(number);
    shell.replaceChildren(...(preview ? [preview.image, content] : [content]));
    shell.dataset.generation = generation;
    restoreAnchor(anchor);
    rendered.delete(number);
    rendered.add(number);
    capturePreview(number, canvas);
    if (number === activePage) setStatus('');
    paintMatches(number);
    if (pendingMatchPage === number) {
      pendingMatchPage = null;
      shell.querySelector('.search-hit.is-current')?.scrollIntoView({ block: 'center', behavior: 'instant' });
    }
  } catch (error) {
    if (obsolete() || error.name === 'RenderingCancelledException') return;
    discardDocument(number);
    if (!shell.querySelector('canvas') && !previews.has(number)) {
      const retry = document.createElement('button');
      retry.className = 'pdf-error';
      retry.textContent = 'No se pudo cargar la página. Reintentar';
      retry.addEventListener('click', requestPages);
      shell.replaceChildren(retry);
    }
    console.error(error);
  } finally {
    rendering.delete(number);
    trimCache();
    if (obsolete() && Math.abs(activePage - number) <= 1) queue.unshift(number);
    pumpQueue();
    if (number === activePage && rendered.has(number)) preloader.start();
  }
}

// Keep the point under the cursor fixed while page dimensions change.
function captureAnchor(clientX, clientY) {
  const container = pagesElement.getBoundingClientRect();
  const x = clientX ?? container.left + pagesElement.clientWidth / 2;
  const y = clientY ?? container.top + 1;
  let shell = document.elementFromPoint(x, y)?.closest('.pdf-page');
  if (!shell) shell = document.getElementById(`page-${activePage}`);
  const rect = shell.getBoundingClientRect();
  return { shell, x, y, fx: (x - rect.left) / rect.width, fy: (y - rect.top) / rect.height };
}

function restoreAnchor(anchor) {
  const rect = anchor.shell.getBoundingClientRect();
  pagesElement.scrollBy({ left: rect.left + anchor.fx * rect.width - anchor.x, top: rect.top + anchor.fy * rect.height - anchor.y, behavior: 'instant' });
  lastScrollTop = pagesElement.scrollTop;
  lastScrollTime = performance.now();
}

function updateActiveFromScroll() {
  if (!pdf || pinch) return;
  const midpoint = pagesElement.getBoundingClientRect().top + pagesElement.clientHeight * 0.45;
  let low = 1;
  let high = pdf.numPages;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (document.getElementById(`page-${middle}`).getBoundingClientRect().bottom < midpoint) low = middle + 1;
    else high = middle;
  }
  updatePage(low);
  requestPages();
}

let scrollScheduled = false;
pagesElement.addEventListener('scroll', () => {
  if (pinch) return;
  const now = performance.now();
  const distance = Math.abs(pagesElement.scrollTop - lastScrollTop);
  const elapsed = Math.max(1, now - lastScrollTime);
  if (distance > pagesElement.clientHeight * 0.5 || distance / elapsed > pagesElement.clientHeight / 160) {
    fastScrolling = true;
    queue = [];
  }
  lastScrollTop = pagesElement.scrollTop;
  lastScrollTime = now;
  clearTimeout(scrollIdleTimer);
  scrollIdleTimer = setTimeout(() => {
    fastScrolling = false;
    updateActiveFromScroll();
  }, 140);
  if (scrollScheduled) return;
  scrollScheduled = true;
  requestAnimationFrame(() => { scrollScheduled = false; updateActiveFromScroll(); });
}, { passive: true });

function scrollToPage(number) {
  if (!pdf) return;
  const clamped = Math.max(1, Math.min(pdf.numPages, Math.trunc(Number(number)) || 1));
  pageInput.value = clamped;
  document.getElementById(`page-${clamped}`).scrollIntoView({ block: 'start', behavior: 'instant' });
  fastScrolling = false;
  lastScrollTop = pagesElement.scrollTop;
  lastScrollTime = performance.now();
  updatePage(clamped);
  requestPages();
}

function rerender(nextZoom = zoom, clientX, clientY, savedAnchor = null) {
  const anchor = savedAnchor || captureAnchor(clientX, clientY);
  const ratio = nextZoom / zoom;
  zoom = nextZoom;
  renderGeneration += 1;
  zoomPending = true;
  for (const job of rendering.values()) job.renderTask?.cancel();
  // Read geometry together before changing styles: large books may have 1000 shells.
  const layouts = [...document.querySelectorAll('.pdf-page')].map((shell, index) => {
    const natural = pageSizes.get(index + 1);
    const rect = shell.getBoundingClientRect();
    const width = natural ? Math.min(Math.max(280, pagesElement.clientWidth - 28) / natural.width, 1.6) * zoom * natural.width : rect.width * ratio * pagesElement.clientWidth / layoutWidth;
    const height = natural ? width * natural.height / natural.width : rect.height * width / rect.width;
    return { shell, width, height };
  });
  for (const { shell, width, height } of layouts) {
    shell.style.width = `${width}px`;
    shell.style.height = `${height}px`;
    const content = shell.querySelector('.pdf-page-content');
    if (content) content.style.transform = `scale(${width / parseFloat(content.style.width)})`;
    shell.querySelector('.search-highlights')?.remove();
  }
  layoutWidth = pagesElement.clientWidth;
  restoreAnchor(anchor);
  clearTimeout(zoomTimer);
  zoomTimer = setTimeout(() => { zoomPending = false; requestPages(); }, 140);
}

function updateFindCount(message = '') {
  findCount.textContent = message || (searchMatches.length ? `${selectedMatch + 1} / ${searchTotal}` : '0 resultados');
  findPrevious.disabled = findNext.disabled = !searchMatches.length;
}

function goToMatch(index) {
  if (!searchMatches.length) return;
  const oldPage = searchMatches[selectedMatch];
  selectedMatch = (index + searchMatches.length) % searchMatches.length;
  const number = searchMatches[selectedMatch];
  pendingMatchPage = rendered.has(number) ? null : number;
  updateFindCount();
  if (oldPage && oldPage !== number && rendered.has(oldPage)) paintMatches(oldPage);
  scrollToPage(number);
  if (rendered.has(number)) {
    paintMatches(number);
    document.getElementById(`page-${number}`).querySelector('.search-hit.is-current')?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }
}

async function processSearchQueue() {
  if (searchBusy) return;
  searchBusy = true;
  while (pendingQuery !== null) {
    const query = pendingQuery;
    pendingQuery = null;
    if (!query) continue;
    updateFindCount('Buscando…');
    try {
      const url = new URL(root.dataset.searchUrl, location.href);
      url.searchParams.set('q', query);
      let complete = false;
      while (!complete && pendingQuery === null && findInput.value.trim() === query) {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const result = await response.json();
        if (pendingQuery !== null || findInput.value.trim() !== query) break;
        if (searchQuery !== query) selectedMatch = -1;
        searchQuery = query;
        searchMatches = result.matches;
        searchTotal = result.total;
        complete = result.complete;
        setStatus('');
        for (const number of rendered) paintMatches(number);
        if (searchMatches.length && selectedMatch < 0) {
          const nextOnOrAfterPage = searchMatches.findIndex(number => number >= activePage);
          goToMatch(nextOnOrAfterPage === -1 ? 0 : nextOnOrAfterPage);
        }
        if (complete && !result.has_text) {
          updateFindCount('Sin texto');
          setStatus('Este PDF no contiene texto seleccionable. Necesita OCR para poder buscar.');
        } else {
          updateFindCount(complete ? '' : `${result.indexed_pages}/${result.pages} págs.`);
        }
        if (!complete) await new Promise(resolve => setTimeout(resolve, 250));
      }
    } catch (error) {
      if (pendingQuery !== null) continue;
      updateFindCount('Error');
      console.error(error);
    }
  }
  searchBusy = false;
}

function queueSearch() {
  const query = findInput.value.trim();
  clearTimeout(searchTimer);
  if (!query) {
    pendingQuery = '';
    searchQuery = '';
    searchMatches = [];
    searchTotal = 0;
    selectedMatch = -1;
    updateFindCount('');
    for (const number of rendered) paintMatches(number);
    setStatus('');
    return;
  }
  updateFindCount('Buscando…');
  searchTimer = setTimeout(() => { pendingQuery = query; processSearchQueue(); }, 350);
}

function showFind() {
  findbar.hidden = false;
  findToggle.setAttribute('aria-expanded', 'true');
  findInput.focus();
  findInput.select();
}

function hideFind() {
  findbar.hidden = true;
  findToggle.setAttribute('aria-expanded', 'false');
  findToggle.focus();
}

previous.addEventListener('click', () => scrollToPage(activePage - 1));
next.addEventListener('click', () => scrollToPage(activePage + 1));
pageInput.addEventListener('change', () => scrollToPage(pageInput.value));
pageInput.addEventListener('blur', () => { pageInput.value = activePage; });
zoomSelect.addEventListener('change', () => rerender(zoomSelect.value === 'fit' ? 1 : Number(zoomSelect.value)));
function updateZoomControl(value) {
  zoomSelect.querySelector('[data-custom]')?.remove();
  if (![...zoomSelect.options].some(option => option.value === String(value))) {
    const option = new Option(`${Math.round(value * 100)}%`, String(value));
    option.dataset.custom = 'true';
    zoomSelect.add(option);
  }
  zoomSelect.value = String(value);
}
function setBookZoom(value, x, y) {
  value = Math.round(Math.max(0.5, Math.min(3, value)) * 100) / 100;
  if (value === zoom) return;
  updateZoomControl(value);
  rerender(value, x, y);
}

function touchPair(touches) {
  const [a, b] = touches;
  return { distance: Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY),
    x: (a.clientX + b.clientX) / 2, y: (a.clientY + b.clientY) / 2 };
}
function beginPinch(pair) {
  if (pinch) finishPinch();
  clearTimeout(zoomTimer);
  clearTimeout(scrollIdleTimer);
  zoomPending = true;
  renderGeneration++;
  for (const job of rendering.values()) job.renderTask?.cancel();
  const bounds = pagesElement.getBoundingClientRect();
  const overlay = document.createElement('div');
  overlay.className = 'pdf-pinch-overlay';
  overlay.setAttribute('aria-hidden', 'true');
  Object.assign(overlay.style, { left: `${bounds.left}px`, top: `${bounds.top}px`,
    width: `${bounds.width}px`, height: `${bounds.height}px` });
  const surface = document.createElement('div');
  surface.className = 'pdf-pinch-surface';
  overlay.append(surface);
  // Snapshot only the nearby area that could enter view at the minimum zoom.
  // Never promote an entire 800-page book into one enormous GPU layer.
  const reach = bounds.height * zoom / 0.5 * 2;
  const snapshots = [];
  const collect = number => {
    const shell = document.getElementById(`page-${number}`);
    const rect = shell.getBoundingClientRect();
    if (rect.bottom < pair.y - reach || rect.top > pair.y + reach) return false;
    const source = shell.querySelector('canvas') || shell.querySelector('.pdf-page-preview');
    let copy;
    if (source?.tagName === 'CANVAS') {
      copy = document.createElement('canvas');
      copy.width = source.width;
      copy.height = source.height;
      copy.getContext('2d').drawImage(source, 0, 0);
    } else if (source) {
      copy = source.cloneNode();
    } else {
      copy = document.createElement('div');
      copy.textContent = `Página ${number}`;
    }
    copy.className = 'pdf-pinch-page';
    Object.assign(copy.style, { left: `${rect.left - bounds.left}px`, top: `${rect.top - bounds.top}px`,
      width: `${rect.width}px`, height: `${rect.height}px` });
    snapshots.push(copy);
    return true;
  };
  for (let number = activePage; number <= pdf.numPages && collect(number); number++);
  for (let number = activePage - 1; number >= 1 && collect(number); number--);
  surface.append(...snapshots);
  let release;
  pinch = { ...pair, zoom, value: zoom, latest: pair, bounds, overlay, surface,
    anchor: captureAnchor(pair.x, pair.y), frame: null,
    finished: new Promise(resolve => { release = resolve; }), release: () => release() };
  root.append(overlay);
}
function paintPinch() {
  if (!pinch) return;
  pinch.frame = null;
  const ratio = pinch.value / pinch.zoom;
  const x = pinch.latest.x - pinch.bounds.left - (pinch.x - pinch.bounds.left) * ratio;
  const y = pinch.latest.y - pinch.bounds.top - (pinch.y - pinch.bounds.top) * ratio;
  // One compositor transform per frame: no page sizing, PDF render or layout reads.
  pinch.surface.style.transform = `translate3d(${x}px,${y}px,0) scale(${ratio})`;
}
function finishPinch() {
  if (!pinch) return;
  const gesture = pinch;
  cancelAnimationFrame(gesture.frame);
  pinch = null;
  const value = Math.round(gesture.value * 100) / 100;
  updateZoomControl(value);
  rerender(value, undefined, undefined, { ...gesture.anchor, x: gesture.latest.x, y: gesture.latest.y });
  gesture.overlay.remove();
  gesture.release();
}
pagesElement.addEventListener('touchstart', event => {
  if (event.touches.length !== 2) { finishPinch(); return; }
  event.preventDefault();
  beginPinch(touchPair(event.touches));
}, { passive: false });
pagesElement.addEventListener('touchmove', event => {
  if (event.touches.length !== 2) return;
  event.preventDefault();
  const pair = touchPair(event.touches);
  if (!pinch) beginPinch(pair);
  pinch.latest = pair;
  if (pinch.distance > 0) pinch.value = Math.max(0.5, Math.min(3, pinch.zoom * pair.distance / pinch.distance));
  if (pinch.frame === null) pinch.frame = requestAnimationFrame(paintPinch);
}, { passive: false });
for (const event of ['touchend', 'touchcancel']) {
  pagesElement.addEventListener(event, finishPinch, { passive: true });
}
// Safari also emits gesture events; Touch Events above perform the PDF zoom.
for (const event of ['gesturestart', 'gesturechange']) {
  pagesElement.addEventListener(event, event => event.preventDefault(), { passive: false });
}
pagesElement.addEventListener('wheel', event => {
  if (document.activeElement === pageInput) pageInput.blur();
  if (!event.ctrlKey && !event.metaKey) return;
  event.preventDefault();
  const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? pagesElement.clientHeight : 1);
  setBookZoom(zoom * Math.exp(-delta * 0.002), event.clientX, event.clientY);
}, { passive: false });
findToggle.addEventListener('click', showFind);
findClose.addEventListener('click', hideFind);
findInput.addEventListener('input', queueSearch);
findInput.addEventListener('keydown', event => {
  if (event.key === 'Enter') {
    event.preventDefault();
    goToMatch(selectedMatch + (event.shiftKey ? -1 : 1));
  }
});
findPrevious.addEventListener('click', () => goToMatch(selectedMatch - 1));
findNext.addEventListener('click', () => goToMatch(selectedMatch + 1));
document.addEventListener('keydown', event => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'f') {
    event.preventDefault();
    showFind();
  } else if (event.key === 'Escape' && !findbar.hidden) {
    hideFind();
  }
});
let resizeTimer;
window.addEventListener('resize', () => { finishPinch(); clearTimeout(resizeTimer); resizeTimer = setTimeout(() => rerender(), 180); });

try {
  const fragment = document.createDocumentFragment();
  for (let number = 1; number <= pdf.numPages; number++) {
    const shell = document.createElement('section');
    shell.className = 'pdf-page';
    shell.id = `page-${number}`;
    shell.setAttribute('aria-label', `Página ${number}`);
    shell.append(placeholder(number));
    fragment.append(shell);
  }
  pagesElement.append(fragment);
  updatePage(1);
  requestPages();
} catch (error) {
  setStatus('No se pudo abrir el libro. Prueba descargar el PDF.');
  console.error(error);
}
