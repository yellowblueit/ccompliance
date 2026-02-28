'use strict';

/**
 * TableManager – Sortable columns, drag-reorder, column visibility with gear menu.
 *
 * Usage:
 *   const tm = new TableManager(document.querySelector('table'), {
 *     id: 'activities',
 *     columns: [
 *       { key: 'timestamp', label: 'Timestamp', type: 'date' },
 *       { key: 'type', label: 'Type' },
 *       { key: 'actions', label: 'Actions', sortable: false, align: 'end' },
 *     ],
 *     defaultSort: { key: 'timestamp', dir: 'desc' },
 *   });
 *
 *   // After dynamically rendering rows, call:
 *   tm.refresh();
 */
class TableManager {
  constructor(el, opts) {
    this.table = typeof el === 'string' ? document.querySelector(el) : el;
    if (!this.table || this.table.tagName !== 'TABLE') return;

    this.id = opts.id || 'table';
    this.storageKey = 'tm_' + this.id;
    this._dragKey = null;

    // Column state
    this.columns = (opts.columns || []).map(function(c, i) {
      return {
        key: c.key,
        label: c.label,
        type: c.type || 'string',
        sortable: c.sortable !== false,
        visible: true,
        order: i,
        align: c.align || '',
      };
    });
    this._defaults = JSON.parse(JSON.stringify(this.columns));

    // Sort state
    this.sortKey = opts.defaultSort ? opts.defaultSort.key : null;
    this.sortDir = opts.defaultSort ? (opts.defaultSort.dir || 'desc') : 'desc';
    this._defSortKey = this.sortKey;
    this._defSortDir = this.sortDir;

    // Load saved preferences (overrides defaults)
    this._loadPrefs();

    // Build UI
    this._buildHeader();
    this._buildGear();
    this.refresh();
  }

  /** Re-apply sort & visibility after dynamic row changes. */
  refresh() {
    this._applyVis();
    if (this.sortKey) this._sortDOM();
  }

  // ── Preferences ────────────────────────────────────────────

  _loadPrefs() {
    try {
      var s = JSON.parse(localStorage.getItem(this.storageKey));
      if (!s) return;
      var self = this;
      if (s.sk !== undefined) this.sortKey = s.sk;
      if (s.sd) this.sortDir = s.sd;
      if (s.v) this.columns.forEach(function(c) {
        if (s.v[c.key] !== undefined) c.visible = s.v[c.key];
      });
      if (Array.isArray(s.o) && s.o.length === self.columns.length) {
        var m = {};
        s.o.forEach(function(k, i) { m[k] = i; });
        self.columns.forEach(function(c) {
          if (m[c.key] !== undefined) c.order = m[c.key];
        });
      }
    } catch(e) {}
  }

  _savePrefs() {
    var v = {};
    this.columns.forEach(function(c) { v[c.key] = c.visible; });
    localStorage.setItem(this.storageKey, JSON.stringify({
      sk: this.sortKey,
      sd: this.sortDir,
      v: v,
      o: this._ord().map(function(c) { return c.key; }),
    }));
  }

  _ord() {
    return this.columns.slice().sort(function(a, b) { return a.order - b.order; });
  }

  _reset() {
    this.columns = JSON.parse(JSON.stringify(this._defaults));
    this.sortKey = this._defSortKey;
    this.sortDir = this._defSortDir;
    localStorage.removeItem(this.storageKey);
    this._rebuildAll();
  }

  // ── Header ─────────────────────────────────────────────────

