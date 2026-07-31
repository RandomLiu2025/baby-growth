(function initComponents(root, factory) {
  const components = factory();
  if (typeof module === 'object' && module.exports) module.exports = components;
  if (root) root.BabyGrowthComponents = components;
}(typeof globalThis !== 'undefined' ? globalThis : this, function createComponents() {
  function thumbUrl(url) {
    if (typeof url === 'string' && url.startsWith('/uploads/') && /\.(jpe?g|png|webp)(\?|#|$)/i.test(url)) {
      const index = url.lastIndexOf('.');
      return `${url.slice(0, index)}_thumb${url.slice(index)}`;
    }
    return url;
  }

  function createMediaThumb(isVideo) {
    return {
      props: ['url'],
      setup(props) {
        const onErr = event => {
          const full = event.target.getAttribute('data-full');
          if (full && event.target.getAttribute('src') !== full) event.target.src = full;
        };
        return { props, isVideo, thumbUrl, onErr };
      },
      template: `
        <div class="mthumb">
          <div v-if="isVideo(props.url)" class="mediafill video-placeholder" aria-hidden="true"><span class="video-placeholder-icon">🎬</span></div>
          <img v-else class="mediafill" :src="thumbUrl(props.url)" :data-full="props.url" @error="onErr" loading="lazy" decoding="async" alt=""/>
          <span v-if="isVideo(props.url)" class="playbadge" aria-hidden="true">▶</span>
        </div>`,
    };
  }

  const Toggle = {
    props: ['modelValue', 'label'],
    emits: ['update:modelValue'],
    template: `<button type="button" class="sw" :class="{on:modelValue}" role="switch" :aria-checked="modelValue?'true':'false'" :aria-label="label||'切换设置'" @click="$emit('update:modelValue',!modelValue)"><i aria-hidden="true"></i></button>`,
  };

  return { createMediaThumb, thumbUrl, Toggle };
}));
