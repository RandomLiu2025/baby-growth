(function initApi(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.BabyGrowthAPI = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function createApiModule() {
  function errorMessage(detail, fallback) {
    if (typeof detail === 'string' && detail) return detail;
    if (Array.isArray(detail) && detail.length) {
      return detail.map(item => item && item.msg ? item.msg : String(item)).join('；');
    }
    return fallback;
  }

  function createApiClient({ storage, fetchImpl, onTokenChange, onUnauthorized, baseUrl = '/api' }) {
    const request = fetchImpl || ((...args) => fetch(...args));
    return {
      token: storage.getItem('bgt_token') || '',
      setToken(token) {
        this.token = token || '';
        if (this.token) storage.setItem('bgt_token', this.token);
        else storage.removeItem('bgt_token');
        if (onTokenChange) onTokenChange(Boolean(this.token));
      },
      async req(method, path, { json, form } = {}) {
        const headers = {};
        if (this.token) headers.Authorization = `Bearer ${this.token}`;
        const options = { method, headers };
        if (form) options.body = form;
        else if (json !== undefined) {
          headers['Content-Type'] = 'application/json';
          options.body = JSON.stringify(json);
        }
        const response = await request(baseUrl + path, options);
        if (response.status === 401) {
          this.setToken('');
          if (onUnauthorized) onUnauthorized();
          const error = new Error('未登录或登录已过期');
          error.status = 401;
          throw error;
        }
        if (!response.ok) {
          let data = null;
          try { data = await response.json(); } catch (error) {}
          const error = new Error(errorMessage(data && data.detail, `请求失败 ${response.status}`));
          error.status = response.status;
          throw error;
        }
        if (response.status === 204) return null;
        const contentType = response.headers.get('content-type') || '';
        return contentType.includes('json') ? response.json() : response.text();
      },
      get(path) { return this.req('GET', path); },
      post(path, json) { return this.req('POST', path, { json }); },
      put(path, json) { return this.req('PUT', path, { json }); },
      del(path) { return this.req('DELETE', path); },
      upload(form) { return this.req('POST', '/upload', { form }); },
    };
  }

  return { createApiClient, errorMessage };
}));
