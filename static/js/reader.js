import * as pdfjsLib from '../pdfjs/pdf.mjs';

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
const worker = new pdfjsLib.PDFWorker();
let zoom = 1;
let zoomTimer;
let zoomPending = false;
let queue = [];
let layoutWidth = pagesElement.clientWidth;
pageInput.max = pdf.numPages;

function setStatus(message) { status.textContent = message; }

function placeholder(number) {
  const span = document.createElement('span');
  span.className = 'page-placeholder';
  span.textContent = `Página ${number}`;
  return span;
}

function updatePage(number) {
  activePage = number;
  pageInput.value = number;
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
  entry?.task.destroy().catch(() => {});
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
    const shell = document.getElementById(`page-${number}`);
    const canvas = shell.querySelector('canvas');
    pixels -= canvas ? canvas.width * canvas.height : 0;
    shell.replaceChildren(placeholder(number));
    rendered.delete(number);
  }
  for (const number of documents.keys()) {
    if (documents.size <= 8) break;
    if (number !== activePage && !rendering.has(number)) discardDocument(number);
  }
}

async function getPage(number) {
  let entry = documents.get(number);
  if (!entry) {
    const task = pdfjsLib.getDocument({
      url: root.dataset.pageUrlTemplate.replace('123456789', String(number)),
      worker,
      cMapUrl: root.dataset.cmapUrl,
      cMapPacked: true,
      standardFontDataUrl: root.dataset.fontUrl,
      disableRange: true,
    });
    entry = { task };
    entry.promise = task.promise.then(doc => doc.getPage(1)).then(page => (entry.page = page));
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
  if (zoomPending) return;
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
  const query = searchQuery.toLocaleLowerCase();
  const searchable = content.toLocaleLowerCase();
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
    const first = findTextPosition(nodes, index);
    const last = findTextPosition(nodes, index + query.length - 1);
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
    shell.replaceChildren(content);
    shell.dataset.generation = generation;
    restoreAnchor(anchor);
    rendered.delete(number);
    rendered.add(number);
    if (number === activePage) setStatus('');
    paintMatches(number);
    if (pendingMatchPage === number) {
      pendingMatchPage = null;
      shell.querySelector('.search-hit.is-current')?.scrollIntoView({ block: 'center', behavior: 'instant' });
    }
  } catch (error) {
    if (obsolete() || error.name === 'RenderingCancelledException') return;
    discardDocument(number);
    if (!shell.querySelector('canvas')) {
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
}

function updateActiveFromScroll() {
  if (!pdf) return;
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
  if (scrollScheduled) return;
  scrollScheduled = true;
  requestAnimationFrame(() => { scrollScheduled = false; updateActiveFromScroll(); });
}, { passive: true });

function scrollToPage(number, immediate = false) {
  if (!pdf) return;
  const clamped = Math.max(1, Math.min(pdf.numPages, Math.trunc(Number(number)) || 1));
  document.getElementById(`page-${clamped}`).scrollIntoView({ block: 'start', behavior: 'instant' });
  updatePage(clamped);
  requestPages();
}

function rerender(nextZoom = zoom, clientX, clientY) {
  const anchor = captureAnchor(clientX, clientY);
  const ratio = nextZoom / zoom;
  zoom = nextZoom;
  renderGeneration += 1;
  zoomPending = true;
  for (const job of rendering.values()) job.renderTask?.cancel();
  document.querySelectorAll('.pdf-page').forEach((shell, index) => {
    const natural = pageSizes.get(index + 1);
    const width = natural ? Math.min(Math.max(280, pagesElement.clientWidth - 28) / natural.width, 1.6) * zoom * natural.width : shell.getBoundingClientRect().width * ratio * pagesElement.clientWidth / layoutWidth;
    const height = natural ? width * natural.height / natural.width : shell.getBoundingClientRect().height * width / shell.getBoundingClientRect().width;
    shell.style.width = `${width}px`;
    shell.style.height = `${height}px`;
    const content = shell.querySelector('.pdf-page-content');
    if (content) content.style.transform = `scale(${width / parseFloat(content.style.width)})`;
    shell.querySelector('.search-highlights')?.remove();
  });
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
  scrollToPage(number, true);
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
pageInput.addEventListener('change', () => scrollToPage(pageInput.value, true));
zoomSelect.addEventListener('change', () => rerender(zoomSelect.value === 'fit' ? 1 : Number(zoomSelect.value)));
pagesElement.addEventListener('wheel', event => {
  if (!event.ctrlKey && !event.metaKey) return;
  event.preventDefault();
  const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? pagesElement.clientHeight : 1);
  const value = Math.round(Math.max(0.5, Math.min(3, zoom * Math.exp(-delta * 0.002))) * 100) / 100;
  if (value === zoom) return;
  zoomSelect.querySelector('[data-custom]')?.remove();
  if (![...zoomSelect.options].some(option => option.value === String(value))) {
    const option = new Option(`${Math.round(value * 100)}%`, String(value));
    option.dataset.custom = 'true';
    zoomSelect.add(option);
  }
  zoomSelect.value = String(value);
  rerender(value, event.clientX, event.clientY);
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
window.addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => rerender(), 180); });

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
