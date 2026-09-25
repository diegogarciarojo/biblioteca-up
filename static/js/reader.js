import * as pdfjsLib from '../pdfjs/pdf.mjs';

const root = document.getElementById('reader');
const pagesElement = document.getElementById('pdf-pages');
const status = document.getElementById('reader-status');
const pageInput = document.getElementById('page-input');
const total = document.getElementById('page-total');
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

let pdf;
let activePage = 1;
let renderGeneration = 0;
let searchMatches = [];
let searchTotal = 0;
let selectedMatch = -1;
let searchQuery = '';
let pendingQuery = null;
let searchBusy = false;
let searchTimer;
const rendering = new Set();
const rendered = new Set();

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
  for (const item of rendered) {
    if (Math.abs(item - number) > 4) {
      document.getElementById(`page-${item}`).replaceChildren(placeholder(item));
      rendered.delete(item);
    }
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
  if (!pdf || rendering.has(number) || rendered.has(number)) return;
  rendering.add(number);
  const shell = document.getElementById(`page-${number}`);
  try {
    const page = await pdf.getPage(number);
    if (generation !== renderGeneration) return;
    const natural = page.getViewport({ scale: 1 });
    const available = Math.max(280, pagesElement.clientWidth - 28);
    const base = Math.min(available / natural.width, 1.6);
    const multiplier = zoomSelect.value === 'fit' ? 1 : Number(zoomSelect.value);
    const viewport = page.getViewport({ scale: base * multiplier });
    const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
    const canvas = document.createElement('canvas');
    canvas.width = Math.floor(viewport.width * pixelRatio);
    canvas.height = Math.floor(viewport.height * pixelRatio);
    canvas.style.width = `${viewport.width}px`;
    canvas.style.height = `${viewport.height}px`;
    const context = canvas.getContext('2d', { alpha: false });
    if (!context) throw new Error('El dispositivo no permite dibujar páginas PDF.');
    await page.render({ canvasContext: context, canvas, viewport, transform: [pixelRatio, 0, 0, pixelRatio, 0, 0] }).promise;
    if (generation !== renderGeneration) return;
    shell.style.width = `${viewport.width}px`;
    shell.style.height = `${viewport.height}px`;
    shell.style.setProperty('--total-scale-factor', String(viewport.scale));
    shell.replaceChildren(canvas);
    if (number === 1) setStatus('');

    const textContent = await page.getTextContent();
    if (generation !== renderGeneration) return;
    const textDiv = document.createElement('div');
    textDiv.className = 'textLayer';
    const textLayer = new pdfjsLib.TextLayer({ textContentSource: textContent, container: textDiv, viewport });
    textDiv.style.width = `${viewport.width}px`;
    textDiv.style.height = `${viewport.height}px`;
    await textLayer.render();
    if (generation !== renderGeneration) return;
    shell.append(textDiv);
    rendered.add(number);
    paintMatches(number);
    if (searchMatches[selectedMatch] === number) {
      shell.querySelector('.search-hit.is-current')?.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  } catch (error) {
    shell.replaceChildren();
    const message = document.createElement('span');
    message.className = 'pdf-error';
    message.textContent = 'No se pudo mostrar esta página. Puedes descargar el PDF desde arriba.';
    shell.append(message);
    console.error(error);
  } finally {
    rendering.delete(number);
    if (generation !== renderGeneration && !rendered.has(number)) renderPage(number);
  }
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
}

let scrollScheduled = false;
pagesElement.addEventListener('scroll', () => {
  if (scrollScheduled) return;
  scrollScheduled = true;
  requestAnimationFrame(() => { scrollScheduled = false; updateActiveFromScroll(); });
}, { passive: true });

function scrollToPage(number, immediate = false) {
  if (!pdf) return;
  const clamped = Math.max(1, Math.min(pdf.numPages, Number(number) || 1));
  document.getElementById(`page-${clamped}`).scrollIntoView({ block: 'start', behavior: immediate || matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
  updatePage(clamped);
  renderPage(clamped);
}

function rerender() {
  if (!pdf) return;
  renderGeneration += 1;
  rendered.clear();
  document.querySelectorAll('.pdf-page').forEach((shell, index) => {
    shell.style.width = '';
    shell.style.height = '';
    shell.replaceChildren(placeholder(index + 1));
  });
  renderPage(activePage);
  for (let number = Math.max(1, activePage - 1); number <= Math.min(pdf.numPages, activePage + 1); number++) renderPage(number);
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
      const response = await fetch(url);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const result = await response.json();
      if (pendingQuery !== null || findInput.value.trim() !== query) continue;
      searchQuery = query;
      searchMatches = result.matches;
      searchTotal = result.total;
      selectedMatch = -1;
      setStatus('');
      for (const number of rendered) paintMatches(number);
      if (searchMatches.length) {
        const nextOnOrAfterPage = searchMatches.findIndex(number => number >= activePage);
        goToMatch(nextOnOrAfterPage === -1 ? 0 : nextOnOrAfterPage);
      } else if (!result.has_text) {
        updateFindCount('Sin texto');
        setStatus('Este PDF no contiene texto seleccionable. Necesita OCR para poder buscar.');
      } else {
        updateFindCount('0 resultados');
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
zoomSelect.addEventListener('change', rerender);
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
window.addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(rerender, 180); });

try {
  const loadingTask = pdfjsLib.getDocument({
    url: root.dataset.pdfUrl,
    cMapUrl: root.dataset.cmapUrl,
    cMapPacked: true,
    standardFontDataUrl: root.dataset.fontUrl,
    disableAutoFetch: true,
    disableStream: true,
    rangeChunkSize: 256 * 1024,
  });
  pdf = await loadingTask.promise;
  total.textContent = `/ ${pdf.numPages}`;
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
  const observer = new IntersectionObserver(entries => {
    const visible = entries.filter(entry => entry.isIntersecting).sort((a, b) => Math.abs(a.boundingClientRect.top - 80) - Math.abs(b.boundingClientRect.top - 80));
    for (const entry of visible) renderPage(Number(entry.target.id.slice(5)));
  }, { root: pagesElement, rootMargin: '450px 0px', threshold: 0.01 });
  document.querySelectorAll('.pdf-page').forEach(page => observer.observe(page));
  await renderPage(1);
  updatePage(1);
} catch (error) {
  setStatus('No se pudo abrir el libro. Prueba descargar el PDF.');
  console.error(error);
}
