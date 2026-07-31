(function initDefaults(root, factory) {
  const defaults = factory();
  if (typeof module === 'object' && module.exports) module.exports = defaults;
  if (root) root.BabyGrowthDefaults = defaults;
}(typeof globalThis !== 'undefined' ? globalThis : this, function createDefaults() {
  const DEFAULT_SETTINGS = {
    theme: { name: '甜心粉', primary: '#ec8aa0', primaryD: '#d75f7e', secondary: '#7fc6d0', accent: '#ffc178', bg: '#fff6f3' },
    deco: { enabled: true, opacity: 0.5, emoji: ['🍼', '🌸', '⭐', '🧸', '🎈', '☁️', '💕'] },
    modules: { timeline: true, gallery: true, growth: true, vaccine: true, daily: true, diary: true, messages: true, videos: true, about: true },
    home: { hero: true, countdown: true, onthisday: true, carousel: true, milestones: true, growth: true, videos: true, diary: true, recap: true, vaccine: true },
    feeding: { defaultAmount: 150, dailyTarget: 900 },
    ai: { enabled: false, apiKey: '', apiKeyConfigured: false, clearApiKey: false, baseUrl: 'https://api.openai.com/v1', model: 'gpt-4o-mini' },
    faviconUrl: '',
    photoFrame: 'polaroid',
  };

  function clone(value) {
    if (Array.isArray(value)) return value.map(clone);
    if (!value || typeof value !== 'object') return value;
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, clone(item)]));
  }

  function emptyDb() {
    return {
      baby: { name: '宝贝', gender: 'girl', birthday: '', avatar: '', bio: '', family: '' },
      settings: clone(DEFAULT_SETTINGS),
      milestones: [], albums: [], onThisDayPhotos: [], albumsCompact: false,
      growth: [], daily: [], dailyCompact: false, dailyTotal: 0,
      diary: [], diaryCompact: false, messages: [], videos: [], recaps: [],
      shares: [], vaccines: [], isAdmin: false,
      businessTime: { timeZone: '', now: '', today: '' },
    };
  }

  return { DEFAULT_SETTINGS, emptyDb };
}));