  _buildHeader() {
    var self = this;
    var thead = this.table.querySelector('thead');
    if (!thead) { thead = document.createElement('thead'); this.table.prepend(thead); }

    var tr = document.createElement('tr');
    var ordered = this._ord();

    ordered.forEach(function(col) {
      var th = document.createElement('th');
      th.dataset.colKey = col.key;
      th.draggable = true;
      th.className = 'tm-th';
      if (col.align) th.classList.add('text-' + col.align);
      if (col.sortable) th.classList.add('tm-sortable');

      var lbl = document.createElement('span');
      lbl.textContent = col.label;
      th.appendChild(lbl);

      if (col.sortable) {
        var arrows = document.createElement('span');
        arrows.className = 'tm-arrows';
        arrows.innerHTML = '<span class="tm-up">&#9650;</span><span class="tm-dn">&#9660;</span>';
        th.appendChild(arrows);

        if (self.sortKey === col.key) {
          th.classList.add('tm-active');
          th.classList.add(self.sortDir === 'asc' ? 'tm-asc' : 'tm-desc');
        }

        th.addEventListener('click', function(e) {
          if (e.target.closest('.tm-gear-wrap')) return;
          self._onSort(col.key);
        });
      }

      // Drag events
      th.addEventListener('dragstart', function(e) {
        self._dragKey = col.key;
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', col.key);
        th.classList.add('tm-dragging');
      });
      th.addEventListener('dragover', function(e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
      });
      th.addEventListener('dragenter', function(e) {
        var t = e.target.closest('th.tm-th');
        if (t && t.dataset.colKey !== self._dragKey) t.classList.add('tm-drag-over');
      });
      th.addEventListener('dragleave', function(e) {
        var t = e.target.closest('th.tm-th');
        if (t) t.classList.remove('tm-drag-over');
      });
      th.addEventListener('drop', function(e) {
        e.preventDefault();
        var t = e.target.closest('th.tm-th');
        if (t) t.classList.remove('tm-drag-over');
        self._onDrop(col.key);
      });
      th.addEventListener('dragend', function() {
        self._dragKey = null;
        self.table.querySelectorAll('.tm-dragging,.tm-drag-over').forEach(function(el) {
          el.classList.remove('tm-dragging', 'tm-drag-over');
        });
      });

      tr.appendChild(th);
    });

    thead.innerHTML = '';
    thead.appendChild(tr);
  }

  // ── Gear Menu ──────────────────────────────────────────────

