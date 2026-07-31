(function initCompat(root, factory) {
  const compat = factory();
  if (typeof module === 'object' && module.exports) module.exports = compat;
  if (root) root.BabyGrowthCompat = compat;
}(typeof globalThis !== 'undefined' ? globalThis : this, function createCompat() {
  const unsafeKeys = new Set(['__proto__', 'prototype', 'constructor']);

  function isPlainObject(value) {
    if (!value || Object.prototype.toString.call(value) !== '[object Object]') return false;
    const prototype = Object.getPrototypeOf(value);
    return prototype === Object.prototype || prototype === null;
  }

  function cloneData(value) {
    if (Array.isArray(value)) return value.map(cloneData);
    if (!isPlainObject(value)) return value;
    const cloned = {};
    Object.entries(value).forEach(([key, item]) => {
      if (!unsafeKeys.has(key)) cloned[key] = cloneData(item);
    });
    return cloned;
  }

  function mergeWithDefaults(defaultValue, incomingValue) {
    if (Array.isArray(defaultValue)) {
      return Array.isArray(incomingValue) ? cloneData(incomingValue) : cloneData(defaultValue);
    }
    if (isPlainObject(defaultValue)) {
      if (incomingValue !== undefined && !isPlainObject(incomingValue)) return cloneData(defaultValue);
      const merged = cloneData(defaultValue);
      Object.entries(incomingValue || {}).forEach(([key, item]) => {
        if (!unsafeKeys.has(key)) merged[key] = mergeWithDefaults(defaultValue[key], item);
      });
      return merged;
    }
    return incomingValue === undefined ? cloneData(defaultValue) : cloneData(incomingValue);
  }

  function normalizeBootstrap(payload, defaults) {
    return mergeWithDefaults(defaults, isPlainObject(payload) ? payload : {});
  }

  function sameId(left, right) {
    return left !== null && left !== undefined
      && right !== null && right !== undefined
      && String(left) === String(right);
  }

  function isVideoUrl(url) {
    return /\.(mp4|webm|ogg|ogv|mov|m4v)(\?|#|$)/i.test(url || '');
  }

  function albumPhotoCount(album) {
    if (!album) return 0;
    const count = Number(album.photoCount);
    if (Number.isFinite(count) && count >= 0) return count;
    return Array.isArray(album.photos) ? album.photos.length : 0;
  }

  function albumNeedsLoad(album) {
    return !album || album.photosLoaded === false;
  }

  function replaceCollection(target, incoming) {
    if (!Array.isArray(target)) throw new TypeError('target must be an array');
    const items = Array.isArray(incoming) ? cloneData(incoming) : [];
    target.splice(0, target.length, ...items);
    return target;
  }

  function diaryImageCount(diary) {
    if (!diary) return 0;
    const count = Number(diary.imageCount);
    if (Number.isFinite(count) && count >= 0) return count;
    return Array.isArray(diary.images) ? diary.images.length : 0;
  }

  function diaryNeedsLoad(diary) {
    return !diary || diary.detailLoaded === false;
  }

  return { albumNeedsLoad, albumPhotoCount, cloneData, diaryImageCount, diaryNeedsLoad, isVideoUrl, normalizeBootstrap, replaceCollection, sameId };
}));
