// Keep the entire book on disk, while PDF.js only holds a few parsed pages in RAM.
export class BookPreloader {
  constructor({ total, url, name, onProgress = () => {}, busy = () => false, prepare = null,
    storage = globalThis.caches, fetcher = globalThis.fetch.bind(globalThis) }) {
    Object.assign(this, { total, url, name, onProgress, busy, prepare, storage, fetcher });
    this.saved = new Set();
    this.prepared = new Set();
    this.pending = new Map();
    this.failures = new Set();
    this.paused = false;
    this.stopped = false;
    this.problem = '';
    this.cache = null;
    this.ready = this.open();
  }

  async open() {
    try {
      if (!this.storage) throw new Error('No cache storage');
      this.cache = await this.storage.open(this.name);
      const keys = new Set((await this.cache.keys()).map(request => request.url));
      for (let number = 1; number <= this.total; number++) {
        if (keys.has(this.url(number))) this.saved.add(number);
      }
    } catch {
      this.problem = 'Este navegador no permite guardar el libro completo. La lectura por página sigue disponible.';
    }
    this.report();
  }

  report() {
    const loaded = this.prepare ? [...this.prepared].filter(number => this.saved.has(number)).length : this.saved.size;
    this.onProgress({ loaded, downloaded: this.saved.size, total: this.total,
      complete: loaded === this.total, paused: this.paused,
      available: !!this.cache, problem: this.problem, failed: this.failures.size });
  }

  async cached(number) {
    if (!this.cache) return null;
    try {
      const response = await this.cache.match(this.url(number));
      if (response) {
        // Another tab may have finished downloading this page since open().
        this.saved.add(number);
        return response;
      }
      // Browsers can evict data to recover disk space.
      if (this.saved.delete(number)) this.report();
    } catch {
      this.saved.delete(number);
    }
    return null;
  }

  async download(number, foreground) {
    let job = this.pending.get(number);
    if (job?.controller.signal.aborted) job = null;
    if (job) {
      if (foreground) job.foreground = true;
      return job.promise;
    }
    job = { controller: new AbortController(), foreground };
    this.pending.set(number, job);
    job.promise = (async () => {
      let timedOut = false;
      const timeout = setTimeout(() => { timedOut = true; job.controller.abort(); }, 45000);
      try {
        const response = await this.fetcher(this.url(number), {
          signal: job.controller.signal, priority: foreground ? 'high' : 'low',
        });
        if (response.status !== 200) throw new Error(`HTTP ${response.status}`);
        const bytes = await response.arrayBuffer();
        const header = new Uint8Array(bytes, 0, Math.min(5, bytes.byteLength));
        if (String.fromCharCode(...header) !== '%PDF-') throw new Error('Respuesta PDF inválida');
        const complete = new Response(bytes, { headers: { 'Content-Type': 'application/pdf' } });
        if (this.cache && !this.problem) {
          try {
            await this.cache.put(this.url(number), complete.clone());
            this.saved.add(number);
            this.failures.delete(number);
          } catch (error) {
            this.paused = true;
            this.problem = error.name === 'QuotaExceededError'
              ? 'No hay espacio suficiente para guardar todo el libro. La lectura por página sigue disponible.'
              : 'No se pudo guardar el libro completo en este navegador. La lectura por página sigue disponible.';
          }
          this.report();
        }
        return complete;
      } catch (error) {
        if (timedOut) throw new Error('Tiempo de descarga agotado');
        throw error;
      } finally {
        clearTimeout(timeout);
        if (this.pending.get(number) === job) this.pending.delete(number);
      }
    })();
    return job.promise;
  }

  async bytes(number, signal) {
    await this.ready;
    signal?.throwIfAborted();
    const stored = await this.cached(number);
    let onAbort;
    let response;
    try {
      const cancelled = new Promise((_, reject) => {
        onAbort = () => {
          this.pending.get(number)?.controller.abort();
          reject(signal.reason);
        };
        signal?.addEventListener('abort', onAbort, { once: true });
      });
      signal?.throwIfAborted();
      response = stored || await Promise.race([this.download(number, true), cancelled]);
    } finally {
      signal?.removeEventListener('abort', onAbort);
    }
    signal?.throwIfAborted();
    // Each PDF.js document receives its own buffer; workers transfer/detach it.
    return new Uint8Array(await response.clone().arrayBuffer());
  }

  prioritize(number) {
    for (const [page, job] of this.pending) {
      if (!job.foreground && page !== number) job.controller.abort();
    }
  }

  toggle() {
    this.paused = !this.paused;
    if (this.paused) {
      for (const job of this.pending.values()) if (!job.foreground) job.controller.abort();
    } else {
      this.failures.clear();
      if (this.cache) this.problem = '';
      this.start();
    }
    this.report();
  }

  async start() {
    await this.ready;
    if (this.running || !this.cache || this.stopped || this.problem) return;
    this.running = true;
    // Two sequential workers, rather than hundreds of simultaneous requests.
    const reserved = new Set();
    const work = async () => {
      while (!this.stopped && !this.problem) {
        if (this.paused || this.busy()) {
          await new Promise(resolve => setTimeout(resolve, 180));
          continue;
        }
        let number = 1;
        while (number <= this.total && ((this.saved.has(number) && (!this.prepare || this.prepared.has(number))) || reserved.has(number) || this.failures.has(number))) number++;
        if (number > this.total) break;
        reserved.add(number);
        try {
          const response = await this.cached(number) || await this.download(number, false);
          if (this.prepare && !this.prepared.has(number)) {
            await this.prepare(number, response.clone(), this.cache);
            this.prepared.add(number);
            this.report();
          }
        } catch (error) {
          if (error.name !== 'AbortError') this.failures.add(number);
        } finally {
          reserved.delete(number);
        }
      }
    };
    try {
      await Promise.all([work(), work()]);
    } finally {
      this.running = false;
      if (this.failures.size && !this.problem) this.paused = true;
      this.report();
    }
  }

  stop() {
    this.stopped = true;
    for (const job of this.pending.values()) job.controller.abort();
  }
}
