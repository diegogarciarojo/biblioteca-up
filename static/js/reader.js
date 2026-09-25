import * as pdfjsLib from '../pdfjs/pdf.mjs';

const root = document.getElementById('reader');
const pagesElement = document.getElementById('pdf-pages');
const status = document.getElementById('reader-status');
const pageInput = document.getElementById('page-input');
const total = document.getElementById('page-total');
const zoomSelect = document.getElementById('zoom-select');
const previous = document.getElementById('previous-page');
const next = document.getElementById('next-page');
pdfjsLib.GlobalWorkerOptions.workerSrc = root.dataset.workerUrl;

let pdf;
let activePage = 1;
let renderGeneration = 0;
let observer;
const rendering = new Set();
const rendered = new Set();

function setStatus(message) { status.textContent = message; }
function updatePage(number) {
  activePage = number;
  pageInput.value = number;
  previous.disabled = number <= 1;
  next.disabled = number >= pdf.numPages;
  for (const item of rendered) {
    if (Math.abs(item - number) > 4) {
      const page = document.getElementById(`page-${item}`);
      page.querySelector('canvas')?.remove();
      if (!page.querySelector('.page-placeholder')) page.insertAdjacentHTML('beforeend', `<span class="page-placeholder">Página ${item}</span>`);
      rendered.delete(item);
    }
  }
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
    shell.replaceChildren(canvas);
    shell.style.width = `${viewport.width}px`;
    shell.style.height = `${viewport.height}px`;
    rendered.add(number);
    if (number === 1) setStatus('');
  } catch (error) {
    shell.innerHTML = '<span class="pdf-error">No se pudo mostrar esta página. Puedes descargar el PDF desde arriba.</span>';
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

function scrollToPage(number) {
  if (!pdf) return;
  const clamped = Math.max(1, Math.min(pdf.numPages, Number(number) || 1));
  document.getElementById(`page-${clamped}`).scrollIntoView({ block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
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
    shell.innerHTML = `<span class="page-placeholder">Página ${index + 1}</span>`;
  });
  renderPage(activePage);
  for (let number = Math.max(1, activePage - 1); number <= Math.min(pdf.numPages, activePage + 1); number++) renderPage(number);
}

previous.addEventListener('click', () => scrollToPage(activePage - 1));
next.addEventListener('click', () => scrollToPage(activePage + 1));
pageInput.addEventListener('change', () => scrollToPage(pageInput.value));
zoomSelect.addEventListener('change', rerender);
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
    const placeholder = document.createElement('span');
    placeholder.className = 'page-placeholder';
    placeholder.textContent = `Página ${number}`;
    shell.append(placeholder);
    fragment.append(shell);
  }
  pagesElement.append(fragment);
  observer = new IntersectionObserver(entries => {
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
