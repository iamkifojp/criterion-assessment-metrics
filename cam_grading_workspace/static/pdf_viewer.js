/* PDF display controls. Local endpoints only; no external scripts required. */
class CAMPdfViewer {
  constructor(parent, file, omitted, onSave) {
    Object.assign(this, {file, onSave, pages: [], index: 0, grid: false});
    this.abort = new AbortController();
    this.root = document.createElement("div");
    this.root.className = "cam-pdf";
    this.root.innerHTML = `
      <div class="pdf-tools">
        <button type="button" data-act="prev" aria-label="Previous PDF page">←</button>
        <span class="pdf-position" aria-live="polite"></span>
        <button type="button" data-act="next" aria-label="Next PDF page">→</button>
        <button type="button" data-act="grid">Page thumbnails</button>
        <label>Zoom <select aria-label="PDF zoom"><option value="100">Fit width</option>
          <option value="75">75%</option><option value="125">125%</option>
          <option value="150">150%</option><option value="200">200%</option></select></label>
        <label>Omit pages <input class="pdf-omit" aria-label="PDF pages to omit" placeholder="e.g. 1-9, 12"></label>
        <button type="button" data-act="apply">Apply to assignment</button>
        <span class="pdf-note">Original page numbers · PDFs only</span>
      </div><div class="pdf-message" role="status"></div><div class="pdf-pages"></div>`;
    parent.appendChild(this.root);
    this.body = this.root.querySelector(".pdf-pages");
    this.message = this.root.querySelector(".pdf-message");
    this.input = this.root.querySelector(".pdf-omit");
    this.input.value = omitted || "";
    this.zoom = this.root.querySelector("select");
    this.zoom.addEventListener("change", () => this.render());
    this.root.querySelector('[data-act="prev"]').onclick = () => this.go(-1);
    this.root.querySelector('[data-act="next"]').onclick = () => this.go(1);
    this.root.querySelector('[data-act="grid"]').onclick = () => {
      this.grid = !this.grid;
      this.render();
    };
    this.root.querySelector('[data-act="apply"]').onclick = async () => {
      const button = this.root.querySelector('[data-act="apply"]');
      button.disabled = true;
      try {
        const omitted = await this.onSave(this.input.value);
        if (this.abort.signal.aborted) return;
        this.input.value = omitted;
        await this.load();
      } catch (error) {
        if (!this.abort.signal.aborted) this.message.textContent = error.message;
      } finally { button.disabled = false; }
    };
    this.load();
  }

  async load() {
    this.message.textContent = "Loading PDF pages…";
    this.pages = [];
    this.body.replaceChildren();
    try {
      const response = await fetch(`/api/pdf/${encodeURIComponent(this.file.id)}/pages`,
                                   {signal: this.abort.signal});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not open this PDF.");
      if (this.abort.signal.aborted) return;
      this.pages = data.pages;
      this.total = data.page_count;
      this.index = 0;
      this.message.textContent = this.pages.length
        ? `${this.pages.length} of ${this.total} pages shown. Omitted pages stay in the original file.`
        : "All pages in this PDF are omitted. Clear or shorten the page range to see them.";
      this.render();
    } catch (error) {
      if (!this.abort.signal.aborted) this.message.textContent = error.message;
    }
  }

  go(offset) {
    this.index = Math.max(0, Math.min(this.pages.length - 1, this.index + offset));
    this.grid = false;
    this.render();
  }

  render() {
    this.body.replaceChildren();
    this.body.classList.toggle("pdf-grid", this.grid);
    this.root.querySelector('[data-act="grid"]').textContent = this.grid ? "Single page" : "Page thumbnails";
    this.root.querySelector('[data-act="grid"]').setAttribute("aria-pressed", String(this.grid));
    this.root.querySelector('[data-act="prev"]').disabled = !this.pages.length || this.index === 0;
    this.root.querySelector('[data-act="next"]').disabled = !this.pages.length || this.index >= this.pages.length - 1;
    this.root.querySelector(".pdf-position").textContent = this.pages.length
      ? `Page ${this.pages[this.index]} / ${this.total}` : "No visible pages";
    this.zoom.disabled = this.grid;
    const shown = this.grid ? this.pages : this.pages.slice(this.index, this.index + 1);
    shown.forEach(page => {
      const tile = document.createElement(this.grid ? "button" : "div");
      tile.className = "pdf-page";
      if (this.grid) {
        tile.type = "button";
        tile.setAttribute("aria-label", `Open page ${page}`);
        tile.onclick = () => { this.index = this.pages.indexOf(page); this.grid = false; this.render(); };
      } else { tile.style.width = this.zoom.value + "%"; }
      const img = document.createElement("img");
      img.alt = `Page ${page}`;
      img.loading = "lazy";
      img.src = `/api/pdf/${encodeURIComponent(this.file.id)}/pages/${page}?width=${this.grid ? 320 : 1800}`;
      img.onerror = () => { img.alt = `Page ${page} could not load. Reopen the PDF to retry.`; };
      tile.appendChild(img);
      const caption = document.createElement("div");
      caption.textContent = `Page ${page}`;
      tile.appendChild(caption);
      this.body.appendChild(tile);
    });
    this.body.scrollTop = 0;
  }

  destroy() { this.abort.abort(); this.root.remove(); }
}
window.CAMPdfViewer = CAMPdfViewer;