  _buildGear() {
    var self = this;
    if (this._gearEl) this._gearEl.remove();

    // Place gear in the card ancestor (which has position:relative from Bootstrap)
    var card = this.table.closest('.card');
    var container = card || this.table.parentElement;

    var wrap = document.createElement('div');
    wrap.className = 'tm-gear-wrap';

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'tm-gear-btn';
    btn.title = 'Column settings';
    btn.innerHTML = '<i class="bi bi-gear-fill"></i>';

    var menu = document.createElement('div');
    menu.className = 'tm-gear-menu';

    this._ord().forEach(function(col) {
      if (!col.label) return; // skip utility columns (e.g. checkbox)
      var item = document.createElement('label');
      item.className = 'tm-gear-item';
      var cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = col.visible;
      cb.addEventListener('change', function() {
        col.visible = cb.checked;
        self._applyVis();
        self._savePrefs();
      });
      item.appendChild(cb);
      item.appendChild(document.createTextNode(' ' + col.label));
      menu.appendChild(item);
    });

    var reset = document.createElement('div');
    reset.className = 'tm-gear-reset';
    reset.innerHTML = '<i class="bi bi-arrow-counterclockwise me-1"></i>Reset to defaults';
    reset.addEventListener('click', function() {
      self._reset();
      menu.classList.remove('show');
    });
    menu.appendChild(reset);

    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      menu.classList.toggle('show');
    });

    document.addEventListener('click', function(e) {
      if (!wrap.contains(e.target)) menu.classList.remove('show');
    });

    wrap.appendChild(btn);
    wrap.appendChild(menu);
    container.appendChild(wrap);
    this._gearEl = wrap;
  }

  // ── Sort ───────────────────────────────────────────────────

  _onSort(key) {
    var self = this;
    if (this.sortKey === key) {
      this.sortDir = this.sortDir === 'asc' ? 'desc' : 'asc';
    } else {
      this.sortKey = key;
      this.sortDir = 'desc';
    }

    this.table.querySelectorAll('thead th.tm-th').forEach(function(th) {
      th.classList.remove('tm-active', 'tm-asc', 'tm-desc');
      if (th.dataset.colKey === self.sortKey) {
        th.classList.add('tm-active', self.sortDir === 'asc' ? 'tm-asc' : 'tm-desc');
      }
    });

    this._sortDOM();
    this._savePrefs();
  }

  _colIdx(key) {
    var ths = this.table.querySelectorAll('thead th[data-col-key]');
    for (var i = 0; i < ths.length; i++) {
      if (ths[i].dataset.colKey === key) return i;
    }
    return -1;
  }

  _sortDOM() {
    var tbody = this.table.querySelector('tbody');
    if (!tbody) return;
    var idx = this._colIdx(this.sortKey);
    if (idx < 0) return;
    var col = null;
    for (var i = 0; i < this.columns.length; i++) {
      if (this.columns[i].key === this.sortKey) { col = this.columns[i]; break; }
    }
    if (!col) return;

    var numCols = this.columns.length;
    var dir = this.sortDir;
    var rows = Array.from(tbody.querySelectorAll('tr'));

    rows.sort(function(a, b) {
      // Skip special rows (colspan, loading spinners, empty states)
      if (a.children.length < numCols || b.children.length < numCols) return 0;
      var ca = a.children[idx], cb = b.children[idx];
      if (!ca || !cb) return 0;

      var va = ca.dataset.sort !== undefined ? ca.dataset.sort : ca.textContent.trim();
      var vb = cb.dataset.sort !== undefined ? cb.dataset.sort : cb.textContent.trim();

      var cmp = 0;
      if (col.type === 'date') {
        cmp = (new Date(va || 0)).getTime() - (new Date(vb || 0)).getTime();
      } else if (col.type === 'number') {
        cmp = (parseFloat(va) || 0) - (parseFloat(vb) || 0);
      } else {
        cmp = (va || '').localeCompare(vb || '', undefined, { sensitivity: 'base' });
      }

      return dir === 'asc' ? cmp : -cmp;
    });

    rows.forEach(function(r) { tbody.appendChild(r); });
  }

  // ── Visibility ─────────────────────────────────────────────

  _applyVis() {
    var self = this;
    this.columns.forEach(function(col) {
      if (!col.label) return; // utility columns always visible
      var idx = self._colIdx(col.key);
      if (idx < 0) return;
      var d = col.visible ? '' : 'none';
      var th = self.table.querySelector('thead th[data-col-key="' + col.key + '"]');
      if (th) th.style.display = d;
      self.table.querySelectorAll('tbody tr').forEach(function(row) {
        if (row.children[idx]) row.children[idx].style.display = d;
      });
    });
  }

  // ── Drag & Drop Reorder ────────────────────────────────────

  _onDrop(targetKey) {
    if (!this._dragKey || this._dragKey === targetKey) return;
    var src = null, tgt = null;
    for (var i = 0; i < this.columns.length; i++) {
      if (this.columns[i].key === this._dragKey) src = this.columns[i];
      if (this.columns[i].key === targetKey) tgt = this.columns[i];
    }
    if (!src || !tgt) return;

    var sO = src.order, tO = tgt.order;
    if (sO < tO) {
      this.columns.forEach(function(c) { if (c.order > sO && c.order <= tO) c.order--; });
    } else {
      this.columns.forEach(function(c) { if (c.order >= tO && c.order < sO) c.order++; });
    }
    src.order = tO;

    this._rebuildAll();
    this._savePrefs();
  }

  _rebuildAll() {
    // Capture old column key order from DOM
    var oldThs = Array.from(this.table.querySelectorAll('thead th[data-col-key]'));
    var oldKeys = oldThs.map(function(th) { return th.dataset.colKey; });
    var keyIdx = {};
    oldKeys.forEach(function(k, i) { keyIdx[k] = i; });

    var newOrder = this._ord().map(function(c) { return c.key; });

    // Reorder body cells to match new column order
    var tbody = this.table.querySelector('tbody');
    if (tbody) {
      tbody.querySelectorAll('tr').forEach(function(row) {
        if (row.children.length < oldKeys.length) return; // skip special rows
        var cells = Array.from(row.children);
        var reordered = newOrder.map(function(k) { return cells[keyIdx[k]]; }).filter(Boolean);
        while (row.firstChild) row.removeChild(row.firstChild);
        reordered.forEach(function(c) { row.appendChild(c); });
      });
    }

    // Rebuild header and gear
    this._buildHeader();
    this._buildGear();
    this._applyVis();
    if (this.sortKey) this._sortDOM();
  }
}
