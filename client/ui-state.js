(function initUiState(root, factory) {
  const uiState = factory();
  if (typeof module === 'object' && module.exports) module.exports = uiState;
  if (root) root.BabyGrowthUI = uiState;
}(typeof globalThis !== 'undefined' ? globalThis : this, function createUiState() {
  function createActionGate(pendingKeys = new Set()) {
    const active = new Map();
    return {
      pendingKeys,
      isBusy(key) {
        return active.has(key);
      },
      run(key, task) {
        if (active.has(key)) return active.get(key);
        pendingKeys.add(key);
        let promise;
        try {
          promise = Promise.resolve(task());
        } catch (error) {
          promise = Promise.reject(error);
        }
        promise = promise.finally(() => {
          active.delete(key);
          pendingKeys.delete(key);
        });
        active.set(key, promise);
        return promise;
      },
    };
  }

  function createToastStore(limit = 4) {
    let sequence = 0;
    const store = {
      items: [],
      remove(id) {
        const index = this.items.findIndex(item => item.id === id);
        if (index >= 0) this.items.splice(index, 1);
      },
      push(message, type = 'info', duration = 3600) {
        const item = { id: ++sequence, message: String(message || ''), type };
        this.items.push(item);
        if (this.items.length > Math.max(1, limit)) {
          this.items.splice(0, this.items.length - Math.max(1, limit));
        }
        if (duration > 0) setTimeout(() => this.remove(item.id), duration);
        return item;
      },
    };
    return store;
  }

  function createHistoryPager({ resource, request, limit = 50 }) {
    if (!resource) throw new TypeError('resource is required');
    if (typeof request !== 'function') throw new TypeError('request must be a function');
    const pageLimit = Math.min(100, Math.max(1, Number(limit) || 50));
    return {
      items: [],
      total: 0,
      limit: pageLimit,
      offset: 0,
      hasMore: false,
      loading: false,
      loadError: '',
      get page() {
        return Math.floor(this.offset / this.limit) + 1;
      },
      get pageCount() {
        return Math.max(1, Math.ceil(this.total / this.limit));
      },
      get hasPrevious() {
        return this.offset > 0;
      },
      async load(nextOffset = this.offset) {
        const safeOffset = Math.max(0, Number(nextOffset) || 0);
        this.loading = true;
        this.loadError = '';
        try {
          const page = await request(`/admin/history/${encodeURIComponent(resource)}?limit=${this.limit}&offset=${safeOffset}`);
          this.items = Array.isArray(page && page.items) ? page.items.slice() : [];
          this.total = Math.max(0, Number(page && page.total) || 0);
          this.offset = Math.max(0, Number(page && page.offset) || 0);
          this.hasMore = Boolean(page && page.hasMore);
          return page;
        } catch (error) {
          this.loadError = error && error.message ? error.message : '历史记录加载失败';
          throw error;
        } finally {
          this.loading = false;
        }
      },
      previous() {
        if (!this.hasPrevious || this.loading) return Promise.resolve(null);
        return this.load(Math.max(0, this.offset - this.limit));
      },
      next() {
        if (!this.hasMore || this.loading) return Promise.resolve(null);
        return this.load(this.offset + this.limit);
      },
      async refreshAfterMutation() {
        await this.load(this.offset);
        if (!this.items.length && this.offset > 0) {
          const lastOffset = Math.floor(Math.max(0, this.total - 1) / this.limit) * this.limit;
          return this.load(lastOffset);
        }
        return this.items;
      },
    };
  }

  function startupErrorMessage(error) {
    if (!error) return '加载失败，请稍后重试';
    if (error.name === 'AbortError') return '请求超时，请稍后重试';
    if (error instanceof TypeError) return '无法连接服务器，请检查网络或服务状态';
    return error.message || '加载失败，请稍后重试';
  }

  return { createActionGate, createHistoryPager, createToastStore, startupErrorMessage };
}));
