(function initUploadUtils(root, factory) {
  const utils = factory();
  if (typeof module === 'object' && module.exports) module.exports = utils;
  if (root) root.BabyGrowthUploads = utils;
}(typeof globalThis !== 'undefined' ? globalThis : this, function createUploadUtils() {
  function detectFileKind(file, imageExtensions, videoExtensions) {
    const extension = ((file.name || '').split('.').pop() || '').toLowerCase();
    const contentType = (file.type || '').toLowerCase();
    if (imageExtensions.includes(extension) || contentType.startsWith('image/')) return 'image';
    if (videoExtensions.includes(extension) || contentType.startsWith('video/')) return 'video';
    return null;
  }

  function validateUploadFile(file, limits, defaults, imageExtensions, videoExtensions) {
    const kind = detectFileKind(file, imageExtensions, videoExtensions);
    if (!kind) return { ok: false, msg: `不支持的文件类型：${file.name}（仅支持图片和视频）` };
    const configured = limits || defaults;
    const megabytes = kind === 'image' ? (configured.imageMB || 10) : (configured.videoMB || 200);
    if (file.size > megabytes * 1024 * 1024) {
      return { ok: false, msg: `文件过大：${file.name}（${kind === 'image' ? '图片' : '视频'}上限 ${megabytes}MB，当前 ${(file.size / 1048576).toFixed(1)}MB）` };
    }
    return { ok: true };
  }

  function makeUploadId(cryptoImpl) {
    const bytes = new Uint8Array(16);
    cryptoImpl.getRandomValues(bytes);
    return Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
  }

  function resumeStorageKey(file) {
    const source = [
      file && file.name || '',
      Number(file && file.size || 0),
      Number(file && file.lastModified || 0),
      file && file.type || '',
    ].join('\u0000');
    let first = 0x811c9dc5;
    let second = 0x9e3779b9;
    for (let index = 0; index < source.length; index += 1) {
      const code = source.charCodeAt(index);
      first = Math.imul(first ^ code, 0x01000193);
      second = Math.imul(second ^ (code + index), 0x85ebca6b);
    }
    const hex = value => (value >>> 0).toString(16).padStart(8, '0');
    return `bgt_upload_resume_${hex(first)}${hex(second)}`;
  }

  async function runPool(items, limit, worker) {
    let next = 0;
    let failed = null;
    async function run() {
      while (next < items.length) {
        if (failed) return;
        const index = next++;
        try { await worker(items[index], index); }
        catch (error) { failed = failed || error; return; }
      }
    }
    const concurrency = Math.max(1, Math.min(limit, items.length));
    await Promise.all(Array.from({ length: concurrency }, run));
    if (failed) throw failed;
  }

  return { detectFileKind, makeUploadId, resumeStorageKey, runPool, validateUploadFile };
}));
