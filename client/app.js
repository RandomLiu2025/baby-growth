/* 宝贝成长记 · 前端应用逻辑（Vue 3 全局构建，无需打包） */
const { createApp, reactive, computed, ref, watch, onMounted, onUnmounted, nextTick } = Vue;
const { albumNeedsLoad, albumPhotoCount, cloneData, diaryImageCount, diaryNeedsLoad, isVideoUrl, normalizeBootstrap, sameId } = window.BabyGrowthCompat;
const { createActionGate, createHistoryPager, createToastStore, startupErrorMessage } = window.BabyGrowthUI;
const { createApiClient } = window.BabyGrowthAPI;
const { DEFAULT_SETTINGS, emptyDb } = window.BabyGrowthDefaults;
const { detectFileKind, makeUploadId, resumeStorageKey, runPool, validateUploadFile } = window.BabyGrowthUploads;
const { createMediaThumb, Toggle } = window.BabyGrowthComponents;
const {
  addDays: addCalendarDays,
  addMonths: addCalendarMonths,
  addYears: addCalendarYears,
  ageText: calendarAgeText,
  calendarDaysBetween,
  compareDateValues,
  createBusinessClock,
  dateKey: businessDateKey,
  formatDate: formatBusinessDate,
  formatDateTime: formatBusinessDateTime,
  formatMonthDay: formatBusinessMonthDay,
  formatTime: formatBusinessTime,
  monthDay: businessMonthDay,
  yearOf: businessYearOf,
} = window.BabyGrowthTime;
/* 健壮存储：真实 localStorage/sessionStorage 优先；在无 allow-same-origin 的沙箱 iframe 中访问会抛 SecurityError，此时自动降级为内存存储（本会话有效） */
function makeStore(kind){
  let ok=true, backend=null; const mem={};
  try{ backend=window[kind]; const t='__probe__'; backend.setItem(t,'1'); backend.removeItem(t); }
  catch(e){ ok=false; backend=null; }
  return {
    get persistent(){return ok;},
    getItem(k){ if(ok){ try{ return backend.getItem(k); }catch(e){ ok=false; } } return (k in mem)?mem[k]:null; },
    setItem(k,v){ if(ok){ try{ backend.setItem(k,String(v)); return; }catch(e){ ok=false; } } mem[k]=String(v); },
    removeItem(k){ if(ok){ try{ backend.removeItem(k); return; }catch(e){ ok=false; } } delete mem[k]; }
  };
}
const LS = makeStore('localStorage');

/* ---------- helpers ---------- */
const uid = ()=>Math.random().toString(36).slice(2,9);
const pad = n=>String(n).padStart(2,'0');
const clockTick=ref(0);
let businessClock=createBusinessClock();
const iso = value=>businessDateKey(value,businessClock.timeZone);
const fmtDate = value=>formatBusinessDate(value,businessClock.timeZone);
const fmtMD = value=>formatBusinessMonthDay(value,businessClock.timeZone);
function todayStr(){clockTick.value;return businessClock.today();}
function ageText(birth,ref){return calendarAgeText(birth,ref===undefined?todayStr():iso(ref));}
function daysOld(birth,ref){const reference=ref===undefined?todayStr():iso(ref);return Math.max(0,calendarDaysBetween(birth,reference));}
function since(ts){clockTick.value;const value=new Date(ts).getTime();if(!Number.isFinite(value))return'—';const s=Math.max(0,(businessClock.now().getTime()-value)/1000);const h=Math.floor(s/3600),m=Math.floor(s%3600/60);return h?`${h}小时${m}分`:`${m}分钟`;}
function businessYear(){return businessYearOf(todayStr(),businessClock.timeZone);}
function vxDue(v){const birth=iso(state.db.baby.birthday);return birth?addCalendarMonths(birth,+v.plannedMonth||0):null;}
function vxInfo(v){const due=vxDue(v);const days=due?calendarDaysBetween(todayStr(),due):null;if(v.date)return{label:'已接种',cls:'ok',due,days};if(days!=null&&days<0)return{label:'逾期',cls:'due',due,days};if(days!=null&&days<=30)return{label:'即将到期',cls:'pend',due,days};return{label:'待接种',cls:'grey',due,days};}
function vxMonLabel(m){m=+m;if(m===0)return '出生时';if(m<12)return m+' 月龄';const y=Math.floor(m/12),mm=m%12;return mm?(y+'岁'+mm+'月'):(y+' 岁');}

/* ---------- store (API-backed) ---------- */
const state = reactive({ db: emptyDb(), session:{ loggedIn:false, role:'', username:'' }, ready:false, mobileMenu:false });
const startup = reactive({ loading:false, error:'' });
const toasts = reactive(createToastStore());
const pendingActions = reactive(new Set());
const actionGate = createActionGate(pendingActions);
function noticeType(message){const text=String(message||'');if(/取消/.test(text))return'info';if(/成功|已保存|已创建|已复制|已完成/.test(text))return'success';return'error';}
function notify(message,type=noticeType(message),duration=3600){return toasts.push(message,type,duration);}
const alert = message=>notify(message);
function runAction(key,task){return actionGate.run(key,task);}
function actionKey(prefix,payload){try{return prefix+':'+JSON.stringify(payload);}catch(e){return prefix;}}

const API = createApiClient({
  storage: LS,
  onTokenChange: loggedIn => { state.session.loggedIn=loggedIn; },
  onUnauthorized: () => { if(String(route.name).startsWith('admin'))go('home'); },
});
function makeAdminHistoryPager(resource){return reactive(createHistoryPager({resource,request:path=>API.get(path)}));}
function assignDb(d){ const normalized=normalizeBootstrap(d,emptyDb());businessClock=createBusinessClock(normalized.businessTime||{});Object.assign(state.db,normalized);state.session.loggedIn=!!normalized.user;state.session.role=(normalized.user&&normalized.user.role)||'';state.session.username=(normalized.user&&normalized.user.username)||''; }
async function refresh(){ if(_refreshPromise) return _refreshPromise; _refreshPromise=(async()=>{const d=await API.get('/bootstrap?compact=true');assignDb(d);applyTheme();})(); try{return await _refreshPromise;}finally{_refreshPromise=null;} }
async function loadBranding(){ try{ const b=await API.get('/branding'); if(b){ if(typeof b.faviconUrl==='string') state.db.settings.faviconUrl=b.faviconUrl; if(b.babyName) state.db.baby.name=b.babyName; applyFavicon(); } }catch(e){/* 忽略：未登录也不影响，使用默认 */} }
// 局部更新：CRUD 端点均返回完整对象（含 id），直接改本地对应数组，避免每次操作全量重拉 /bootstrap
// res 名与 state.db 的数组键一一对应（milestones/albums/growth/daily/diary/videos/vaccines）
function _localArr(res){ const a=state.db[res]; return Array.isArray(a)?a:null; }
function markAlbumLoaded(album){if(!album)return album;album.photoCount=albumPhotoCount(album);album.photosLoaded=true;return album;}
async function ensureAlbumLoaded(id){
  let current=state.db.albums.find(album=>sameId(album.id,id));
  if(!albumNeedsLoad(current))return current;
  const detail=markAlbumLoaded(await runAction('album:load:'+id,()=>API.get('/albums/'+encodeURIComponent(id))));
  current=state.db.albums.find(album=>sameId(album.id,id));
  if(current)Object.assign(current,detail);else state.db.albums.push(detail);
  state.db.albumsCompact=state.db.albums.some(albumNeedsLoad);
  return current||detail;
}
function markDiaryLoaded(diary){if(!diary)return diary;diary.imageCount=diaryImageCount(diary);diary.detailLoaded=true;return diary;}
async function ensureDiaryLoaded(id){
  let current=state.db.diary.find(diary=>sameId(diary.id,id));
  if(!diaryNeedsLoad(current))return current;
  const detail=markDiaryLoaded(await runAction('diary:load:'+id,()=>API.get('/diary/'+encodeURIComponent(id))));
  current=state.db.diary.find(diary=>sameId(diary.id,id));
  if(current)Object.assign(current,detail);else state.db.diary.push(detail);
  state.db.diaryCompact=state.db.diary.some(diaryNeedsLoad);
  return current||detail;
}
async function apiCreate(res,obj){return runAction(actionKey('create:'+res,obj),async()=>{let s=await API.post('/'+res,obj);if(res==='albums')s=markAlbumLoaded(s);if(res==='diary')s=markDiaryLoaded(s);const arr=_localArr(res);if(arr&&s&&s.id!=null){arr.push(s);if(res==='daily'&&state.db.dailyCompact)state.db.dailyTotal=(+state.db.dailyTotal||0)+1;}else await refresh();return s;});}
async function apiUpdate(res,id,obj){return runAction(actionKey('update:'+res+':'+id,obj),async()=>{let s=await API.put('/'+res+'/'+id,obj);if(res==='albums')s=markAlbumLoaded(s);if(res==='diary')s=markDiaryLoaded(s);const arr=_localArr(res);if(arr&&s&&s.id!=null){const i=arr.findIndex(x=>sameId(x.id,id));if(i>=0)arr.splice(i,1,s);else arr.push(s);}else await refresh();return s;});}
async function apiDelete(res,id){return runAction('delete:'+res+':'+id,async()=>{await API.del('/'+res+'/'+id);const arr=_localArr(res);if(arr){const i=arr.findIndex(x=>x.id===id);if(i>=0)arr.splice(i,1);}else await refresh();});}
async function reseed(){return runAction('admin:seed',async()=>{await API.post('/admin/seed');await refresh();});}
async function doLogout(){ try{await API.post('/auth/logout');}catch(e){} API.setToken('');state.session.loggedIn=false;state.session.role='';state.session.username='';go('home'); }

/* ---------- theme + deco ---------- */
function shade(hex,amt){const h=(hex||'').replace('#','');if(h.length!==6)return hex;const n=parseInt(h,16);if(isNaN(n))return hex;const f=Math.max(0,1-amt);const c=[(n>>16)&255,(n>>8)&255,n&255].map(x=>Math.round(x*f).toString(16).padStart(2,'0'));return '#'+c.join('');}
const DEFAULT_FAVICON="data:image/svg+xml,%3Csvg%20xmlns%3D%27http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%27%20viewBox%3D%270%200%20100%20100%27%3E%3Ctext%20y%3D%27.9em%27%20font-size%3D%2790%27%3E%F0%9F%8D%BC%3C%2Ftext%3E%3C%2Fsvg%3E";
function applyFavicon(){
  const u=(state.db.settings&&state.db.settings.faviconUrl)||'';
  const cur=document.getElementById('favicon'); if(cur) cur.remove();
  const link=document.createElement('link'); link.id='favicon'; link.rel='icon';
  if(u){ link.href=u; } else { link.href=DEFAULT_FAVICON; link.type='image/svg+xml'; }
  document.head.appendChild(link);
}
function applyTheme(){
  const t=state.db.settings.theme, r=document.documentElement.style;
  r.setProperty('--c-primary',t.primary);r.setProperty('--c-primary-d',t.primaryD);
  r.setProperty('--c-primary-strong',shade(t.primaryD,0.12));
  r.setProperty('--c-secondary',t.secondary);r.setProperty('--c-secondary-d',shade(t.secondary,0.38));
  r.setProperty('--c-accent',t.accent);r.setProperty('--c-bg',t.bg);
  const d=state.db.settings.deco; r.setProperty('--deco-opacity',d.enabled?d.opacity:0);
  // Photo frame style: set html.frame-XXX class so scoped CSS can override
  const frame = (state.db.settings && state.db.settings.photoFrame) || 'polaroid';
  const cls = document.documentElement.classList;
  ['frame-polaroid','frame-matted','frame-wood','frame-none'].forEach(c => cls.remove(c));
  cls.add('frame-' + frame);
  buildDeco();
  applyFavicon();
}
function buildDeco(){
  const el=document.getElementById('deco'); if(!el)return; el.innerHTML='';
  const d=state.db.settings.deco; if(!d.enabled)return;
  for(let i=0;i<14;i++){const s=document.createElement('span');s.textContent=d.emoji[i%d.emoji.length];
    s.style.left=Math.random()*100+'%';s.style.top=Math.random()*100+'%';
    s.style.animationDelay=(Math.random()*8)+'s';s.style.fontSize=(1.4+Math.random()*1.8)+'rem';el.appendChild(s);}
}
/* ---------- derived data ---------- */
function sortedGrowth(){return state.db.growth.slice().sort((a,b)=>compareDateValues(a.date,b.date,businessClock.timeZone));}
function latestGrowth(){const g=sortedGrowth();return g[g.length-1];}
function dailyStats(){
  const logs=state.db.daily.slice().sort((a,b)=>new Date(b.time)-new Date(a.time));
  const t=todayStr();
  const today=logs.filter(x=>iso(x.time)===t);
  const feeds=today.filter(x=>x.type==='feeding');
  const totalMl=feeds.reduce((s,x)=>s+(+x.amount||0),0);
  const pee=today.filter(x=>x.type==='diaper'&&x.diaperType==='pee').length;
  const poop=today.filter(x=>x.type==='diaper'&&x.diaperType==='poop').length;
  const lastFeed=logs.find(x=>x.type==='feeding');
  const target=+state.db.settings.feeding.dailyTarget||900;
  return {feeds,totalMl,pee,poop,lastFeed,target,pct:Math.min(100,Math.round(totalMl/target*100)),logs,today};
}
/* ---------- router + lightbox globals ---------- */
const NAV=[['home','首页','🏠'],['timeline','成长时间线','📅'],['gallery','照片画廊','📷'],['videos','成长视频','🎬'],['growth','成长曲线','📈'],['vaccine','疫苗接种','💉'],['daily','日常记录','🍼'],['diary','成长日记','📖'],['messages','留言墙','💌'],['about','关于','👶']];
const route=reactive({name:'home',params:{}});
let _refreshPromise=null;
function go(name,params={}){route.name=name;route.params=params;state.mobileMenu=false;location.hash=name+(params.id?('/'+params.id):'');window.scrollTo({top:0,behavior:'smooth'});}
function parseHash(){const h=location.hash.replace(/^#/,'').split('/');if(h[0]){route.name=h[0];route.params=h[1]?{id:h[1]}:{};}}
const lb=reactive({open:false,list:[],i:0,editable:false});
const uploadState = reactive({active:false,pct:0,label:'',index:0,total:0,cancelled:false,cancellable:true,uploadId:'',resumeKey:'',_xhrs:new Set()});
function cancelUpload(){
  if(!uploadState.active||!uploadState.cancellable) return;
  uploadState.cancelled=true;
  uploadState._xhrs.forEach(h=>{ try{ h.abort(); }catch(e){} });
  const uploadId=uploadState.uploadId, resumeKey=uploadState.resumeKey;
  uploadState.uploadId='';uploadState.resumeKey='';
  if(resumeKey)LS.removeItem(resumeKey);
  if(uploadId)API.del('/upload/'+encodeURIComponent(uploadId)).catch(err=>{if(err&&err.status!==404)console.error('cancel upload cleanup failed',err);});
}
function _cancelErr(){ const e=new Error('已取消上传'); e.cancelled=true; return e; }
const confirmState = reactive({open:false,message:'',_resolve:null});
function confirmDialog(message){return new Promise(res=>{confirmState.message=message;confirmState._resolve=res;confirmState.open=true;});}
function confirmYes(){confirmState.open=false;const r=confirmState._resolve;confirmState._resolve=null;if(r)r(true);}
function confirmNo(){confirmState.open=false;const r=confirmState._resolve;confirmState._resolve=null;if(r)r(false);}
async function saveMediaEdit(item){if(item&&item.id){const payload={caption:item.caption||'',desc:item.desc||''};return runAction(actionKey('update:photos:'+item.id,payload),()=>API.put('/photos/'+item.id,payload));}return null;}
async function saveVideoEdit(item){if(item&&item.id){const payload={title:item.title||'',desc:item.desc||'',date:item.date,url:item.url,cover:item.cover||''};return runAction(actionKey('update:videos:'+item.id,payload),()=>API.put('/videos/'+item.id,payload));}return null;}
function openLightbox(list,i,editable){lb.list=list;lb.i=i;lb.open=true;lb.editable=!!editable;}
let _io; function observeReveals(){nextTick(()=>{if(_io)_io.disconnect();_io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting)e.target.classList.add('in');}),{threshold:.1});document.querySelectorAll('.reveal:not(.in)').forEach(el=>_io.observe(el));});}

/* ---------- shared components ---------- */
const SiteNav={ setup(){
  // 顶部保留的主要栏目；其余归入"更多 ▾"下拉，保持顶部简洁
  const PRIMARY_KEYS=new Set(['home','timeline','gallery','videos','growth','daily']);
  const links=computed(()=>NAV.filter(n=>n[0]==='home'||state.db.settings.modules[n[0]]));
  const primary=computed(()=>links.value.filter(l=>PRIMARY_KEYS.has(l[0])));
  const more=computed(()=>links.value.filter(l=>!PRIMARY_KEYS.has(l[0])));
  const moreOpen=ref(false);
  const inMore=computed(()=>more.value.some(l=>l[0]===route.name));
  // .nav-links 上的 overflow-x:auto 会剪切内部的下拉浮层，所以桌面用 position:fixed 并按按钮位置动态定位
  function positionMoreMenu(btn){
    const menu=btn&&btn.parentElement&&btn.parentElement.querySelector('.more-menu');
    if(!menu||!btn) return;
    const r=btn.getBoundingClientRect();
    menu.style.top=(r.bottom+6)+'px';
    menu.style.right=Math.max(6,window.innerWidth-r.right)+'px';
  }
  async function toggleMore(e){
    if(e){e.preventDefault();e.stopPropagation();}
    const willOpen=!moreOpen.value;
    moreOpen.value=willOpen;
    if(willOpen&&e&&e.currentTarget){ await nextTick(); positionMoreMenu(e.currentTarget); }
  }
  function goItem(name){moreOpen.value=false;go(name);}
  function toggleMobile(e){if(e){e.stopPropagation();}state.mobileMenu=!state.mobileMenu;}
  const onDoc=e=>{
    if(!e.target.closest('.more-wrap'))moreOpen.value=false;
    if(state.mobileMenu&&!e.target.closest('.nav-links')&&!e.target.closest('.menu-btn'))state.mobileMenu=false;
  };
  const onScroll=()=>{if(moreOpen.value)moreOpen.value=false;};
  // 抽屉打开时锁定背景滚动；ESC 关闭
  watch(()=>state.mobileMenu,v=>{document.documentElement.classList.toggle('drawer-open',!!v);});
  const onKey=e=>{if(e.key==='Escape'){if(state.mobileMenu)state.mobileMenu=false;if(moreOpen.value)moreOpen.value=false;}};
  onMounted(()=>{document.addEventListener('click',onDoc);document.addEventListener('keydown',onKey);window.addEventListener('scroll',onScroll,{passive:true});window.addEventListener('resize',onScroll);});
  return {links,primary,more,moreOpen,inMore,state,go,goItem,route,logout:doLogout,toggleMore,toggleMobile};
}, template:`
<header class="nav"><div class="container">
  <a class="brand" @click="go('home')" style="cursor:pointer"><span class="logo">🍼</span>{{state.db.baby.name}}的成长记</a>
  <button class="menu-btn" @click="toggleMobile($event)" :aria-expanded="state.mobileMenu?'true':'false'" aria-controls="site-nav-drawer" aria-label="菜单">☰</button>
  <nav class="nav-links" id="site-nav-drawer" :class="{open:state.mobileMenu}">
    <a v-for="l in primary" :key="l[0]" :class="{active:route.name===l[0]}" @click="go(l[0])"><span class="nav-emoji" aria-hidden="true">{{l[2]}}</span>{{l[1]}}</a>
    <div class="more-wrap" v-if="more.length">
      <a class="more-btn" :class="{active:inMore||moreOpen}" @click="toggleMore($event)">更多 <span class="carat">▾</span></a>
      <div class="more-menu" :class="{show:moreOpen}">
        <a v-for="l in more" :key="l[0]" :class="{active:route.name===l[0]}" @click="goItem(l[0])"><span class="nav-emoji" aria-hidden="true">{{l[2]}}</span>{{l[1]}}</a>
      </div>
    </div>
    <a v-if="state.session.role!=='admin'" class="adminlink" :class="{active:route.name==='profile'}" @click="go('profile')">👤 {{state.session.username||'我的'}}</a>
    <a v-if="state.session.role==='admin'" class="adminlink" :class="{active:route.name.startsWith('admin')}" @click="go('admin')">⚙️ 管理</a>
    <a v-if="state.session.role!=='admin'" class="adminlink" style="cursor:pointer" @click="logout">🚪 退出</a>
  </nav>
</div></header>` };

const SiteFooter={ setup(){return{businessYear};},template:`<footer class="footer container">用 ❤️ 记录成长 · {{businessYear()}}</footer>` };

const Lightbox={ setup(){
  const cur=computed(()=>lb.list[lb.i]||{});
  const editing=ref(false);
  const draft=ref(null);
  const saving=ref(false);
  function cancelEdit(){editing.value=false;draft.value=null;}
  const nav=d=>{cancelEdit();lb.i=(lb.i+d+lb.list.length)%lb.list.length;};
  function close(){cancelEdit();lb.open=false;}
  function startEdit(){draft.value=cloneData(cur.value);editing.value=true;}
  async function saveEdit(){
    if(!draft.value||saving.value)return;
    saving.value=true;
    try{const saved=await saveMediaEdit(draft.value);if(saved)Object.assign(cur.value,saved);cancelEdit();}
    catch(e){alert(e.message);}
    finally{saving.value=false;}
  }
  const onKey=e=>{if(!lb.open)return;if(e.key==='Escape')close();if(!editing.value){if(e.key==='ArrowLeft')nav(-1);if(e.key==='ArrowRight')nav(1);}};
  onMounted(()=>window.addEventListener('keydown',onKey));
  return {lb,cur,nav,close,editing,draft,saving,startEdit,cancelEdit,saveEdit,state};
}, template:`
<transition name="fade"><div class="lb" v-if="lb.open" role="dialog" aria-modal="true" aria-label="媒体预览" @click.self="close">
  <button type="button" class="x" @click="close" aria-label="关闭预览">✕</button>
  <button type="button" class="arw l" @click="nav(-1)" v-if="lb.list.length>1&&!editing" aria-label="上一项">‹</button>
  <figure class="lb-fig">
    <video v-if="isVideo(cur.url)" :src="cur.url" controls autoplay playsinline class="lb-media"></video>
    <img v-else :src="cur.url" :alt="cur.caption" class="lb-media"/>
    <figcaption class="lb-cap">
      <template v-if="editing">
        <input v-model="draft.caption" placeholder="标题" class="lb-input"/>
        <textarea v-model="draft.desc" placeholder="描述（可选）" rows="2" class="lb-input"></textarea>
        <div style="display:flex;gap:8px;justify-content:center;margin-top:8px"><button class="btn gray sm" :disabled="saving" @click="cancelEdit">取消</button><button class="btn sm" :disabled="saving" @click="saveEdit">{{saving?'保存中…':'保存'}}</button></div>
      </template>
      <template v-else>
        <div v-if="cur.caption" class="lb-title">{{cur.caption}}</div>
        <div v-if="cur.desc" class="lb-desc">{{cur.desc}}</div>
        <div class="lb-meta"><span>{{lb.i+1}} / {{lb.list.length}}</span><button v-if="lb.editable&&cur.id&&state.session.loggedIn" class="btn ghost sm" @click="startEdit">✏️ 编辑</button></div>
      </template>
    </figcaption>
  </figure>
  <button type="button" class="arw r" @click="nav(1)" v-if="lb.list.length>1&&!editing" aria-label="下一项">›</button>
</div></transition>` };

const isVideo = isVideoUrl;
const MediaThumb = createMediaThumb(isVideo);
const HistoryPager={ props:['pager'], setup(props){
  async function turn(method){try{await props.pager[method]();}catch(e){}}
  return {turn};
}, template:`
<div class="history-pager" role="navigation" aria-label="历史记录分页">
  <span>共 {{pager.total}} 条 · 第 {{pager.page}} / {{pager.pageCount}} 页</span>
  <div><button class="btn gray sm" :disabled="!pager.hasPrevious||pager.loading" @click="turn('previous')">上一页</button><button class="btn gray sm" :disabled="!pager.hasMore||pager.loading" @click="turn('next')">下一页</button></div>
</div>` };

/* ---------- HOME ---------- */
const Home={ setup(){
  const s=state.db, cfg=computed(()=>s.settings.home);
  const g=computed(()=>latestGrowth());
  const stats=computed(()=>dailyStats());
  const recentMs=computed(()=>s.milestones.slice().sort((a,b)=>compareDateValues(b.date,a.date,businessClock.timeZone)).slice(0,3));
  const recentVideos=computed(()=>(s.videos||[]).slice().sort((a,b)=>compareDateValues(b.date,a.date,businessClock.timeZone)).slice(0,3));
  const vxReminders=computed(()=>(s.vaccines||[]).filter(v=>!v.date).map(v=>({v,i:vxInfo(v)})).filter(x=>x.i.days!=null&&x.i.days<=60).sort((a,b)=>a.i.days-b.i.days).slice(0,4));
  const slides=computed(()=>{const arr=[];s.albums.forEach(a=>{const url=a.cover||((a.photos||[])[0]&&a.photos[0].url);if(url)arr.push({url,cap:a.name});});return arr.slice(0,6);});
  const ci=ref(0); let timer;
  const currentSlide=computed(()=>slides.value[ci.value]||slides.value[0]||null);
  const reduceMotion=typeof window.matchMedia==='function'&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  watch(()=>slides.value.length,length=>{if(!length||ci.value>=length)ci.value=0;});
  onMounted(()=>{if(!reduceMotion)timer=setInterval(()=>{if(slides.value.length)ci.value=(ci.value+1)%slides.value.length;},4000);observeReveals();});
  onUnmounted(()=>clearInterval(timer));
  function daysUntil(dstr){return calendarDaysBetween(todayStr(),iso(dstr));}
  const anniv=computed(()=>{const birth=iso(s.baby.birthday);if(!birth)return [];const out=[{label:'百天',date:addCalendarDays(birth,99)},{label:'半岁',date:addCalendarMonths(birth,6)}];for(let year=1;year<=8;year++)out.push({label:year+'岁生日',date:addCalendarYears(birth,year)});return out.map(item=>({...item,days:daysUntil(item.date)})).filter(item=>item.days>=0).sort((a,b)=>a.days-b.days).slice(0,3);});
  const onthisday=computed(()=>{const today=todayStr();const md=businessMonthDay(today,businessClock.timeZone);const year=businessYearOf(today,businessClock.timeZone);const out=[];const push=(value,icon,title,img)=>{const key=iso(value);const itemYear=businessYearOf(key,businessClock.timeZone);if(key&&businessMonthDay(key,businessClock.timeZone)===md&&itemYear<year)out.push({date:key,icon,title,img,years:year-itemYear});};s.milestones.forEach(m=>push(m.date,'✨',m.title,m.image));(s.diary||[]).forEach(d=>push(d.date,'📖',d.title,(d.images||[])[0]));(s.videos||[]).forEach(v=>push(v.date,'🎬',v.title,v.cover||v.url));if(s.albumsCompact)(s.onThisDayPhotos||[]).forEach(p=>push(p.date,'📷',p.title,p.image));else(s.albums||[]).forEach(a=>(a.photos||[]).forEach(p=>push(p.takenAt,'📷',p.caption||a.name,p.url)));return out.sort((a,b)=>compareDateValues(b.date,a.date,businessClock.timeZone)).slice(0,6);});
  return {s,cfg,g,stats,recentMs,recentVideos,vxReminders,anniv,onthisday,slides,currentSlide,ci,ageText,fmtDate,go,daysOld};
}, template:`
<div>
  <section class="hero" v-if="cfg.hero">
    <div class="hero-bg"></div>
    <div class="container hero-inner">
      <div>
        <span class="tag">🌷 {{ageText(s.baby.birthday)}} · 第 {{daysOld(s.baby.birthday)}} 天</span>
        <h1 style="margin-top:14px">你好呀，我是<span class="accent">{{s.baby.name}}</span></h1>
        <p class="lead">{{s.baby.bio}}</p>
        <div style="display:flex;gap:12px;flex-wrap:wrap">
          <button class="btn" @click="go('timeline')">看看我的成长 →</button>
          <button class="btn ghost" @click="go('gallery')">照片画廊</button>
        </div>
        <div class="hero-stats">
          <div class="s"><b>{{g?g.height:'—'}}<small style="font-size:.9rem">cm</small></b><span>最新身高</span></div>
          <div class="s"><b>{{g?g.weight:'—'}}<small style="font-size:.9rem">kg</small></b><span>最新体重</span></div>
          <div class="s"><b>{{s.milestones.length}}</b><span>里程碑</span></div>
        </div>
      </div>
      <div class="hero-photo">
        <img :src="s.baby.avatar" :alt="s.baby.name" />
        <div class="hero-badge">🎂 {{fmtDate(s.baby.birthday)}}</div>
      </div>
    </div>
  </section>

  <section class="section container" v-if="cfg.carousel && slides.length">
    <div class="carousel">
      <div v-if="currentSlide" :key="currentSlide.url" class="slide on" :style="{backgroundImage:'url('+currentSlide.url+')'}"></div>
      <div class="cap">{{currentSlide?.cap}}</div>
      <div class="dots" role="group" aria-label="轮播图切换">
        <button type="button" v-for="(sl,i) in slides" :key="i" class="dot" :class="{on:i===ci}" :aria-label="'显示第 '+(i+1)+' 张照片：'+sl.cap" :aria-current="i===ci?'true':'false'" @click="ci=i"></button>
      </div>
    </div>
  </section>

  <section class="section container" v-if="cfg.recap && s.recaps && s.recaps.length">
    <div class="card reveal" style="padding:26px;background:linear-gradient(135deg,#fff,#fff4f6)">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px"><span style="font-size:1.4rem">📝</span><h3 style="margin:0">{{s.recaps[0].title}}</h3><span style="margin-left:auto;color:var(--c-muted);font-size:.82rem">{{fmtDate(s.recaps[0].createdAt)}}</span></div>
      <p style="color:#5b5870;white-space:pre-wrap;line-height:1.9">{{s.recaps[0].content}}</p>
    </div>
  </section>

  <section class="section container" v-if="cfg.vaccine && vxReminders.length">
    <h2 class="section-title reveal">💉 疫苗提醒</h2>
    <div class="grid reveal" style="grid-template-columns:repeat(auto-fit,minmax(230px,1fr))">
      <div class="card" v-for="x in vxReminders" :key="x.v.id" style="padding:16px;display:flex;align-items:center;gap:12px">
        <div style="width:42px;height:42px;border-radius:50%;display:grid;place-items:center;font-size:1.2rem;background:#e5f4f7;flex:none">💉</div>
        <div class="grow"><b>{{x.v.name}} 第{{x.v.dose}}剂</b><small style="display:block;color:var(--c-muted)">{{x.i.days<0?('已逾期 '+(-x.i.days)+' 天'):(x.i.days===0?'就在今天':(x.i.days+' 天后到期'))}}</small></div>
        <span class="pill" :class="x.i.cls">{{x.i.label}}</span>
      </div>
    </div>
  </section>

  <section class="section container" v-if="cfg.countdown && anniv.length">
    <h2 class="section-title reveal">🎂 纪念日倒计时</h2>
    <div class="grid reveal" style="grid-template-columns:repeat(auto-fit,minmax(160px,1fr))">
      <div class="card" v-for="(a,i) in anniv" :key="a.label" style="padding:22px;text-align:center">
        <div style="color:var(--c-muted);font-size:.85rem">{{a.label}}</div>
        <div style="font-family:'Baloo 2';font-size:2.6rem;color:var(--c-primary-d);line-height:1.15">{{a.days===0?'今天!':a.days}}</div>
        <div style="color:var(--c-muted);font-size:.8rem">{{a.days===0?'🎉 就是今天':('天后 · '+fmtDate(a.date))}}</div>
      </div>
    </div>
  </section>

  <section class="section container" v-if="cfg.onthisday && onthisday.length">
    <h2 class="section-title reveal">📆 那年今天</h2>
    <p class="section-sub reveal">往年的这一天，也有这些温柔瞬间</p>
    <div class="grid ms-grid">
      <div class="card ms-card reveal" v-for="(o,i) in onthisday" :key="i">
        <div class="ph" :data-date="o.date?fmtDate(o.date):null"><MediaThumb :url="o.img"/></div>
        <div class="bd"><div class="dt">{{o.years}} 年前的今天 · {{o.icon}}</div><h4>{{o.title}}</h4><p>{{fmtDate(o.date)}}</p></div>
      </div>
    </div>
  </section>

  <section class="section container" v-if="cfg.milestones">
    <h2 class="section-title reveal">✨ 最近里程碑</h2>
    <p class="section-sub reveal">那些值得铭记的第一次</p>
    <div class="grid ms-grid">
      <div class="card ms-card reveal" v-for="m in recentMs" :key="m.id" @click="go('timeline')">
        <div class="ph" :data-date="m.date?fmtDate(m.date):null"><MediaThumb :url="m.image"/></div>
        <div class="bd"><div class="dt">{{fmtDate(m.date)}} · {{m.category}}</div><h4>{{m.title}}</h4><p>{{m.desc}}</p></div>
      </div>
    </div>
  </section>

  <section class="section container" v-if="cfg.videos && recentVideos.length">
    <h2 class="section-title reveal">🎬 最新成长视频</h2>
    <p class="section-sub reveal">会动的珍贵瞬间</p>
    <div class="grid vid-grid">
      <div class="card vid-card reveal" v-for="v in recentVideos" :key="v.id" @click="go('videos',{id:v.id})">
        <div class="vthumb"><MediaThumb :url="v.cover||v.url"/><span class="playbadge">▶</span></div>
        <div class="bd"><div class="dt">{{fmtDate(v.date)}}</div><h4>{{v.title}}</h4></div>
      </div>
    </div>
    <div class="reveal" style="text-align:center;margin-top:20px"><button class="btn ghost" @click="go('videos')">查看全部视频 →</button></div>
  </section>

  <section class="section container" v-if="cfg.diary">
    <div class="card reveal" style="padding:34px;display:grid;grid-template-columns:1fr auto;gap:20px;align-items:center;background:linear-gradient(135deg,#fff,#fff4f6)">
      <div><h2 style="margin-bottom:8px">📖 成长日记</h2><p style="color:var(--c-muted)">已记录 {{s.diary.length}} 篇温柔的日常，点滴都是爱。</p></div>
      <button class="btn" @click="go('diary')">翻开日记</button>
    </div>
  </section>
</div>` };

/* ---------- TIMELINE ---------- */
const Timeline={ setup(){
  const items=computed(()=>state.db.milestones.slice().sort((a,b)=>compareDateValues(b.date,a.date,businessClock.timeZone)));
  const years=computed(()=>['全部',...[...new Set(items.value.map(m=>businessYearOf(m.date,businessClock.timeZone)).filter(Boolean))].sort((a,b)=>b-a)]);
  const yr=ref('全部');
  const shown=computed(()=>yr.value==='全部'?items.value:items.value.filter(m=>businessYearOf(m.date,businessClock.timeZone)===yr.value));
  watch([yr,shown],()=>observeReveals()); onMounted(observeReveals);
  return {items,years,yr,shown,fmtDate,ageText,state,openLightbox};
}, template:`
<section class="section container">
  <h2 class="section-title">📅 成长时间线</h2>
  <p class="section-sub">一步一步，慢慢长大</p>
  <div class="yr-filter">
    <button v-for="y in years" :key="y" :class="{on:yr===y}" @click="yr=y">{{y}}{{y==='全部'?'':'年'}}</button>
  </div>
  <div class="tl">
    <div class="tl-item reveal" v-for="m in shown" :key="m.id">
      <div class="dot"></div>
      <div class="card tl-card">
        <div class="dt">{{fmtDate(m.date)}} · {{ageText(state.db.baby.birthday,m.date)||'新生'}} · <span class="tag">{{m.category}}</span></div>
        <h4>{{m.title}}</h4>
        <p style="color:var(--c-muted)">{{m.desc}}</p>
        <div class="tl-img" v-if="m.image" :data-date="m.date?fmtDate(m.date):null" @click="openLightbox([{url:m.image,caption:m.title}],0)" style="cursor:pointer"><MediaThumb :url="m.image"/></div>
      </div>
    </div>
  </div>
</section>` };

/* ---------- GALLERY ---------- */
const Gallery={ setup(){
  const albums=computed(()=>state.db.albums);
  const album=computed(()=>state.db.albums.find(a=>sameId(a.id,route.params.id)));
  const loading=ref(!!route.params.id&&albumNeedsLoad(album.value));
  const error=ref('');
  async function loadDetail(){const id=route.params.id;error.value='';if(!id||!albumNeedsLoad(album.value)){loading.value=false;return;}loading.value=true;try{await ensureAlbumLoaded(id);}catch(e){error.value=e.message||'相册加载失败';}finally{loading.value=false;observeReveals();}}
  onMounted(()=>{loadDetail();observeReveals();});watch([()=>route.params.id,()=>album.value&&album.value.photosLoaded],()=>{loadDetail();observeReveals();});
  return {albums,album,route,go,fmtDate,openLightbox,albumPhotoCount,loading,error,loadDetail};
}, template:`
<section class="section container">
  <template v-if="!route.params.id">
    <h2 class="section-title">📷 照片画廊</h2>
    <p class="section-sub">共 {{albums.length}} 本相册</p>
    <div class="grid alb-grid">
      <div class="alb reveal" v-for="a in albums" :key="a.id" @click="go('gallery',{id:a.id})">
        <MediaThumb :url="a.cover"/>
        <div class="ov"><h4>{{a.name}}</h4><span>{{fmtDate(a.date)}} · {{albumPhotoCount(a)}} 张</span></div>
      </div>
    </div>
  </template>
  <div v-else-if="loading" class="card" style="padding:34px;text-align:center;color:var(--c-muted)">正在加载相册照片…</div>
  <div v-else-if="error" class="card" style="padding:34px;text-align:center"><p style="color:#c53d52;margin-bottom:14px">{{error}}</p><button class="btn" @click="loadDetail">重新加载</button></div>
  <template v-else-if="album">
    <button class="btn ghost sm" @click="go('gallery')">← 返回相册</button>
    <h2 class="section-title" style="margin-top:16px">{{album.name}}</h2>
    <p class="section-sub">{{album.desc}} · {{fmtDate(album.date)}}</p>
    <div class="grid photos">
      <div class="p reveal" v-for="(p,i) in album.photos" :key="p.id" :data-date="p.takenAt?fmtDate(p.takenAt):null" @click="openLightbox(album.photos,i,true)"><MediaThumb :url="p.url"/></div>
    </div>
  </template>
  <div v-else class="card" style="padding:34px;text-align:center;color:var(--c-muted)">相册不存在或已被删除</div>
</section>` };
const WHO={
 girl:{M:[0,1,2,3,4,6,9,12,15,18,21,24],
  height:{p3:[45.6,50.0,53.2,55.6,57.8,61.2,65.3,68.9,72.0,74.9,77.5,80.0],p50:[49.1,53.7,57.1,59.8,62.1,65.7,70.1,74.0,77.5,80.7,83.7,86.4],p97:[52.7,57.4,61.1,64.0,66.4,70.3,74.9,79.2,83.0,86.5,89.8,92.9]},
  weight:{p3:[2.4,3.2,4.0,4.5,5.0,5.7,6.5,7.0,7.6,8.1,8.6,9.0],p50:[3.2,4.2,5.1,5.8,6.4,7.3,8.2,8.9,9.6,10.2,10.9,11.5],p97:[4.2,5.5,6.6,7.5,8.2,9.3,10.5,11.5,12.4,13.2,14.0,14.8]}},
 boy:{M:[0,1,2,3,4,6,9,12,15,18,21,24],
  height:{p3:[46.1,50.8,54.4,57.3,59.7,63.3,67.5,71.0,74.2,76.9,79.4,81.7],p50:[49.9,54.7,58.4,61.4,63.9,67.6,72.0,75.7,79.1,82.3,85.1,87.8],p97:[53.7,58.6,62.4,65.5,68.0,71.9,76.5,80.5,84.0,87.7,90.8,93.9]},
  weight:{p3:[2.5,3.4,4.4,5.0,5.6,6.4,7.1,7.7,8.3,8.8,9.2,9.7],p50:[3.3,4.5,5.6,6.4,7.0,7.9,8.9,9.6,10.3,10.9,11.5,12.2],p97:[4.3,5.8,7.1,8.0,8.7,9.8,11.0,12.0,12.9,13.7,14.5,15.3]}}
};
/* ---------- GROWTH ---------- */
const Growth={ setup(){
  const rows=computed(()=>sortedGrowth());
  const el=ref(null); let chart;
  function render(){
    if(!el.value)return; if(!chart)chart=echarts.init(el.value);
    const t=state.db.settings.theme, r=rows.value, b=state.db.baby;
    chart.setOption({
      tooltip:{trigger:'axis'},
      legend:{data:['身高 (cm)','体重 (kg)'],bottom:0},
      grid:{left:52,right:52,top:30,bottom:46},
      xAxis:{type:'category',boundaryGap:false,data:r.map(x=>ageText(b.birthday,x.date)||'出生'),axisLabel:{color:'#8f8ba0'}},
      yAxis:[{type:'value',name:'cm',scale:true,axisLabel:{color:'#8f8ba0'},splitLine:{lineStyle:{color:'#f0e3dd'}}},
             {type:'value',name:'kg',scale:true,axisLabel:{color:'#8f8ba0'},splitLine:{show:false}}],
      series:[
        {name:'身高 (cm)',type:'line',smooth:true,symbolSize:7,data:r.map(x=>x.height),
         itemStyle:{color:t.primary},lineStyle:{width:3,color:t.primary},
         areaStyle:{color:new echarts.graphic.LinearGradient(0,0,0,1,[{offset:0,color:t.primary+'55'},{offset:1,color:t.primary+'05'}])}},
        {name:'体重 (kg)',type:'line',yAxisIndex:1,smooth:true,symbolSize:7,data:r.map(x=>x.weight),
         itemStyle:{color:t.secondary},lineStyle:{width:3,color:t.secondary}}
      ]
    });
  }
  const metric=ref('height'); const pel=ref(null); let chart2;
  function monthsAt(value){const birth=iso(state.db.baby.birthday),current=iso(value);return birth&&current?calendarDaysBetween(birth,current)/30.44:0;}
  function renderPct(){
    if(!pel.value)return; if(!chart2)chart2=echarts.init(pel.value);
    const t=state.db.settings.theme; const sex=state.db.baby.gender==='boy'?'boy':'girl'; const w=WHO[sex]; const m=metric.value;
    const line=(name,arr,color,dashed)=>({name,type:'line',smooth:true,showSymbol:false,data:w.M.map((mo,i)=>[mo,arr[i]]),lineStyle:{color,width:1.5,type:dashed?'dashed':'solid',opacity:.75},itemStyle:{color},z:1});
    const baby=rows.value.filter(r=>r[m]!=null).map(r=>[+monthsAt(r.date).toFixed(2),r[m]]).sort((a,b)=>a[0]-b[0]);
    chart2.setOption({
      tooltip:{trigger:'axis'},legend:{bottom:0,textStyle:{color:'#8f8ba0'}},
      grid:{left:48,right:20,top:22,bottom:46},
      xAxis:{type:'value',name:'月龄',min:0,axisLabel:{color:'#8f8ba0'},splitLine:{show:false}},
      yAxis:{type:'value',name:m==='height'?'cm':'kg',scale:true,axisLabel:{color:'#8f8ba0'},splitLine:{lineStyle:{color:'#f0e3dd'}}},
      series:[
        line('P97',w[m].p97,'#cbd6da',true),
        line('P50 中位',w[m].p50,'#9bb0b7',false),
        line('P3',w[m].p3,'#cbd6da',true),
        {name:state.db.baby.name+' 实测',type:'line',smooth:true,symbolSize:8,data:baby,itemStyle:{color:t.primary},lineStyle:{width:3,color:t.primary},z:3}
      ]
    });
  }
  const onResize=()=>{chart&&chart.resize();chart2&&chart2.resize();};
  onMounted(()=>{render();renderPct();window.addEventListener('resize',onResize);observeReveals();});
  onUnmounted(()=>{window.removeEventListener('resize',onResize);chart&&chart.dispose();chart2&&chart2.dispose();chart=chart2=null;});
  watch(rows,()=>nextTick(()=>{render();renderPct();}),{deep:true});
  watch(metric,()=>nextTick(renderPct));
  return {rows,el,pel,metric,fmtDate,ageText,state};
}, template:`
<section class="section container">
  <h2 class="section-title">📈 成长曲线</h2>
  <p class="section-sub">身高体重变化趋势</p>
  <div class="card reveal" style="padding:22px;margin-bottom:26px"><div ref="el" class="chart"></div></div>
  <div class="card reveal" style="padding:22px;margin-bottom:26px">
    <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px">
      <h4>📊 WHO 生长百分位（{{state.db.baby.gender==='boy'?'男':'女'}}宝）</h4>
      <div class="yr-filter" style="margin:0"><button :class="{on:metric==='height'}" @click="metric='height'">身高</button><button :class="{on:metric==='weight'}" @click="metric='weight'">体重</button></div>
    </div>
    <p class="section-sub" style="margin:6px 0 4px">虚线为 WHO 参考区间（P3 · P50 中位 · P97），实线为{{state.db.baby.name}}实测。仅供参考，请以医生评估为准。</p>
    <div ref="pel" class="chart"></div>
  </div>
  <div class="card reveal" style="padding:8px 4px;overflow:auto">
    <table class="tbl"><thead><tr><th>日期</th><th>月龄</th><th>身高 (cm)</th><th>体重 (kg)</th><th>头围 (cm)</th></tr></thead>
    <tbody><tr v-for="x in rows.slice().reverse()" :key="x.id">
      <td>{{fmtDate(x.date)}}</td><td>{{ageText(state.db.baby.birthday,x.date)||'出生'}}</td>
      <td>{{x.height}}</td><td>{{x.weight}}</td><td>{{x.head}}</td></tr></tbody></table>
  </div>
</section>` };

/* ---------- DAILY ---------- */
const Daily={ setup(){
  const tick=ref(0); let t; onMounted(()=>{t=setInterval(()=>tick.value++,30000);observeReveals();}); onUnmounted(()=>clearInterval(t));
  const s=computed(()=>dailyStats());
  const sinceLast=computed(()=>{tick.value;return s.value.lastFeed?since(s.value.lastFeed.time):'—';});
  const feedTime=value=>formatBusinessTime(value,businessClock.timeZone);
  return {s,sinceLast,feedTime,fmtMD,state};
}, template:`
<section class="section container">
  <h2 class="section-title">🍼 日常记录</h2>
  <p class="section-sub">今日喂养与护理概览</p>
  <div class="stat-row">
    <div class="card stat reveal"><b>{{s.feeds.length}}</b><span>今日喂奶次数</span></div>
    <div class="card stat reveal"><b>{{s.totalMl}}<small style="font-size:.9rem">ml</small></b><span>今日总奶量</span></div>
    <div class="card stat reveal"><b>{{s.pee}}</b><span>小便次数</span></div>
    <div class="card stat reveal"><b>{{s.poop}}</b><span>大便次数</span></div>
  </div>
  <div class="grid" style="grid-template-columns:1fr 1fr;gap:22px;margin-bottom:26px">
    <div class="card reveal" style="padding:24px">
      <h4>每日奶量进度</h4>
      <div class="prog"><i :style="{width:s.pct+'%'}"></i></div>
      <div style="display:flex;justify-content:space-between;color:var(--c-muted);font-size:.88rem"><span>{{s.totalMl}} ml</span><span>目标 {{s.target}} ml · {{s.pct}}%</span></div>
    </div>
    <div class="card reveal" style="padding:24px;text-align:center">
      <h4 style="text-align:left">距上次喂奶</h4>
      <div class="feed-timer" style="margin:10px 0">{{sinceLast}}</div>
      <span style="color:var(--c-muted);font-size:.86rem">{{s.lastFeed?('上次 '+(s.lastFeed.amount||'')+'ml · '+feedTime(s.lastFeed.time)):'今天还没喂奶'}}</span>
    </div>
  </div>
  <h4 class="reveal" style="margin-bottom:12px">📋 今日时间线</h4>
  <div class="reveal">
    <div class="log" v-for="l in s.today" :key="l.id">
      <div class="ic" :class="l.type==='feeding'?'feed':(l.diaperType==='poop'?'poop':'pee')">{{l.type==='feeding'?'🍼':(l.diaperType==='poop'?'💩':'💧')}}</div>
      <div class="grow"><b>{{l.type==='feeding'?('喂奶 '+(l.amount||'')+'ml · '+(l.feedType==='breast'?'母乳':'配方奶')):('换尿布 · '+(l.diaperType==='poop'?'大便':'小便'))}}</b>
      <small>{{l.note||'—'}}</small></div>
      <span style="color:var(--c-muted)">{{feedTime(l.time)}}</span>
    </div>
    <p v-if="!s.today.length" style="color:var(--c-muted);text-align:center;padding:20px">今天还没有记录，去管理页或用 AI 助手添加一条吧～</p>
  </div>
</section>` };

/* ---------- DIARY ---------- */
const Diary={ setup(){
  const list=computed(()=>state.db.diary.slice().sort((a,b)=>compareDateValues(b.date,a.date,businessClock.timeZone)));
  const entry=computed(()=>state.db.diary.find(d=>sameId(d.id,route.params.id)));
  const loading=ref(!!route.params.id&&diaryNeedsLoad(entry.value));const error=ref('');
  async function loadDetail(){const id=route.params.id;error.value='';if(!id||!diaryNeedsLoad(entry.value)){loading.value=false;return;}loading.value=true;try{await ensureDiaryLoaded(id);}catch(e){error.value=e.message||'日记加载失败';}finally{loading.value=false;observeReveals();}}
  onMounted(()=>{loadDetail();observeReveals();});watch([()=>route.params.id,()=>entry.value&&entry.value.detailLoaded],()=>{loadDetail();observeReveals();});
  return {list,entry,route,go,fmtDate,openLightbox,loading,error,loadDetail};
}, template:`
<section class="section container">
  <template v-if="!route.params.id">
    <h2 class="section-title">📖 成长日记</h2>
    <p class="section-sub">写给未来的你</p>
    <div class="grid diary-grid">
      <div class="card diary reveal" v-for="d in list" :key="d.id" @click="go('diary',{id:d.id})" style="cursor:pointer;overflow:hidden">
        <div class="ph" v-if="d.images&&d.images[0]" :data-date="d.date?fmtDate(d.date):null"><MediaThumb :url="d.images[0]"/></div>
        <div class="bd"><div class="dt">{{fmtDate(d.date)}}</div><h3>{{d.title}}</h3><p>{{d.content.slice(0,60)}}…</p></div>
      </div>
    </div>
  </template>
  <div v-else-if="loading" class="card" style="padding:34px;text-align:center;color:var(--c-muted)">正在加载完整日记…</div>
  <div v-else-if="error" class="card" style="padding:34px;text-align:center"><p style="color:#c53d52;margin-bottom:14px">{{error}}</p><button class="btn" @click="loadDetail">重新加载</button></div>
  <template v-else-if="entry">
    <button class="btn ghost sm" @click="go('diary')">← 返回日记</button>
    <article class="card reveal" style="padding:34px;max-width:760px;margin:18px auto 0">
      <div class="dt" style="color:var(--c-secondary-d);font-weight:700">{{fmtDate(entry.date)}}</div>
      <h2 style="margin:6px 0 18px">{{entry.title}}</h2>
      <p style="white-space:pre-wrap;color:#5b5870;line-height:1.9">{{entry.content}}</p>
      <div class="grid" style="grid-template-columns:repeat(2,1fr);margin-top:20px" v-if="entry.images&&entry.images.length">
        <div v-for="(im,i) in entry.images" :key="i" @click="openLightbox(entry.images.map(u=>({url:u,caption:entry.title})),i)" style="position:relative;aspect-ratio:16/10;border-radius:14px;overflow:hidden;cursor:pointer;background:#f3e7e2"><MediaThumb :url="im"/></div>
      </div>
    </article>
  </template>
  <div v-else class="card" style="padding:34px;text-align:center;color:var(--c-muted)">日记不存在或已被删除</div>
</section>` };

/* ---------- MESSAGES ---------- */
const Messages={ setup(){
  const approved=computed(()=>state.db.messages.filter(m=>m.status==='approved').sort((a,b)=>new Date(b.createdAt)-new Date(a.createdAt)));
  const form=reactive({name:'',content:''}); const done=ref(false);
  const colors=['#ef8fa4','#7fc8d4','#ffca7a','#9b8cff','#6dc38f'];
  async function submit(){if(!form.name.trim()||!form.content.trim())return;
    try{ await API.post('/messages',{name:form.name,content:form.content,color:colors[Math.floor(Math.random()*colors.length)]}); form.name='';form.content='';done.value=true;setTimeout(()=>done.value=false,5000);}catch(e){alert(e.message);} }
  onMounted(observeReveals);
  return {approved,form,submit,done,fmtMD,since};
}, template:`
<section class="section container">
  <h2 class="section-title">💌 留言墙</h2>
  <p class="section-sub">给宝贝留下一句祝福（审核后展示）</p>
  <div class="card reveal" style="padding:22px;margin-bottom:30px;max-width:640px">
    <div class="row2"><div class="field"><label>你的称呼</label><input v-model="form.name" placeholder="如：外婆 / 朋友 小李"/></div>
    <div class="field" style="display:flex;align-items:flex-end"><button class="btn" style="width:100%" @click="submit">送出祝福 💝</button></div></div>
    <div class="field" style="margin:0"><label>祝福的话</label><textarea v-model="form.content" rows="2" placeholder="写点什么给宝贝吧…"></textarea></div>
    <p v-if="done" style="color:#2f855a;margin-top:10px">✅ 已提交，待管理员审核后就会出现在留言墙上啦～</p>
  </div>
  <div class="grid msg-grid">
    <div class="card msg reveal" v-for="m in approved" :key="m.id">
      <div class="who"><span class="av" :style="{background:m.color}">{{m.name.slice(0,1)}}</span><b>{{m.name}}</b></div>
      <p>{{m.content}}</p><div class="t">{{fmtMD(m.createdAt)}} · {{since(m.createdAt)}}前</div>
    </div>
  </div>
</section>` };

/* ---------- ABOUT ---------- */
const About={ setup(){ onMounted(observeReveals); return {state,ageText,fmtDate,daysOld}; },
 template:`
<section class="section container">
  <h2 class="section-title">👶 关于{{state.db.baby.name}}</h2>
  <div class="card reveal" style="padding:30px;margin-top:10px">
    <div class="about-hero">
      <div class="av"><img :src="state.db.baby.avatar" style="width:100%;height:100%;object-fit:cover"/></div>
      <div>
        <h1 style="font-size:2.2rem">{{state.db.baby.name}}</h1>
        <p style="margin:10px 0"><span class="tag">{{state.db.baby.gender==='girl'?'👧 女宝宝':'👦 男宝宝'}}</span>
        <span class="tag" style="background:rgba(255,202,122,.25);color:#b5822a">🎂 {{fmtDate(state.db.baby.birthday)}}</span>
        <span class="tag">{{ageText(state.db.baby.birthday)}} · 第{{daysOld(state.db.baby.birthday)}}天</span></p>
        <p style="color:#5b5870;line-height:1.9">{{state.db.baby.bio}}</p>
      </div>
    </div>
    <hr style="border:none;border-top:1px dashed var(--c-line);margin:26px 0"/>
    <h3>👨‍👩‍👧 我们的家</h3>
    <p style="color:#5b5870;margin-top:8px">{{state.db.baby.family}}</p>
  </div>
</section>` };
/* ---------- VIDEOS ---------- */
const Videos={ setup(){
  const list=computed(()=>state.db.videos||[]);
  const cur=computed(()=>list.value.find(v=>sameId(v.id,route.params.id)));
  const vedit=ref(false);
  const draft=ref(null);
  const saving=ref(false);
  function startEdit(){draft.value=cloneData(cur.value);vedit.value=true;}
  function cancelEdit(){draft.value=null;vedit.value=false;}
  async function saveVideo(){
    if(!draft.value||saving.value)return;
    saving.value=true;
    try{const saved=await saveVideoEdit(draft.value);if(saved&&cur.value)Object.assign(cur.value,saved);cancelEdit();}
    catch(e){alert(e.message);}
    finally{saving.value=false;}
  }
  onMounted(observeReveals); watch(()=>route.params.id,()=>{cancelEdit();observeReveals();});
  return {list,cur,route,go,fmtDate,vedit,draft,saving,startEdit,cancelEdit,saveVideo,state};
}, template:`
<section class="section container">
  <template v-if="!cur">
    <h2 class="section-title">\ud83c\udfac 成长视频</h2>
    <p class="section-sub">共 {{list.length}} 个视频 · 那些会动的珍贵瞬间</p>
    <div class="grid vid-grid">
      <div class="card vid-card reveal" v-for="v in list" :key="v.id" @click="go('videos',{id:v.id})">
        <div class="vthumb"><MediaThumb :url="v.cover||v.url"/><span class="playbadge">▶</span></div>
        <div class="bd"><div class="dt">{{fmtDate(v.date)}}</div><h4>{{v.title}}</h4><p>{{v.desc}}</p></div>
      </div>
    </div>
    <p v-if="!list.length" style="color:var(--c-muted);text-align:center;padding:30px">还没有视频，去管理页上传第一个吧～</p>
  </template>
  <template v-else>
    <button class="btn ghost sm" @click="go('videos')">← 返回视频</button>
    <div class="card reveal" style="padding:18px;max-width:900px;margin:16px auto 0">
      <video :src="cur.url" :poster="cur.cover||''" controls autoplay playsinline style="display:block;margin:0 auto;max-width:100%;max-height:72vh;width:auto;border-radius:14px;background:#000"></video>
      <div style="padding:10px 4px 0">
        <div class="dt" style="color:var(--c-secondary-d);font-weight:700">{{fmtDate(cur.date)}}</div>
        <template v-if="vedit">
          <input v-model="draft.title" placeholder="标题" style="font-size:1.15rem;font-weight:700;width:100%;padding:9px 11px;border:1.5px solid var(--c-line);border-radius:10px;margin:6px 0"/>
          <textarea v-model="draft.desc" placeholder="描述" rows="3" style="width:100%;padding:9px 11px;border:1.5px solid var(--c-line);border-radius:10px"></textarea>
          <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:8px"><button class="btn gray sm" :disabled="saving" @click="cancelEdit">取消</button><button class="btn sm" :disabled="saving" @click="saveVideo">{{saving?'保存中…':'保存'}}</button></div>
        </template>
        <template v-else>
          <h2 style="margin:4px 0 8px">{{cur.title}}</h2><p style="color:#5b5870;white-space:pre-wrap">{{cur.desc}}</p>
          <button v-if="state.session.loggedIn" class="btn ghost sm" @click="startEdit">✏️ 编辑标题/描述</button>
        </template>
      </div>
    </div>
    <div class="grid vid-grid" style="max-width:900px;margin:22px auto 0" v-if="list.length>1">
      <div class="card vid-card" v-for="v in list.filter(x=>x.id!==cur.id)" :key="v.id" @click="go('videos',{id:v.id})">
        <div class="vthumb"><MediaThumb :url="v.cover||v.url"/><span class="playbadge">▶</span></div>
        <div class="bd"><h4>{{v.title}}</h4></div>
      </div>
    </div>
  </template>
</section>` };

const Profile={ setup(){
  const f=reactive({old:'',n1:'',n2:''}); const msg=ref(''); const ok=ref(false); const busy=ref(false);
  const uname=computed(()=>state.session.username); const role=computed(()=>state.session.role);
  async function submit(){msg.value='';if(f.n1.length<8){ok.value=false;msg.value='新密码至少 8 位';return;}if(f.n1!==f.n2){ok.value=false;msg.value='两次输入的新密码不一致';return;}busy.value=true;try{await API.post('/auth/change-password',{oldPassword:f.old,newPassword:f.n1});ok.value=true;msg.value='✅ 密码已更新，其他设备的旧会话已退出';f.old=f.n1=f.n2='';}catch(e){ok.value=false;msg.value=e.message||'修改失败';}busy.value=false;}
  onMounted(observeReveals);
  return {f,msg,ok,busy,uname,role,submit};
}, template:`
<section class="section container">
  <h2 class="section-title">👤 个人资料</h2>
  <div class="card reveal" style="padding:26px;max-width:520px">
    <div style="display:flex;align-items:center;gap:14px;margin-bottom:18px">
      <span style="width:56px;height:56px;border-radius:50%;background:linear-gradient(135deg,var(--c-primary),var(--c-accent));display:grid;place-items:center;color:#fff;font-weight:700;font-size:1.4rem">{{(uname||'?').slice(0,1).toUpperCase()}}</span>
      <div><b style="font-size:1.15rem">{{uname}}</b><div style="color:var(--c-muted);font-size:.9rem">{{role==='admin'?'管理员':'家庭成员'}}</div></div>
    </div>
    <hr style="border:none;border-top:1px dashed var(--c-line);margin:0 0 18px"/>
    <h4 style="margin-bottom:12px">🔒 修改密码</h4>
    <div class="field"><label>当前密码</label><input type="password" v-model="f.old" @keyup.enter="submit"/></div>
    <div class="field"><label>新密码（至少 8 位）</label><input type="password" v-model="f.n1" @keyup.enter="submit"/></div>
    <div class="field"><label>确认新密码</label><input type="password" v-model="f.n2" @keyup.enter="submit"/></div>
    <p v-if="msg" :style="{color: ok?'#2f855a':'#e0576a',margin:'0 0 12px'}">{{msg}}</p>
    <button class="btn" :disabled="busy" @click="submit">保存新密码</button>
  </div>
</section>` };

const ShareView={ setup(){
  const album=ref(null); const baby=ref(''); const err=ref(''); const loading=ref(true);
  onMounted(async()=>{try{const d=await API.get('/share/'+route.params.id);album.value=d.album;baby.value=d.babyName;}catch(e){err.value=e.message||'链接无效或已过期';}loading.value=false;observeReveals();});
  return {album,baby,err,loading,openLightbox,fmtDate};
}, template:`
<div>
  <header class="nav"><div class="container"><a class="brand"><span class="logo">🍼</span>{{baby||'宝贝'}}的相册</a></div></header>
  <section class="section container">
    <div v-if="loading" style="text-align:center;padding:50px;color:var(--c-muted)">加载中…</div>
    <div v-else-if="err" style="text-align:center;padding:60px 20px"><div style="font-size:2.6rem">🔒</div><h3 style="margin:10px 0 6px">{{err}}</h3><p style="color:var(--c-muted)">请向分享者索取新的链接。</p></div>
    <template v-else-if="album">
      <h2 class="section-title">📷 {{album.name}}</h2>
      <p class="section-sub">{{album.desc}}<template v-if="album.date"> · {{fmtDate(album.date)}}</template> · 共 {{album.photos.length}} 项</p>
      <div class="grid photos">
        <div class="p reveal" v-for="(p,i) in album.photos" :key="p.id" :data-date="p.takenAt?fmtDate(p.takenAt):null" @click="openLightbox(album.photos,i)"><MediaThumb :url="p.url"/></div>
      </div>
      <p style="text-align:center;color:var(--c-muted);font-size:.85rem;margin-top:34px">来自「{{baby}}的成长记」· 家庭私密分享</p>
    </template>
  </section>
</div>` };

/* ---------- VACCINE ---------- */
const Vaccine={ setup(){
  const list=computed(()=>(state.db.vaccines||[]).slice().sort((a,b)=>(a.plannedMonth-b.plannedMonth)||(''+a.name).localeCompare(b.name)));
  const done=computed(()=>list.value.filter(v=>v.date).length);
  const pct=computed(()=>list.value.length?Math.round(done.value/list.value.length*100):0);
  onMounted(observeReveals);
  return {list,done,pct,state,fmtDate};
}, template:`
<section class="section container">
  <h2 class="section-title">💉 疫苗接种</h2>
  <p class="section-sub">国家免疫规划参考 · 已完成 {{done}}/{{list.length}}（{{pct}}%）</p>
  <div class="card reveal" style="padding:18px;margin-bottom:20px" v-if="list.length"><div class="prog"><i :style="{width:pct+'%'}"></i></div></div>
  <div class="reveal">
    <div class="log" v-for="v in list" :key="v.id">
      <div class="ic feed">💉</div>
      <div class="grow"><b>{{v.name}} <span style="color:var(--c-muted);font-weight:400;font-size:.85rem">第{{v.dose}}剂</span></b><small>建议 {{vxMonLabel(v.plannedMonth)}}<template v-if="v.date"> · 已于 {{fmtDate(v.date)}} 接种</template><template v-else-if="vxInfo(v).due"> · 应于 {{fmtDate(vxInfo(v).due)}}</template></small></div>
      <span class="pill" :class="vxInfo(v).cls">{{vxInfo(v).label}}</span>
    </div>
    <p v-if="!list.length" style="color:var(--c-muted);text-align:center;padding:30px">还没有疫苗计划，管理员可在管理端「疫苗管理」载入标准免疫程序。</p>
  </div>
</section>` };

/* ---------- admin helpers ---------- */
const IMG_EXT=['jpg','jpeg','png','gif','webp','avif','heic'];
const VID_EXT=['mp4','webm','ogg','ogv','mov','m4v','mkv'];
const UPLOAD_LIMITS_DEFAULT={imageMB:10,videoMB:200};
// 客户端图片压缩：上传前把大图缩到 2048px、JPEG 85% 质量。iPhone 5MB 原图 → ~350KB，
// 上传耗时缩短一个数量级，是手机端能稳定上传的关键。压缩失败或无益则用原文件。
async function shrinkImage(file, maxDim=2048, quality=0.85){
  if(!file||detectFileKind(file,IMG_EXT,VID_EXT)!=='image') return file;
  if(file.type==='image/svg+xml'||file.type==='image/gif') return file;   // 保留矢量/动图原样
  if(file.size < 512*1024) return file;                                    // <512KB 不折腾
  let bmp=null;
  try{ bmp = await createImageBitmap(file); }catch(e){ return file; }      // 浏览器不能解码则原样上传
  const {width,height}=bmp;
  const scale = Math.min(1, maxDim/Math.max(width,height));
  const w = Math.round(width*scale), h = Math.round(height*scale);
  const canvas = document.createElement('canvas'); canvas.width=w; canvas.height=h;
  const ctx = canvas.getContext('2d'); ctx.drawImage(bmp,0,0,w,h);
  if(bmp.close) bmp.close();
  const blob = await new Promise(r=>canvas.toBlob(r,'image/jpeg',quality));
  if(!blob||blob.size>=file.size) return file;                             // 压完反而更大就跳过
  const newName = (file.name||'image').replace(/\.[^.]+$/,'')+'.jpg';
  const out = new File([blob], newName, {type:'image/jpeg', lastModified: file.lastModified||Date.now()});
  return out;
}
// 分片上传：把大文件切成 5MB 块，并发 POST（限 CHUNK_CONCURRENCY 个同时进行），
// 每片请求短、避开 Cloudflare 100s 单请求上限；合并时后端按 index 排序，故并发顺序无关
async function xhrUploadChunked(file, onProgress){
  const CHUNK=5*1024*1024;
  const MAX_RETRY=3;                          // 每片最多重试 3 次（合计 4 次尝试）
  const CHUNK_CONCURRENCY=3;
  const resumeKey=resumeStorageKey(file);
  let uploadId=LS.getItem(resumeKey);
  if(!/^[a-f0-9]{32}$/.test(uploadId||''))uploadId=makeUploadId(crypto);
  LS.setItem(resumeKey,uploadId);
  uploadState.uploadId=uploadId;uploadState.resumeKey=resumeKey;
  const total=Math.max(1, Math.ceil(file.size/CHUNK));
  const baseLabel = uploadState.label;         // 保留 pickVideo 设的原始标签
  const frac = new Array(total).fill(0);       // 每片已上传比例，用于并发进度合算
  const reportProgress = () => {
    if(!onProgress) return;
    const sum = frac.reduce((a,b)=>a+b, 0);
    onProgress(Math.min(99, Math.round(sum / total * 100)));
  };
  const clearResume=()=>{LS.removeItem(resumeKey);uploadState.uploadId='';uploadState.resumeKey='';};
  async function waitForProcessing(result){
    let latest=result||{};
    let item=((latest.items||[])[0])||{};
    let processingState=item.processingState||'';
    if(processingState!=='pending'&&processingState!=='processing'){
      clearResume();onProgress&&onProgress(100);return latest;
    }
    uploadState.cancellable=false;uploadState.pct=99;uploadState.label=file.name+' (视频处理中)';
    const query='?filename='+encodeURIComponent(file.name)+'&fileSize='+encodeURIComponent(file.size)+'&total='+encodeURIComponent(total);
    for(let attempt=0;attempt<600;attempt++){
      await new Promise(r=>setTimeout(r,1000));
      try{
        const status=await API.get('/upload/status/'+encodeURIComponent(uploadId)+query);
        if(status&&status.result)latest=status.result;
      }catch(err){
        if(err&&err.status===401)throw err;
        if(err&&err.status===403)throw err;
        continue;
      }
      item=((latest.items||[])[0])||{};processingState=item.processingState||'';
      if(processingState==='ready'||processingState==='failed'){
        clearResume();onProgress&&onProgress(100);
        if(item.processingWarning)notify(item.processingWarning,processingState==='failed'?'error':'info',6000);
        return latest;
      }
    }
    notify('视频仍在后台处理中，已保留原视频地址，可稍后重新选择同一文件查询结果','info',8000);
    return latest;
  }
  let received=new Set();
  try{
    const query='?filename='+encodeURIComponent(file.name)+'&fileSize='+encodeURIComponent(file.size)+'&total='+encodeURIComponent(total);
    const status=await API.get('/upload/status/'+encodeURIComponent(uploadId)+query);
    if(status&&status.state==='completed'&&status.result){
      return await waitForProcessing(status.result);
    }
    received=new Set((status&&status.received)||[]);
    received.forEach(index=>{if(index>=0&&index<total)frac[index]=1;});
    if(received.size){uploadState.label=file.name+' (继续上传)';reportProgress();}
  }catch(err){
    if(err&&err.status===401)throw err;
    if(err&&err.status===403)throw err;
    if(uploadState.cancelled)throw _cancelErr();
    if((err&&err.status===404)||(err&&err.status===409)){
      uploadId=makeUploadId(crypto);LS.setItem(resumeKey,uploadId);uploadState.uploadId=uploadId;
    }
  }
  if(uploadState.cancelled)throw _cancelErr();

  function sendChunk(i){
    const start=i*CHUNK, end=Math.min(start+CHUNK,file.size);
    const chunk=file.slice(start,end);
    return new Promise((resolve, reject)=>{
      if(uploadState.cancelled){ reject(_cancelErr()); return; }
      const fd=new FormData();
      fd.append('file', chunk, file.name);
      fd.append('uploadId', uploadId);
      fd.append('index', String(i));
      fd.append('total', String(total));
      fd.append('filename', file.name);
      fd.append('fileSize', String(file.size));
      const xhr=new XMLHttpRequest();
      uploadState._xhrs.add(xhr);
      const done=()=>uploadState._xhrs.delete(xhr);
      xhr.open('POST','/api/upload/chunk');
      if(API.token) xhr.setRequestHeader('Authorization','Bearer '+API.token);
      xhr.upload.onprogress = e => {
        if(e.lengthComputable){ frac[i]=e.loaded/e.total; reportProgress(); }
      };
      xhr.onabort = () => { done(); const err=_cancelErr(); err.fatal=true; reject(err); };
      xhr.onload = () => {
        done();
        if(uploadState.cancelled){ const err=_cancelErr(); err.fatal=true; reject(err); return; }
        if(xhr.status>=200 && xhr.status<300){ frac[i]=1; reportProgress(); resolve(); return; }
        let d=null; try{d=JSON.parse(xhr.responseText);}catch(e){}
        const msg = (d&&d.detail) || ('分片 '+(i+1)+'/'+total+' 上传失败 '+xhr.status);
        const err = new Error(msg);
        err.status = xhr.status;
        err.fatal = (xhr.status===400 || xhr.status===401 || xhr.status===403 || xhr.status===413);
        if(xhr.status===401){API.setToken(''); err.message='登录已过期，请刷新页面重新登录';}
        if(xhr.status===403){err.message='没有上传权限（需要管理员账号）';}
        reject(err);
      };
      xhr.onerror = () => {
        done();
        if(uploadState.cancelled){ const err=_cancelErr(); err.fatal=true; reject(err); return; }
        const err = new Error('分片 '+(i+1)+'/'+total+' 网络错误');
        err.status = 0; err.fatal = false;
        reject(err);
      };
      xhr.send(fd);
    });
  }

  async function withRetry(fn, chunkIdx){
    let lastErr = null;
    for(let attempt=0; attempt<=MAX_RETRY; attempt++){
      if(uploadState.cancelled){ throw _cancelErr(); }
      if(attempt > 0){
        const delay = 1000 * Math.pow(2, attempt-1);   // 1s / 2s / 4s
        await new Promise(r=>setTimeout(r, delay));
        if(uploadState.cancelled){ throw _cancelErr(); }
      }
      try{ return await fn(); }
      catch(err){
        if(err.cancelled){ throw err; }
        console.error('分片 '+(chunkIdx+1)+' 第'+attempt+'次失败:', err.message);
        lastErr = err; frac[chunkIdx]=0;
        if(err.fatal) break;
      }
    }
    throw lastErr;
  }

  const idxs = Array.from({length:total}, (_,i)=>i).filter(index=>!received.has(index));
  await runPool(idxs, CHUNK_CONCURRENCY, i => withRetry(()=>sendChunk(i), i));

  onProgress && onProgress(99);
  uploadState.cancellable=false;
  uploadState.label=file.name+' (合并校验中)';
  // /complete 也重试；只有明确的业务错误（缺片/不支持/过大/权限）才是致命
  let completeErr = null;
  for(let attempt=0; attempt<=MAX_RETRY; attempt++){
    if(attempt > 0){
      const delay = 1000 * Math.pow(2, attempt-1);
      uploadState.label = file.name+' (合并重试 '+attempt+'/'+MAX_RETRY+'...)';
      await new Promise(r=>setTimeout(r, delay));
    }
    try{
      const r = await API.post('/upload/complete', { uploadId, total, filename: file.name, fileSize: file.size });
      uploadState.label = baseLabel;
      return await waitForProcessing(r);
    }catch(err){
      completeErr = err;
      const m = err.message || '';
      // 业务永久错误，不重试
      if(m.indexOf('缺少')>=0 || m.indexOf('不支持')>=0 || m.indexOf('过大')>=0 || m.indexOf('无效')>=0 || m.indexOf('权限')>=0){ break; }
    }
  }
  uploadState.label = baseLabel;
  throw completeErr;
}
function xhrUpload(files,onProgress){return new Promise((resolve,reject)=>{if(uploadState.cancelled){reject(_cancelErr());return;}const fd=new FormData();[...files].forEach(f=>fd.append('files',f));const xhr=new XMLHttpRequest();uploadState._xhrs.add(xhr);const done=()=>uploadState._xhrs.delete(xhr);xhr.open('POST','/api/upload');if(API.token)xhr.setRequestHeader('Authorization','Bearer '+API.token);xhr.upload.onprogress=e=>{if(e.lengthComputable&&onProgress)onProgress(Math.round(e.loaded/e.total*100));};xhr.onabort=()=>{done();reject(_cancelErr());};xhr.onload=()=>{done();if(uploadState.cancelled){reject(_cancelErr());return;}if(xhr.status>=200&&xhr.status<300){try{resolve(JSON.parse(xhr.responseText));}catch(e){resolve({});}}else{let d=null;try{d=JSON.parse(xhr.responseText);}catch(e){}console.error('上传失败',xhr.status,xhr.responseText);if(xhr.status===401){API.setToken('');reject(new Error('登录已过期，请刷新页面重新登录'));return;}if(xhr.status===403){reject(new Error('没有上传权限（需要管理员账号）'));return;}if(xhr.status===413){reject(new Error((d&&d.detail)||'文件太大，被服务器/反向代理拒绝（请检查 Nginx/Caddy 的 client_max_body_size 或 request_body max_size 配置）'));return;}reject(new Error((d&&d.detail)||('上传失败 '+xhr.status+(xhr.responseText?'：'+xhr.responseText.slice(0,200):''))));}};xhr.onerror=()=>{done();if(uploadState.cancelled){reject(_cancelErr());return;}console.error('xhrUpload network error',xhr);reject(new Error('网络错误（服务器可能未启动或无法访问）'));};xhr.send(fd);});}
function pickFile(cb){const i=document.createElement('input');i.type='file';i.accept='image/*,video/*';i.onchange=async e=>{let f=e.target.files[0];if(!f)return;f=await shrinkImage(f);const kind=detectFileKind(f,IMG_EXT,VID_EXT);const v=validateUploadFile(f,state.db&&state.db.limits,UPLOAD_LIMITS_DEFAULT,IMG_EXT,VID_EXT);if(!v.ok){alert(v.msg);return;}uploadState.cancelled=false;uploadState.cancellable=true;uploadState.active=true;uploadState.pct=0;uploadState.label=f.name;uploadState.index=1;uploadState.total=1;let r=null;try{r=kind==='video'?await xhrUploadChunked(f,p=>uploadState.pct=p):await xhrUpload([f],p=>uploadState.pct=p);}catch(err){uploadState.active=false;if(err.cancelled){return;}console.error('pickFile upload failed',err);alert('上传失败：'+err.message);return;}uploadState.active=false;try{cb(r.url);}catch(err){console.error('pickFile callback failed',err);alert('上传成功但处理失败：'+err.message);}};i.click();}
function pickFiles(cb){const i=document.createElement('input');i.type='file';i.accept='image/*,video/*';i.multiple=true;i.onchange=async e=>{
  const raw=[...e.target.files];if(!raw.length)return;
  // 纯图片批量保持 4 并发；包含视频时改为串行并统一走分片与兼容处理，避免共享状态互相覆盖。
  // 图片先客户端压缩；结果按原索引暂存，全部结束后再按序回调，保证相册/日记里的顺序不乱
  const MEDIA_CONCURRENCY=raw.some(file=>detectFileKind(file,IMG_EXT,VID_EXT)==='video')?1:4;
  uploadState.cancelled=false;uploadState.cancellable=true;uploadState.active=true;uploadState.total=raw.length;uploadState.index=0;uploadState.pct=0;
  const failed=[];const results=new Array(raw.length).fill(null);let doneCount=0;let cancelled=false;
  try{
    await runPool(raw, MEDIA_CONCURRENCY, async (file, idx)=>{
      if(uploadState.cancelled){ cancelled=true; throw _cancelErr(); }
      let f=file; uploadState.label=f.name;
      try{ f=await shrinkImage(f); }catch(e){/* 压缩失败就用原图 */}
      if(uploadState.cancelled){ cancelled=true; throw _cancelErr(); }
      const kind=detectFileKind(f,IMG_EXT,VID_EXT);const v=validateUploadFile(f,state.db&&state.db.limits,UPLOAD_LIMITS_DEFAULT,IMG_EXT,VID_EXT); if(!v.ok){ failed.push(f.name+'（'+v.msg+'）'); return; }
      let r=null;
      try{uploadState.cancellable=true;r=kind==='video'?await xhrUploadChunked(f,p=>uploadState.pct=p):await xhrUpload([f]);}
      catch(err){ if(err.cancelled){ cancelled=true; throw err; } console.error('pickFiles item failed',f.name,err); failed.push(f.name+'（'+err.message+'）'); return; }
      results[idx]=r.url;
      doneCount++; uploadState.index=doneCount; uploadState.pct=Math.round(doneCount/raw.length*100);
    });
  }catch(err){ if(!err.cancelled){ console.error('pickFiles pool error',err); } }
  // 按原始顺序回调，保持相册/日记内的排序
  let saved=0;
  results.forEach((url,idx)=>{ if(url==null)return; try{ cb(url); saved++; }catch(err){ console.error('pickFiles callback failed',raw[idx]&&raw[idx].name,err); failed.push((raw[idx]&&raw[idx].name||'文件')+'（保存失败：'+err.message+'）'); } });
  uploadState.active=false;
  if(cancelled){ alert('已取消上传（已完成的 '+saved+' 张已保留）'); return; }
  if(failed.length)alert('以下 '+failed.length+' / '+raw.length+' 个文件上传失败：\n'+failed.join('\n'));
};i.click();}
const ADMIN_TABS=[['overview','概览','📊'],['baby','宝贝信息','👶'],['milestones','里程碑','✨'],['albums','相册','📷'],['videos','成长视频','🎬'],['growth','身高体重','📈'],['daily','日常记录','🍼'],['vaccine','疫苗','💉'],['diary','日记','📖'],['messages','留言审核','💌'],['recap','AI 小结','📝'],['settings','显示设置','⚙️'],['members','成员管理','👥'],['invites','邀请码','🎟️']];
const adminTab=ref('overview');

/* ---------- ADMIN SHELL ---------- */
const Admin={ components:{}, setup(){
  if(!state.session.loggedIn){go('home');}
  const comp=computed(()=>({overview:'AdOverview',baby:'AdBaby',milestones:'AdMilestones',albums:'AdAlbums',videos:'AdVideos',growth:'AdGrowth',daily:'AdDaily',vaccine:'AdVaccines',diary:'AdDiary',messages:'AdMessages',recap:'AdRecaps',settings:'AdSettings',members:'AdMembers',invites:'AdInvites'}[adminTab.value]));
  const pending=computed(()=>state.db.messages.filter(m=>m.status==='pending').length);
  return {ADMIN_TABS,adminTab,comp,logout:doLogout,state,go,pending};
}, template:`
<section class="section container">
  <div class="admin">
    <aside class="card side">
      <a v-for="t in ADMIN_TABS" :key="t[0]" :class="{active:adminTab===t[0]}" @click="adminTab=t[0]">
        <span>{{t[2]}}</span>{{t[1]}}<span v-if="t[0]==='messages'&&pending" class="pill pend" style="margin-left:auto">{{pending}}</span></a>
      <a @click="go('home')" style="margin-top:8px">🏠 查看前台</a>
      <a @click="go('profile')">👤 个人资料</a>
      <a @click="logout" style="color:#e0576a">🚪 退出登录</a>
    </aside>
    <div class="admin-main"><component :is="comp"></component></div>
  </div>
</section>` };

/* ---------- ADMIN: overview ---------- */
const AdOverview={ setup(){
  const s=state.db, g=computed(()=>latestGrowth()), st=computed(()=>dailyStats());
  return {s,g,st,adminTab,ageText,daysOld,albumPhotoCount};
}, template:`
<div>
  <div class="admin-head"><h2>📊 概览</h2></div>
  <div class="stat-row" style="grid-template-columns:repeat(4,1fr)">
    <div class="card stat"><b>{{ageText(s.baby.birthday)}}</b><span>{{s.baby.name}} · 第{{daysOld(s.baby.birthday)}}天</span></div>
    <div class="card stat"><b>{{s.milestones.length}}</b><span>里程碑</span></div>
    <div class="card stat"><b>{{s.albums.reduce((total,album)=>total+albumPhotoCount(album),0)}}</b><span>照片</span></div>
    <div class="card stat"><b>{{st.totalMl}}<small>ml</small></b><span>今日奶量</span></div>
  </div>
  <div class="card" style="padding:24px;margin-top:8px">
    <h4 style="margin-bottom:14px">快捷入口</h4>
    <div style="display:flex;gap:10px;flex-wrap:wrap">
      <button class="btn ghost sm" @click="adminTab='daily'">🍼 记录喂奶</button>
      <button class="btn ghost sm" @click="adminTab='milestones'">✨ 添加里程碑</button>
      <button class="btn ghost sm" @click="adminTab='diary'">📖 写日记</button>
      <button class="btn ghost sm" @click="adminTab='growth'">📈 记身高体重</button>
      <button class="btn ghost sm" @click="adminTab='messages'">💌 审核留言</button>
      <button class="btn ghost sm" @click="adminTab='settings'">⚙️ 显示设置</button>
    </div>
  </div>
</div>` };

/* ---------- ADMIN: baby ---------- */
const AdBaby={ setup(){ const b=state.db.baby; async function save(){try{await API.put('/baby',JSON.parse(JSON.stringify(b)));alert('已保存 ✅');}catch(e){alert(e.message);}} return {b,pickFile,save}; },
 template:`
<div>
  <div class="admin-head"><h2>👶 宝贝信息</h2></div>
  <div class="card" style="padding:24px;max-width:640px">
    <div style="display:flex;gap:20px;align-items:center;margin-bottom:18px">
      <div style="width:90px;height:90px;border-radius:50%;overflow:hidden;box-shadow:var(--shadow-sm);flex:none"><img :src="b.avatar" style="width:100%;height:100%;object-fit:cover"/></div>
      <button class="btn ghost sm" @click="pickFile(u=>b.avatar=u)">上传头像</button>
    </div>
    <div class="row2"><div class="field"><label>姓名 / 昵称</label><input v-model="b.name"/></div>
      <div class="field"><label>性别</label><select v-model="b.gender"><option value="girl">女宝宝</option><option value="boy">男宝宝</option></select></div></div>
    <div class="field"><label>生日</label><input type="date" v-model="b.birthday"/></div>
    <div class="field"><label>宝贝简介</label><textarea v-model="b.bio" rows="3"></textarea></div>
    <div class="field"><label>家庭简介</label><textarea v-model="b.family" rows="2"></textarea></div>
    <button class="btn" @click="save">保存宝贝信息</button>
  </div>
</div>` };

/* ---------- ADMIN: milestones ---------- */
const AdMilestones={ setup(){
  const list=computed(()=>state.db.milestones.slice().sort((a,b)=>compareDateValues(b.date,a.date,businessClock.timeZone)));
  const editing=ref(null);
  const blank=()=>({id:'',date:todayStr(),title:'',category:'成长',desc:'',image:''});
  function open(m){editing.value=m?JSON.parse(JSON.stringify(m)):blank();}
  async function save(){const e=editing.value;if(!e.title){alert('请填写标题');return;}
    try{ if(e.id)await apiUpdate('milestones',e.id,e); else await apiCreate('milestones',e); editing.value=null; }catch(err){alert(err.message);} }
  async function del(m){if(await confirmDialog('确定删除「'+m.title+'」？')){try{await apiDelete('milestones',m.id);}catch(err){alert(err.message);}}}
  function pickImg(){const t=editing.value;if(!t)return;pickFile(u=>{if(editing.value===t)t.image=u;});}
  return {list,editing,open,save,del,fmtDate,pickImg};
}, template:`
<div>
  <div class="admin-head"><h2>✨ 里程碑管理</h2><button class="btn" @click="open()">+ 新增里程碑</button></div>
  <div class="list-row" v-for="m in list" :key="m.id">
    <div class="thumb" :style="{backgroundImage:'url('+m.image+')'}"></div>
    <div class="grow"><b>{{m.title}}</b><small>{{fmtDate(m.date)}} · {{m.category}}</small></div>
    <button class="btn gray sm" @click="open(m)">编辑</button><button class="btn danger sm" @click="del(m)">删除</button>
  </div>
  <div class="modal-bg" v-if="editing" @click.self="editing=null"><div class="card modal">
    <h3>{{editing.id?'编辑':'新增'}}里程碑</h3>
    <div class="row2"><div class="field"><label>日期</label><input type="date" v-model="editing.date"/></div>
      <div class="field"><label>分类</label><input v-model="editing.category" placeholder="如 大动作/语言/饮食"/></div></div>
    <div class="field"><label>标题</label><input v-model="editing.title"/></div>
    <div class="field"><label>描述</label><textarea v-model="editing.desc" rows="3"></textarea></div>
    <div class="field"><label>配图</label>
      <div style="display:flex;gap:10px;align-items:center"><input v-model="editing.image" placeholder="图片URL或上传"/><button class="btn ghost sm" @click="pickImg">上传</button></div>
      <video v-if="editing.image&&isVideo(editing.image)" :src="editing.image" controls style="margin-top:10px;border-radius:12px;max-height:150px;max-width:100%"></video><img v-else-if="editing.image" :src="editing.image" style="margin-top:10px;border-radius:12px;max-height:150px"/></div>
    <div style="display:flex;gap:10px;justify-content:flex-end"><button class="btn gray" @click="editing=null">取消</button><button class="btn" @click="save">保存</button></div>
  </div></div>
</div>` };

/* ---------- ADMIN: albums ---------- */
const AdAlbums={ setup(){
  const pager=makeAdminHistoryPager('albums');
  const albums=computed(()=>pager.items);
  const editing=ref(null);const editingLoading=ref(false);
  const blank=()=>({id:'',name:'',date:todayStr(),desc:'',cover:'',photos:[]});
  async function open(a){if(!a){editing.value=blank();return;}editingLoading.value=true;try{const detail=await ensureAlbumLoaded(a.id);editing.value=cloneData(detail);}catch(err){alert(err.message||'相册详情加载失败');}finally{editingLoading.value=false;}}
  async function save(){const e=editing.value;if(!e.name){alert('请填写相册名');return;}
    if(!e.cover&&e.photos[0])e.cover=e.photos[0].url;
    try{if(e.id)await apiUpdate('albums',e.id,e);else await apiCreate('albums',e);}catch(err){alert(err.message);return;}editing.value=null;try{await pager.refreshAfterMutation();}catch(err){} }
  async function del(a){if(await confirmDialog('删除相册「'+a.name+'」？')){try{await apiDelete('albums',a.id);await pager.refreshAfterMutation();}catch(err){alert(err.message);}}}
  function addPhotos(){const t=editing.value;if(!t)return;pickFiles(u=>{if(editing.value!==t)return;if(!Array.isArray(t.photos))t.photos=[];t.photos.push({id:uid(),url:u,caption:'',takenAt:t.date||''});});}
  function addByUrl(){const t=editing.value;if(!t)return;const u=prompt('输入图片URL');if(!u||editing.value!==t)return;if(!Array.isArray(t.photos))t.photos=[];t.photos.push({id:uid(),url:u,caption:'',takenAt:t.date||''});}
  function pickCover(){const t=editing.value;if(!t)return;pickFile(u=>{if(editing.value===t)t.cover=u;});}
  function delPhoto(p){editing.value.photos=editing.value.photos.filter(x=>x.id!==p.id);}
  const shareA=ref(null); const shareDays=ref(7); const shareUrl=ref(''); const shareExp=ref('');
  const shareLink=tok=>location.origin+location.pathname+'#share/'+tok;
  const shareText=e=>e?('有效期至 '+fmtDate(e)):'永久有效';
  async function openShare(a){shareA.value=a;shareUrl.value='';shareExp.value='';shareDays.value=7;try{const sh=await API.get('/albums/'+a.id+'/share');if(sh&&sh.token){shareUrl.value=shareLink(sh.token);shareExp.value=shareText(sh.expiresAt);}}catch(e){}}
  async function makeShare(){try{const sh=await API.post('/albums/'+shareA.value.id+'/share',{days:shareDays.value||null});shareUrl.value=shareLink(sh.token);shareExp.value=shareText(sh.expiresAt);}catch(e){alert(e.message);}}
  async function revokeShare(){try{await API.del('/albums/'+shareA.value.id+'/share');shareUrl.value='';shareExp.value='';}catch(e){alert(e.message);}}
  function copyShare(){if(navigator.clipboard)navigator.clipboard.writeText(shareUrl.value);alert('已复制链接');}
  async function load(offset=pager.offset){try{await pager.load(offset);}catch(e){}}
  onMounted(()=>load(0));
  return {albums,pager,editing,editingLoading,open,save,del,addPhotos,addByUrl,delPhoto,fmtDate,pickCover,shareA,shareDays,shareUrl,shareExp,openShare,makeShare,revokeShare,copyShare,albumPhotoCount,load};
}, template:`
<div>
  <div class="admin-head"><h2>📷 相册管理</h2><button class="btn" :disabled="pager.loading||editingLoading" @click="open()">+ 新建相册</button></div>
  <p v-if="pager.loading" class="history-status">正在加载相册记录…</p>
  <p v-else-if="pager.loadError" class="history-status error">{{pager.loadError}} <button class="btn ghost sm" @click="load()">重试</button></p>
  <div class="list-row" v-for="a in albums" :key="a.id">
    <div class="thumb" :style="{backgroundImage:'url('+a.cover+')'}"></div>
    <div class="grow"><b>{{a.name}}</b><small>{{fmtDate(a.date)}} · {{albumPhotoCount(a)}} 张照片</small></div>
    <button class="btn ghost sm" :disabled="pager.loading" @click="openShare(a)">🔗 分享</button><button class="btn gray sm" :disabled="pager.loading||editingLoading" @click="open(a)">编辑</button><button class="btn danger sm" :disabled="pager.loading" @click="del(a)">删除</button>
  </div>
  <HistoryPager :pager="pager"/>
  <div class="modal-bg" v-if="shareA" @click.self="shareA=null"><div class="card modal">
    <h3>🔗 分享「{{shareA.name}}」</h3>
    <p style="color:var(--c-muted)">生成一个免登录的对外链接，家人无需注册即可查看这一本相册。</p>
    <div class="field"><label>有效期</label><div class="yr-filter" style="margin:0"><button :class="{on:shareDays===7}" @click="shareDays=7">7 天</button><button :class="{on:shareDays===30}" @click="shareDays=30">30 天</button><button :class="{on:shareDays===0}" @click="shareDays=0">永久</button></div></div>
    <button class="btn" @click="makeShare">生成 / 更新链接</button>
    <div v-if="shareUrl" style="margin-top:14px">
      <div class="field" style="margin:0"><label>分享链接</label><div style="display:flex;gap:8px"><input :value="shareUrl" readonly style="font-size:.82rem"/><button class="btn ghost sm" @click="copyShare">复制</button></div></div>
      <p style="color:var(--c-muted);font-size:.82rem;margin-top:6px">{{shareExp}}</p>
      <button class="btn danger sm" @click="revokeShare">撤销分享</button>
    </div>
    <div style="display:flex;justify-content:flex-end;margin-top:14px"><button class="btn gray" @click="shareA=null">关闭</button></div>
  </div></div>
  <div class="modal-bg" v-if="editing" @click.self="editing=null"><div class="card modal">
    <h3>{{editing.id?'编辑':'新建'}}相册</h3>
    <div class="row2"><div class="field"><label>相册名</label><input v-model="editing.name"/></div>
      <div class="field"><label>日期</label><input type="date" v-model="editing.date"/></div></div>
    <div class="field"><label>描述</label><input v-model="editing.desc"/></div>
    <div class="field"><label>封面</label><div style="display:flex;gap:10px;align-items:center"><input v-model="editing.cover" placeholder="留空则用第一张照片"/><button class="btn ghost sm" @click="pickCover">上传</button></div></div>
    <div class="field"><label>照片（{{editing.photos.length}}）</label>
      <div style="display:flex;gap:8px;margin-bottom:10px"><button class="btn ghost sm" @click="addPhotos">📁 批量上传</button><button class="btn ghost sm" @click="addByUrl">🔗 用URL添加</button></div>
      <div class="grid" style="grid-template-columns:repeat(4,1fr);gap:8px">
        <div v-for="p in editing.photos" :key="p.id" style="position:relative;aspect-ratio:1;border-radius:10px;overflow:hidden;background:#f3e7e2">
          <MediaThumb :url="p.url"/><button @click="delPhoto(p)" style="position:absolute;top:2px;right:2px;z-index:2;background:rgba(0,0,0,.6);color:#fff;width:22px;height:22px;border-radius:50%">✕</button></div>
      </div></div>
    <div style="display:flex;gap:10px;justify-content:flex-end"><button class="btn gray" @click="editing=null">取消</button><button class="btn" @click="save">保存</button></div>
  </div></div>
</div>` };
/* ---------- ADMIN: growth ---------- */
const AdGrowth={ setup(){
  const rows=computed(()=>sortedGrowth().reverse());
  const f=reactive({date:todayStr(),height:'',weight:'',head:''});
  async function add(){if(!f.height&&!f.weight){alert('请填写身高或体重');return;}
    try{ await apiCreate('growth',{date:f.date,height:+f.height||null,weight:+f.weight||null,head:+f.head||null}); f.height=f.weight=f.head=''; }catch(err){alert(err.message);} }
  async function del(x){if(await confirmDialog('删除该条记录？')){try{await apiDelete('growth',x.id);}catch(err){alert(err.message);}}}
  return {rows,f,add,del,fmtDate};
}, template:`
<div>
  <div class="admin-head"><h2>📈 身高体重管理</h2></div>
  <div class="card" style="padding:18px;margin-bottom:18px">
    <div class="row2" style="grid-template-columns:repeat(4,1fr) auto;align-items:end;gap:12px">
      <div class="field" style="margin:0"><label>日期</label><input type="date" v-model="f.date"/></div>
      <div class="field" style="margin:0"><label>身高 cm</label><input type="number" v-model="f.height"/></div>
      <div class="field" style="margin:0"><label>体重 kg</label><input type="number" step="0.1" v-model="f.weight"/></div>
      <div class="field" style="margin:0"><label>头围 cm</label><input type="number" step="0.1" v-model="f.head"/></div>
      <button class="btn" @click="add">+ 添加</button>
    </div>
  </div>
  <div class="card" style="padding:8px 4px;overflow:auto"><table class="tbl"><thead><tr><th>日期</th><th>身高</th><th>体重</th><th>头围</th><th></th></tr></thead>
    <tbody><tr v-for="x in rows" :key="x.id"><td>{{fmtDate(x.date)}}</td><td>{{x.height||'—'}}</td><td>{{x.weight||'—'}}</td><td>{{x.head||'—'}}</td>
    <td><button class="btn danger sm" @click="del(x)">删除</button></td></tr></tbody></table></div>
</div>` };

/* ---------- ADMIN: daily ---------- */
const AdDaily={ setup(){
  const pager=makeAdminHistoryPager('daily');
  const logs=computed(()=>pager.items);
  const st=computed(()=>dailyStats());
  const amt=ref(state.db.settings.feeding.defaultAmount), ftype=ref('formula');
  const feedTime=value=>formatBusinessDateTime(value,businessClock.timeZone);
  async function feed(){try{await apiCreate('daily',{type:'feeding',feedType:ftype.value,amount:+amt.value||null,time:businessClock.now().toISOString(),note:''});await pager.refreshAfterMutation();}catch(err){alert(err.message);}}
  async function diaper(t){try{await apiCreate('daily',{type:'diaper',diaperType:t,time:businessClock.now().toISOString(),note:''});await pager.refreshAfterMutation();}catch(err){alert(err.message);}}
  async function del(x){try{await apiDelete('daily',x.id);await pager.refreshAfterMutation();}catch(err){alert(err.message);}}
  async function load(offset=pager.offset){try{await pager.load(offset);}catch(e){}}
  onMounted(()=>load(0));
  return {logs,pager,st,amt,ftype,feed,diaper,del,feedTime,load};
}, template:`
<div>
  <div class="admin-head"><h2>🍼 日常记录管理</h2></div>
  <p v-if="pager.loading" class="history-status">正在加载日常记录…</p>
  <p v-else-if="pager.loadError" class="history-status error">{{pager.loadError}} <button class="btn ghost sm" @click="load()">重试</button></p>
  <div class="card" style="padding:20px;margin-bottom:16px">
    <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:center">
      <label style="font-weight:600">喂奶</label>
      <input type="number" v-model="amt" style="width:90px;padding:9px;border:1.5px solid var(--c-line);border-radius:10px"/> ml
      <select v-model="ftype" style="padding:9px;border:1.5px solid var(--c-line);border-radius:10px"><option value="formula">配方奶</option><option value="breast">母乳</option></select>
      <button class="btn sm" :disabled="pager.loading||!!pager.loadError" @click="feed">🍼 记一次喂奶</button>
      <span style="width:1px;height:26px;background:var(--c-line)"></span>
      <button class="btn ghost sm" :disabled="pager.loading||!!pager.loadError" @click="diaper('pee')">💧 小便</button>
      <button class="btn ghost sm" :disabled="pager.loading||!!pager.loadError" @click="diaper('poop')">💩 大便</button>
    </div>
    <p style="color:var(--c-muted);margin-top:12px;font-size:.9rem">今日：喂奶 {{st.feeds.length}} 次 / {{st.totalMl}}ml · 小便 {{st.pee}} · 大便 {{st.poop}}</p>
  </div>
  <div class="log" v-for="l in logs" :key="l.id">
    <div class="ic" :class="l.type==='feeding'?'feed':(l.diaperType==='poop'?'poop':'pee')">{{l.type==='feeding'?'🍼':(l.diaperType==='poop'?'💩':'💧')}}</div>
    <div class="grow"><b>{{l.type==='feeding'?('喂奶 '+(l.amount||'')+'ml'):('换尿布 · '+(l.diaperType==='poop'?'大便':'小便'))}}</b><small>{{feedTime(l.time)}}{{l.note?(' · '+l.note):''}}</small></div>
    <button class="btn danger sm" :disabled="pager.loading||!!pager.loadError" @click="del(l)">删除</button>
  </div>
  <HistoryPager :pager="pager"/>
</div>` };

/* ---------- ADMIN: diary ---------- */
const AdDiary={ setup(){
  const pager=makeAdminHistoryPager('diary');
  const list=computed(()=>pager.items);
  const editing=ref(null);
  const blank=()=>({id:'',date:todayStr(),title:'',content:'',images:[]});
  function open(d){editing.value=d?cloneData(d):blank();}
  async function save(){const e=editing.value;if(!e.title){alert('请填写标题');return;}
    try{if(e.id)await apiUpdate('diary',e.id,e);else await apiCreate('diary',e);}catch(err){alert(err.message);return;}editing.value=null;try{await pager.refreshAfterMutation();}catch(err){} }
  async function del(d){if(await confirmDialog('删除日记「'+d.title+'」？')){try{await apiDelete('diary',d.id);await pager.refreshAfterMutation();}catch(err){alert(err.message);}}}
  function addImgs(){const t=editing.value;if(!t)return;pickFiles(u=>{if(editing.value!==t)return;if(!Array.isArray(t.images))t.images=[];t.images.push(u);});}
  function addUrl(){const t=editing.value;if(!t)return;const u=prompt('图片URL');if(!u||editing.value!==t)return;if(!Array.isArray(t.images))t.images=[];t.images.push(u);}
  async function load(offset=pager.offset){try{await pager.load(offset);}catch(e){}}
  onMounted(()=>load(0));
  return {list,pager,editing,open,save,del,addImgs,addUrl,fmtDate,load};
}, template:`
<div>
  <div class="admin-head"><h2>📖 日记管理</h2><button class="btn" :disabled="pager.loading||!!pager.loadError" @click="open()">+ 写日记</button></div>
  <p v-if="pager.loading" class="history-status">正在加载日记记录…</p>
  <p v-else-if="pager.loadError" class="history-status error">{{pager.loadError}} <button class="btn ghost sm" @click="load()">重试</button></p>
  <div class="list-row" v-for="d in list" :key="d.id">
    <div class="thumb" :style="{backgroundImage:'url('+(d.images&&d.images[0]||'')+')'}"></div>
    <div class="grow"><b>{{d.title}}</b><small>{{fmtDate(d.date)}} · {{d.content.slice(0,30)}}…</small></div>
    <button class="btn gray sm" :disabled="pager.loading" @click="open(d)">编辑</button><button class="btn danger sm" :disabled="pager.loading||!!pager.loadError" @click="del(d)">删除</button>
  </div>
  <HistoryPager :pager="pager"/>
  <div class="modal-bg" v-if="editing" @click.self="editing=null"><div class="card modal">
    <h3>{{editing.id?'编辑':'新写'}}日记</h3>
    <div class="row2"><div class="field"><label>日期</label><input type="date" v-model="editing.date"/></div>
      <div class="field"><label>标题</label><input v-model="editing.title"/></div></div>
    <div class="field"><label>正文</label><textarea v-model="editing.content" rows="6"></textarea></div>
    <div class="field"><label>配图（{{editing.images.length}}）</label>
      <div style="display:flex;gap:8px;margin-bottom:8px"><button class="btn ghost sm" @click="addImgs">📁 上传</button><button class="btn ghost sm" @click="addUrl">🔗 URL</button></div>
      <div class="grid" style="grid-template-columns:repeat(4,1fr);gap:8px"><div v-for="(im,i) in editing.images" :key="i" style="position:relative;aspect-ratio:1;border-radius:10px;overflow:hidden;background:#f3e7e2"><MediaThumb :url="im"/><button @click="editing.images.splice(i,1)" style="position:absolute;top:2px;right:2px;z-index:2;background:rgba(0,0,0,.6);color:#fff;width:22px;height:22px;border-radius:50%">✕</button></div></div></div>
    <div style="display:flex;gap:10px;justify-content:flex-end"><button class="btn gray" @click="editing=null">取消</button><button class="btn" @click="save">保存</button></div>
  </div></div>
</div>` };

/* ---------- ADMIN: messages ---------- */
const AdMessages={ setup(){
  const pending=computed(()=>state.db.messages.filter(m=>m.status==='pending'));
  const approved=computed(()=>state.db.messages.filter(m=>m.status==='approved'));
  async function approve(m){try{const r=await API.post('/messages/'+m.id+'/approve');const i=state.db.messages.findIndex(x=>x.id===m.id);if(i>=0&&r&&r.id!=null)state.db.messages.splice(i,1,r);else await refresh();}catch(err){alert(err.message);}}
  async function del(m){if(await confirmDialog('删除该留言？')){try{await API.del('/messages/'+m.id);const i=state.db.messages.findIndex(x=>x.id===m.id);if(i>=0)state.db.messages.splice(i,1);else await refresh();}catch(err){alert(err.message);}}}
  return {pending,approved,approve,del,fmtMD};
}, template:`
<div>
  <div class="admin-head"><h2>💌 留言审核</h2></div>
  <h4 style="margin-bottom:10px">待审核 <span class="pill pend">{{pending.length}}</span></h4>
  <p v-if="!pending.length" style="color:var(--c-muted);margin-bottom:20px">暂无待审核留言</p>
  <div class="list-row" v-for="m in pending" :key="m.id">
    <span class="av" :style="{background:m.color,width:'42px',height:'42px',borderRadius:'50%',display:'grid',placeItems:'center',color:'#fff',fontWeight:700}">{{m.name.slice(0,1)}}</span>
    <div class="grow"><b>{{m.name}}</b><small>{{m.content}}</small></div>
    <button class="btn sm" @click="approve(m)">✓ 通过</button><button class="btn danger sm" @click="del(m)">删除</button>
  </div>
  <h4 style="margin:24px 0 10px">已通过 <span class="pill ok">{{approved.length}}</span></h4>
  <div class="list-row" v-for="m in approved" :key="m.id">
    <span class="av" :style="{background:m.color,width:'42px',height:'42px',borderRadius:'50%',display:'grid',placeItems:'center',color:'#fff',fontWeight:700}">{{m.name.slice(0,1)}}</span>
    <div class="grow"><b>{{m.name}}</b><small>{{m.content}}</small></div>
    <button class="btn danger sm" @click="del(m)">删除</button>
  </div>
</div>` };

/* ---------- ADMIN: settings ---------- */
const THEMES=[{name:'甜心粉',primary:'#ec8aa0',primaryD:'#d75f7e',secondary:'#7fc6d0',accent:'#ffc178',bg:'#fff6f3'},
{name:'天空蓝',primary:'#5aa8dd',primaryD:'#2f7fb8',secondary:'#8fd0c4',accent:'#ffcf87',bg:'#f1f8ff'},
{name:'薄荷绿',primary:'#5ebd8a',primaryD:'#2f9d68',secondary:'#86c6d6',accent:'#ffc178',bg:'#f2fbf6'},
{name:'奶油黄',primary:'#eaad4a',primaryD:'#c6862a',secondary:'#7fc6c0',accent:'#ef8fa4',bg:'#fffdf3'},
{name:'薰衣紫',primary:'#9a83d6',primaryD:'#6f52b8',secondary:'#9ec7de',accent:'#f3a0be',bg:'#f7f4ff'}];
const MODNAMES={timeline:'成长时间线',gallery:'照片画廊',growth:'成长曲线',vaccine:'疫苗接种',daily:'日常记录',diary:'成长日记',messages:'留言墙',videos:'成长视频',about:'关于'};
const HOMENAMES={hero:'Hero 首屏',countdown:'纪念日倒计时',onthisday:'那年今天',carousel:'照片轮播',milestones:'最近里程碑',growth:'成长概览',videos:'最新视频',diary:'日记入口',recap:'成长小结',vaccine:'疫苗提醒'};
const AdSettings={ components:{Toggle}, setup(){
  const s=state.db.settings;
  const emojiStr=ref(s.deco.emoji.join(' '));
  const backups=ref([]);
  const cleanupPreview=ref(null);
  const busy=key=>pendingActions.has(key);
  function applyPreset(t){Object.assign(s.theme,t);applyTheme();}
  function onColor(){applyTheme();}
  function onDeco(){s.deco.emoji=emojiStr.value.split(/[\s,，]+/).filter(Boolean);applyTheme();}
  const photoCount=computed(()=>{let n=0;state.db.albums.forEach(a=>n+=albumPhotoCount(a));return n+state.db.diary.reduce((x,d)=>x+diaryImageCount(d),0)+state.db.milestones.filter(m=>m.image).length;});
  async function reset(){if(await confirmDialog('确定恢复示例数据？当前所有数据将被覆盖！')){try{await reseed();adminTab.value='overview';go('home');}catch(e){alert(e.message);}}}
  async function save(){try{const payload=JSON.parse(JSON.stringify(s));const saved=await runAction('settings:save',()=>API.put('/settings',payload));if(saved&&saved.ai){s.ai.apiKey='';s.ai.apiKeyConfigured=!!saved.ai.apiKeyConfigured;s.ai.clearApiKey=false;s.ai.enabled=!!saved.ai.enabled;}alert('设置已保存 ✅');}catch(e){alert(e.message);}}
  async function exportData(){try{const d=await API.get('/export');const blob=new Blob([JSON.stringify(d,null,2)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='baby-growth-backup-'+todayStr()+'.json';document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(a.href);}catch(e){alert(e.message);}}
  function importData(){const i=document.createElement('input');i.type='file';i.accept='application/json,.json';i.onchange=async e=>{const f=e.target.files[0];if(!f)return;try{const data=JSON.parse(await f.text());const preview=await API.post('/import/validate',data);const summary=preview.summary||{};const msg='预检通过：相册 '+(summary.albums||0)+' 个、照片 '+(summary.photos||0)+' 项、日常记录 '+(summary.daily||0)+' 条。\n导入前会自动创建完整备份，并撤销旧相册分享链接，确定继续？';if(!await confirmDialog(msg))return;const result=await runAction('import:apply',()=>API.post('/import?confirm=true',data));await refresh();await loadBackups();alert('导入成功，操作前备份：'+result.backupId);}catch(err){alert('导入失败：'+err.message);}};i.click();}
  async function loadBackups(){try{backups.value=await API.get('/backups');}catch(e){backups.value=[];}}
  async function createBackup(){try{const b=await runAction('backup:create',()=>API.post('/backups',{reason:'manual'}));await loadBackups();alert('完整备份已创建：'+b.backupId);}catch(e){alert('备份失败：'+e.message);}}
  function downloadBackup(b){const a=document.createElement('a');a.href='/api/backups/'+encodeURIComponent(b.backupId)+'/download';a.download='';document.body.appendChild(a);a.click();a.remove();}
  async function removeBackup(b){if(!await confirmDialog('删除备份 '+b.backupId+'？'))return;try{await runAction('backup:delete:'+b.backupId,()=>API.del('/backups/'+encodeURIComponent(b.backupId)));await loadBackups();}catch(e){alert(e.message);}}
  async function previewMediaCleanup(){try{cleanupPreview.value=await runAction('media:preview',()=>API.post('/media/cleanup/preview',{olderThanHours:24}));if(!(cleanupPreview.value.orphanFiles+cleanupPreview.value.temporaryFiles))alert('没有发现可清理的媒体文件。');}catch(e){alert('扫描失败：'+e.message);}}
  async function executeMediaCleanup(){const p=cleanupPreview.value;if(!p)return;const count=(p.orphanFiles||0)+(p.temporaryFiles||0);if(!count){cleanupPreview.value=null;return;}const msg='将删除 '+count+' 个未引用或过期临时文件，预计释放 '+fmtBytes((p.orphanBytes||0)+(p.temporaryBytes||0))+'。\n清理前会自动创建完整备份，确定继续？';if(!await confirmDialog(msg))return;try{const result=await runAction('media:cleanup',()=>API.post('/media/cleanup',{olderThanHours:24,confirmToken:p.confirmToken}));cleanupPreview.value=null;await loadBackups();alert('媒体清理完成：删除 '+result.deletedFiles+' 个文件，释放 '+fmtBytes(result.releasedBytes)+(result.backupId?'，备份 '+result.backupId:''));}catch(e){alert('清理失败：'+e.message);}}
  function fmtBytes(n){n=+n||0;if(n<1024)return n+' B';if(n<1048576)return (n/1024).toFixed(1)+' KB';if(n<1073741824)return (n/1048576).toFixed(1)+' MB';return (n/1073741824).toFixed(1)+' GB';}
  onMounted(loadBackups);
  async function saveFavicon(){ try{ await API.put('/settings', JSON.parse(JSON.stringify(s))); }catch(e){ alert('保存失败：'+e.message); } }
  function pickIcon(){pickFile(async u=>{s.faviconUrl=u;applyTheme();await saveFavicon();});}
  async function resetIcon(){s.faviconUrl='';applyTheme();await saveFavicon();}
  function clearAiKey(){s.ai.apiKey='';s.ai.clearApiKey=true;s.ai.apiKeyConfigured=false;s.ai.enabled=false;}
  const FRAMES=[['polaroid','宝丽来','🎞️'],['matted','白边墙','🖼️'],['wood','复古木质','🪵'],['none','无框','⬜']];
  async function setFrame(style){ s.photoFrame=style; applyTheme(); await saveFavicon(); }
  return {s,THEMES,MODNAMES,HOMENAMES,FRAMES,applyPreset,onColor,onDeco,emojiStr,photoCount,reset,save,exportData,importData,pickIcon,resetIcon,clearAiKey,setFrame,DEFAULT_FAVICON,backups,cleanupPreview,busy,createBackup,downloadBackup,removeBackup,previewMediaCleanup,executeMediaCleanup,fmtBytes,fmtDate};
}, template:`
<div>
  <div class="admin-head"><h2>⚙️ 显示设置</h2><button class="btn" :disabled="busy('settings:save')" @click="save">{{busy('settings:save')?'保存中…':'保存设置'}}</button></div>
  <div class="card" style="padding:22px;margin-bottom:16px">
    <h4 style="margin-bottom:12px">🎨 主题配色</h4>
    <div class="swatch" style="margin-bottom:16px"><button v-for="t in THEMES" :key="t.name" :title="t.name" :class="{on:s.theme.name===t.name}" :style="{background:'linear-gradient(135deg,'+t.primary+','+t.accent+')'}" @click="applyPreset(t)"></button></div>
    <div class="row2"><div class="field"><label>主色</label><input type="color" v-model="s.theme.primary" @input="onColor"/></div>
      <div class="field"><label>主色(深)</label><input type="color" v-model="s.theme.primaryD" @input="onColor"/></div>
      <div class="field"><label>辅色</label><input type="color" v-model="s.theme.secondary" @input="onColor"/></div>
      <div class="field"><label>点缀色</label><input type="color" v-model="s.theme.accent" @input="onColor"/></div>
      <div class="field"><label>背景色</label><input type="color" v-model="s.theme.bg" @input="onColor"/></div></div>
  </div>
  <div class="card" style="padding:22px;margin-bottom:16px">
    <h4 style="margin-bottom:6px">✨ 背景装饰</h4>
    <div class="toggle-row"><span>启用漂浮装饰</span><Toggle v-model="s.deco.enabled" label="启用漂浮装饰" @update:modelValue="onDeco"/></div>
    <div class="field" style="margin-top:14px"><label>透明度 {{Math.round(s.deco.opacity*100)}}%</label><input type="range" min="0" max="1" step="0.05" v-model.number="s.deco.opacity" @input="onDeco"/></div>
    <div class="field"><label>装饰图案（空格分隔的 Emoji）</label><input v-model="emojiStr" @change="onDeco"/></div>
  </div>
  <div class="card" style="padding:22px;margin-bottom:16px">
    <h4 style="margin-bottom:6px">🌟 网站图标（favicon）</h4>
    <p style="color:var(--c-muted);font-size:.86rem;margin-bottom:14px">浏览器标签栏、书签栏、主屏快捷方式上显示的小图标。建议正方形 PNG/SVG，尺寸 64×64 到 512×512 之间。留空则用默认 🍼。</p>
    <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">
      <img :src="s.faviconUrl||DEFAULT_FAVICON" alt="favicon 预览" style="width:64px;height:64px;border-radius:12px;border:1px solid var(--c-line);object-fit:contain;background:#fff;padding:6px"/>
      <button class="btn ghost sm" @click="pickIcon">上传自定义图标</button>
      <button class="btn ghost sm" @click="resetIcon">恢复默认 🍼</button>
    </div>
  </div>
  <div class="card" style="padding:22px;margin-bottom:16px">
    <h4 style="margin-bottom:6px">🖼️ 照片相框风格</h4>
    <p style="color:var(--c-muted);font-size:.86rem;margin-bottom:14px">选好即刻生效并自动保存。全站所有图片（首页大图/相册/时间线/日记/里程碑/视频）都用这个风格。</p>
    <div class="frame-picker">
      <button v-for="f in FRAMES" :key="f[0]" :class="{on:(s.photoFrame||'polaroid')===f[0]}" @click="setFrame(f[0])">
        <span class="preview" :class="'preview-'+f[0]"></span>
        <span class="lbl">{{f[2]}} {{f[1]}}</span>
      </button>
    </div>
  </div>
  <div class="row2" style="align-items:start">
    <div class="card" style="padding:22px"><h4 style="margin-bottom:6px">🧩 功能模块开关</h4>
      <div class="toggle-row" v-for="(nm,k) in MODNAMES" :key="k"><span>{{nm}}</span><Toggle v-model="s.modules[k]" :label="nm"/></div></div>
    <div class="card" style="padding:22px"><h4 style="margin-bottom:6px">🏠 首页区块开关</h4>
      <div class="toggle-row" v-for="(nm,k) in HOMENAMES" :key="k"><span>{{nm}}</span><Toggle v-model="s.home[k]" :label="nm"/></div></div>
  </div>
  <div class="card" style="padding:22px;margin-top:16px"><h4 style="margin-bottom:12px">🍼 喂奶默认参数</h4>
    <div class="row2"><div class="field"><label>默认单次奶量 (ml)</label><input type="number" v-model.number="s.feeding.defaultAmount"/></div>
      <div class="field"><label>预计每日奶量 (ml)</label><input type="number" v-model.number="s.feeding.dailyTarget"/></div></div></div>
  <div class="card" style="padding:22px;margin-top:16px"><h4 style="margin-bottom:6px">🤖 AI 助手（可选大模型）</h4>
    <p style="color:var(--c-muted);font-size:.86rem;margin-bottom:12px">不填则使用内置指令助手（免费）。已保存密钥只保留在服务器，页面仅显示配置状态；输入新密钥会替换旧值。</p>
    <div class="toggle-row"><span>启用大模型自然语言对话</span><Toggle v-model="s.ai.enabled" label="启用大模型自然语言对话"/></div>
    <div class="field" style="margin-top:12px"><label>API Key <span v-if="s.ai.apiKeyConfigured" class="pill ok">已保存密钥</span></label><div style="display:flex;gap:8px;align-items:center"><input v-model="s.ai.apiKey" type="password" :placeholder="s.ai.apiKeyConfigured?'留空保留已保存密钥':'sk-...'" @input="s.ai.clearApiKey=false"/><button v-if="s.ai.apiKeyConfigured" class="btn danger sm" @click="clearAiKey">清除密钥</button></div></div>
    <div class="row2"><div class="field"><label>Base URL</label><input v-model="s.ai.baseUrl"/></div>
      <div class="field"><label>模型</label><input v-model="s.ai.model"/></div></div></div>
  <div class="card" style="padding:22px;margin-top:16px"><h4 style="margin-bottom:6px">🔐 管理员账号</h4>
    <p style="color:var(--c-muted);font-size:.9rem">管理员账号由首次部署配置创建。后续密码请在“个人资料”中修改；修改后其他设备的旧会话会立即失效。</p></div>
  <div class="card" style="padding:22px;margin-top:16px"><h4 style="margin-bottom:6px">🗂️ 文件与数据</h4>
    <p style="color:var(--c-muted);font-size:.9rem;margin-bottom:12px">当前约 {{photoCount}} 张图片引用 · 数据与图片保存在服务器（SQLite 数据库 + uploads 目录）</p>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px">
      <button class="btn sm" :disabled="busy('backup:create')" @click="createBackup">{{busy('backup:create')?'创建中…':'🛡️ 创建完整备份'}}</button>
      <button class="btn ghost sm" @click="exportData">⬇️ 导出数据(JSON)</button>
      <button class="btn ghost sm" :disabled="busy('import:apply')" @click="importData">{{busy('import:apply')?'导入中…':'⬆️ 导入恢复'}}</button>
      <button class="btn ghost sm" :disabled="busy('media:preview')" @click="previewMediaCleanup">{{busy('media:preview')?'扫描中…':'🧹 扫描未引用媒体'}}</button>
    </div>
    <div v-if="cleanupPreview" class="list-row" style="padding:10px 0;margin-bottom:10px">
      <div class="grow"><b>媒体清理预览</b><small>未引用 {{cleanupPreview.orphanFiles||0}} 个 · 临时 {{cleanupPreview.temporaryFiles||0}} 个 · 可释放 {{fmtBytes((cleanupPreview.orphanBytes||0)+(cleanupPreview.temporaryBytes||0))}}<template v-if="cleanupPreview.missingReferences"> · 缺失引用 {{cleanupPreview.missingReferences}} 个</template></small></div>
      <button class="btn danger sm" :disabled="busy('media:cleanup')||!((cleanupPreview.orphanFiles||0)+(cleanupPreview.temporaryFiles||0))" @click="executeMediaCleanup">{{busy('media:cleanup')?'清理中…':'确认清理'}}</button>
    </div>
    <p style="color:var(--c-muted);font-size:.78rem;margin:0 0 12px">完整备份包含 SQLite 和上传文件，自动保留最近 2 份。JSON 导入会先预检并创建完整备份。</p>
    <div class="list-row" v-for="b in backups" :key="b.backupId" style="padding:10px 0">
      <div class="grow"><b>{{b.reason||'manual'}}</b><small>{{fmtDate(b.createdAt)}} · {{fmtBytes(b.bytes)}} · {{b.uploadFiles||0}} 个上传文件</small></div>
      <button class="btn ghost sm" @click="downloadBackup(b)">下载</button><button class="btn danger sm" :disabled="busy('backup:delete:'+b.backupId)" @click="removeBackup(b)">{{busy('backup:delete:'+b.backupId)?'删除中…':'删除'}}</button>
    </div>
    <button class="btn danger sm" :disabled="busy('admin:seed')" @click="reset">{{busy('admin:seed')?'恢复中…':'恢复示例数据（覆盖当前）'}}</button></div>
</div>` };
const AdVideos={ setup(){
  const list=computed(()=>state.db.videos||[]);
  const editing=ref(null);
  const blank=()=>({id:'',date:todayStr(),title:'',desc:'',url:'',cover:''});
  function open(v){editing.value=v?JSON.parse(JSON.stringify(v)):blank();}
  async function save(){const e=editing.value;if(!e.title||!e.url){alert('请填写标题并上传视频');return;}
    try{ if(e.id)await apiUpdate('videos',e.id,e); else await apiCreate('videos',e); editing.value=null; }catch(err){alert(err.message);} }
  async function del(v){if(await confirmDialog('删除视频「'+v.title+'」？')){try{await apiDelete('videos',v.id);}catch(err){alert(err.message);}}}
  function pickVideo(){const t=editing.value;if(!t)return;const i=document.createElement('input');i.type='file';i.accept='video/*';i.onchange=async ev=>{const f=ev.target.files[0];if(!f)return;const v=validateUploadFile(f,state.db&&state.db.limits,UPLOAD_LIMITS_DEFAULT,IMG_EXT,VID_EXT);if(!v.ok){alert(v.msg);return;}uploadState.cancelled=false;uploadState.cancellable=true;uploadState.active=true;uploadState.pct=0;uploadState.label=f.name+' (分片上传中)';uploadState.index=1;uploadState.total=1;try{const r=await xhrUploadChunked(f,p=>uploadState.pct=p);const it=(r.items&&r.items[0])||{};if(editing.value===t){t.url=it.url||r.url;if(!t.cover&&it.poster)t.cover=it.poster;}}catch(err){if(!err.cancelled){console.error('pickVideo failed',err);alert('上传失败：'+err.message);}}finally{uploadState.active=false;uploadState.cancellable=true;}};i.click();}
  function pickVideoCover(){const t=editing.value;if(!t)return;pickFile(u=>{if(editing.value===t)t.cover=u;});}
  return {list,editing,open,save,del,fmtDate,pickVideo,pickVideoCover};
}, template:`
<div>
  <div class="admin-head"><h2>\ud83c\udfac 成长视频管理</h2><button class="btn" @click="open()">+ 新增视频</button></div>
  <div class="list-row" v-for="v in list" :key="v.id">
    <div class="thumb"><MediaThumb :url="v.cover||v.url"/></div>
    <div class="grow"><b>{{v.title}}</b><small>{{fmtDate(v.date)}}</small></div>
    <button class="btn gray sm" @click="open(v)">编辑</button><button class="btn danger sm" @click="del(v)">删除</button>
  </div>
  <p v-if="!list.length" style="color:var(--c-muted)">还没有视频，点右上角新增。</p>
  <div class="modal-bg" v-if="editing" @click.self="editing=null"><div class="card modal">
    <h3>{{editing.id?'编辑':'新增'}}视频</h3>
    <div class="row2"><div class="field"><label>标题</label><input v-model="editing.title"/></div>
      <div class="field"><label>日期</label><input type="date" v-model="editing.date"/></div></div>
    <div class="field"><label>简介</label><textarea v-model="editing.desc" rows="2"></textarea></div>
    <div class="field"><label>视频文件</label><div style="display:flex;gap:10px;align-items:center"><input v-model="editing.url" placeholder="视频URL或上传"/><button class="btn ghost sm" @click="pickVideo()">上传视频</button></div>
      <video v-if="editing.url" :src="editing.url" controls style="margin-top:10px;border-radius:12px;max-height:180px;max-width:100%"></video></div>
    <div class="field"><label>封面图（可选，留空用视频首帧）</label><div style="display:flex;gap:10px;align-items:center"><input v-model="editing.cover" placeholder="封面URL或上传"/><button class="btn ghost sm" @click="pickVideoCover">上传封面</button></div></div>
    <div style="display:flex;gap:10px;justify-content:flex-end"><button class="btn gray" @click="editing=null">取消</button><button class="btn" @click="save">保存</button></div>
  </div></div>
</div>` };

const AdMembers={ setup(){
  const list=ref([]);
  const resetTarget=ref(null);const resetForm=reactive({password:'',confirm:''});const resetBusy=ref(false);const resetError=ref('');
  async function load(){try{list.value=await API.get('/users');}catch(e){list.value=[];}}
  async function toggle(u){try{await API.post('/users/'+u.id+'/status',{disabled:!u.disabled});await load();}catch(e){alert(e.message);}}
  async function del(u){if(await confirmDialog('删除成员「'+u.username+'」？该账号将无法再登录。')){try{await API.del('/users/'+u.id);await load();}catch(e){alert(e.message);}}}
  function clearReset(){resetForm.password='';resetForm.confirm='';resetError.value='';}
  function openReset(u){clearReset();resetTarget.value=u;}
  function closeReset(){if(resetBusy.value)return;resetTarget.value=null;clearReset();}
  async function submitReset(){
    resetError.value='';
    if(resetForm.password.length<8){resetError.value='新密码至少 8 位';return;}
    if(resetForm.password!==resetForm.confirm){resetError.value='两次输入的新密码不一致';return;}
    const target=resetTarget.value;if(!target||resetBusy.value)return;
    resetBusy.value=true;
    try{
      await runAction('member:reset-password:'+target.id,()=>API.post('/users/'+target.id+'/reset-password',{newPassword:resetForm.password}));
      resetTarget.value=null;clearReset();
      alert('密码重置成功，该成员所有旧会话已退出');
    }catch(e){resetError.value=e.message||'密码重置失败';}
    finally{resetBusy.value=false;}
  }
  onMounted(load);
  return {list,resetTarget,resetForm,resetBusy,resetError,toggle,del,openReset,closeReset,submitReset,fmtDate};
}, template:`
<div>
  <div class="admin-head"><h2>👥 成员管理</h2></div>
  <p style="color:var(--c-muted);margin-bottom:14px">管理员账号受保护，不能在此禁用、删除或重置密码。</p>
  <div class="list-row" v-for="u in list" :key="u.id">
    <span :style="{background:u.role==='admin'?'#ef8fa4':'#7fc8d4',width:'40px',height:'40px',borderRadius:'50%',display:'grid',placeItems:'center',color:'#fff',fontWeight:700,flex:'none'}">{{(u.username||'?').slice(0,1).toUpperCase()}}</span>
    <div class="grow"><b>{{u.username}}</b><small>{{u.role==='admin'?'管理员':'家庭成员'}}<template v-if="u.createdAt"> · 注册于 {{fmtDate(u.createdAt)}}</template></small></div>
    <span class="pill" :class="u.disabled?'pend':'ok'">{{u.role==='admin'?'管理员':(u.disabled?'已禁用':'正常')}}</span>
    <button v-if="u.role!=='admin'" class="btn ghost sm" :disabled="resetBusy" @click="openReset(u)">重置密码</button>
    <button v-if="u.role!=='admin'" class="btn gray sm" @click="toggle(u)">{{u.disabled?'启用':'禁用'}}</button>
    <button v-if="u.role!=='admin'" class="btn danger sm" @click="del(u)">删除</button>
  </div>
  <p v-if="!list.length" style="color:var(--c-muted)">还没有成员。</p>
  <div class="modal-bg" v-if="resetTarget" @click.self="closeReset"><div class="card modal">
    <h3>🔑 重置“{{resetTarget.username}}”的密码</h3>
    <p style="color:var(--c-muted);margin-bottom:14px">保存后该成员所有设备上的旧会话会立即退出，禁用状态不会改变。</p>
    <div class="field"><label>新密码（至少 8 位）</label><input type="password" autocomplete="new-password" v-model="resetForm.password" @keyup.enter="submitReset"/></div>
    <div class="field"><label>确认新密码</label><input type="password" autocomplete="new-password" v-model="resetForm.confirm" @keyup.enter="submitReset"/></div>
    <p v-if="resetError" style="color:#e0576a;margin:0 0 12px">{{resetError}}</p>
    <div style="display:flex;gap:10px;justify-content:flex-end"><button class="btn gray" :disabled="resetBusy" @click="closeReset">取消</button><button class="btn" :disabled="resetBusy" @click="submitReset">{{resetBusy?'重置中…':'确认重置'}}</button></div>
  </div></div>
</div>` };

const AdRecaps={ setup(){
  const list=computed(()=>state.db.recaps||[]);
  const busy=ref(false);
  const aihint=computed(()=>state.db.settings.ai&&state.db.settings.ai.enabled?'已启用大模型，将生成更自然的小结。':'当前使用内置模板生成；在显示设置填入大模型 Key 可获得更自然的文字。');
  async function gen(p){busy.value=true;try{const r=await API.post('/recaps/generate',{period:p});if(Array.isArray(state.db.recaps)&&r&&r.id!=null)state.db.recaps.unshift(r);else await refresh();}catch(e){alert(e.message);}busy.value=false;}
  async function del(r){if(await confirmDialog('删除这份小结？')){try{await API.del('/recaps/'+r.id);const arr=state.db.recaps;const i=Array.isArray(arr)?arr.findIndex(x=>x.id===r.id):-1;if(i>=0)arr.splice(i,1);else await refresh();}catch(e){alert(e.message);}}}
  return {list,busy,aihint,gen,del,fmtDate};
}, template:`
<div>
  <div class="admin-head"><h2>📝 AI 成长小结</h2><div style="display:flex;gap:8px"><button class="btn" :disabled="busy" @click="gen('week')">生成本周</button><button class="btn ghost" :disabled="busy" @click="gen('month')">生成本月</button></div></div>
  <p style="color:var(--c-muted);margin-bottom:14px">{{aihint}}</p>
  <div class="card" v-for="r in list" :key="r.id" style="padding:20px;margin-bottom:12px">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px"><b>{{r.title}}</b><span class="pill ok">{{r.period==='month'?'月':'周'}}</span><span style="margin-left:auto;color:var(--c-muted);font-size:.8rem">{{fmtDate(r.createdAt)}}</span><button class="btn danger sm" @click="del(r)">删除</button></div>
    <p style="color:#5b5870;white-space:pre-wrap;line-height:1.85">{{r.content}}</p>
  </div>
  <p v-if="!list.length" style="color:var(--c-muted)">还没有小结，点右上角生成一份。</p>
</div>` };

const AdVaccines={ setup(){
  const list=computed(()=>(state.db.vaccines||[]).slice().sort((a,b)=>(a.plannedMonth-b.plannedMonth)||(''+a.name).localeCompare(b.name)));
  const done=computed(()=>list.value.filter(v=>v.date).length);
  const editing=ref(null);
  const blank=()=>({id:'',name:'',dose:1,plannedMonth:0,date:'',note:''});
  function open(v){editing.value=v?JSON.parse(JSON.stringify(v)):blank();}
  async function save(){const e=editing.value;if(!e.name){alert('请填写名称');return;}try{if(e.id)await apiUpdate('vaccines',e.id,e);else await apiCreate('vaccines',e);editing.value=null;}catch(err){alert(err.message);}}
  async function del(v){if(await confirmDialog('删除「'+v.name+' 第'+v.dose+'剂」？')){try{await apiDelete('vaccines',v.id);}catch(err){alert(err.message);}}}
  async function toggle(v){try{await apiUpdate('vaccines',v.id,{date:v.date?'':todayStr()});}catch(err){alert(err.message);}}
  async function loadStd(){try{state.db.vaccines=await API.post('/vaccines/load-standard',{});}catch(err){alert(err.message);}}
  return {list,done,editing,open,save,del,toggle,loadStd,fmtDate};
}, template:`
<div>
  <div class="admin-head"><h2>💉 疫苗管理</h2><div style="display:flex;gap:8px"><button class="btn ghost" @click="loadStd" v-if="!list.length">载入标准程序</button><button class="btn" @click="open()">+ 新增</button></div></div>
  <p style="color:var(--c-muted);margin-bottom:12px">已完成 {{done}}/{{list.length}}。点右侧状态可切换是否已接种。</p>
  <div class="list-row" v-for="v in list" :key="v.id">
    <div style="width:42px;height:42px;border-radius:50%;display:grid;place-items:center;font-size:1.2rem;background:#e5f4f7;flex:none">💉</div>
    <div class="grow"><b>{{v.name}} · 第{{v.dose}}剂</b><small>建议 {{vxMonLabel(v.plannedMonth)}}<template v-if="v.date"> · 已接种 {{fmtDate(v.date)}}</template></small></div>
    <span class="pill" :class="vxInfo(v).cls" style="cursor:pointer" @click="toggle(v)">{{vxInfo(v).label}}</span>
    <button class="btn gray sm" @click="open(v)">编辑</button><button class="btn danger sm" @click="del(v)">删除</button>
  </div>
  <p v-if="!list.length" style="color:var(--c-muted)">还没有疫苗计划，点「载入标准程序」快速开始。</p>
  <div class="modal-bg" v-if="editing" @click.self="editing=null"><div class="card modal">
    <h3>{{editing.id?'编辑':'新增'}}疫苗</h3>
    <div class="row2"><div class="field"><label>名称</label><input v-model="editing.name"/></div><div class="field"><label>剂次</label><input type="number" v-model.number="editing.dose"/></div></div>
    <div class="row2"><div class="field"><label>建议月龄</label><input type="number" v-model.number="editing.plannedMonth"/></div><div class="field"><label>接种日期（空=未接种）</label><input type="date" v-model="editing.date"/></div></div>
    <div class="field"><label>备注</label><input v-model="editing.note"/></div>
    <div style="display:flex;gap:10px;justify-content:flex-end"><button class="btn gray" @click="editing=null">取消</button><button class="btn" @click="save">保存</button></div>
  </div></div>
</div>` };

/* ---------- AI WIDGET ---------- */
const AiWidget={ setup(){
  const open=ref(false), input=ref(''), busy=ref(false), listening=ref(false);
  const msgs=reactive([{role:'assistant',content:'你好呀！我是宝贝的成长小助手 🍼\n问我"宝宝多大了""最新身高体重""距上次喂奶多久"都可以，登录后还能帮你记录喂奶～'}]);
  const bodyEl=ref(null);
  const mode=computed(()=>state.db.settings.ai&&state.db.settings.ai.enabled?'AI 大模型':'内置助手');
  const quicks=['宝宝多大了？','最新身高体重','距上次喂奶多久','今天喝了多少奶','最近的里程碑'];
  function scrollB(){nextTick(()=>{if(bodyEl.value)bodyEl.value.scrollTop=bodyEl.value.scrollHeight;});}
  function speak(t){if('speechSynthesis'in window){const u=new SpeechSynthesisUtterance(t.replace(/[·•\n]/g,'，'));u.lang='zh-CN';u.rate=1.05;speechSynthesis.cancel();speechSynthesis.speak(u);}}
  async function send(txt,spoken=false){const q=(txt??input.value).trim();if(!q||busy.value)return;
    msgs.push({role:'user',content:q});input.value='';busy.value=true;scrollB();
    let reply;
    try{ const r=await API.post('/ai/chat',{messages:msgs.filter(m=>m.role!=='system').map(m=>({role:m.role,content:m.content}))}); reply=r.reply; if(state.session.loggedIn)await refresh(); }
    catch(e){ reply='抱歉，出错了：'+e.message; }
    msgs.push({role:'assistant',content:reply});busy.value=false;scrollB();if(spoken)speak(reply);
  }
  let rec;
  function voice(){
    const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
    if(!SR){alert('当前浏览器不支持语音识别，建议用 Chrome / Edge');return;}
    if(listening.value){rec&&rec.stop();return;}
    rec=new SR();rec.lang='zh-CN';rec.interimResults=false;
    rec.onstart=()=>listening.value=true;rec.onend=()=>listening.value=false;
    rec.onerror=()=>listening.value=false;
    rec.onresult=e=>{const t=e.results[0][0].transcript;input.value=t;send(t,true);};
    rec.start();
  }
  watch(open,v=>{if(v)scrollB();});
  return {open,input,busy,listening,msgs,bodyEl,mode,quicks,send,voice};
}, template:`
<div>
  <transition name="fade"><div class="ai-panel" v-if="open">
    <div class="ai-head"><span style="font-size:1.3rem">🤖</span><div><b>成长小助手</b></div><span class="st">{{mode}}</span>
      <button @click="open=false" style="color:#fff;margin-left:8px;font-size:1.2rem">✕</button></div>
    <div class="ai-body" ref="bodyEl">
      <div v-for="(m,i) in msgs" :key="i" class="bub" :class="m.role==='user'?'me':'ai'">{{m.content}}</div>
      <div v-if="busy" class="bub ai">正在思考…</div>
    </div>
    <div class="ai-quick"><button v-for="q in quicks" :key="q" @click="send(q)">{{q}}</button></div>
    <div class="ai-input">
      <button class="mic" :class="{rec:listening}" @click="voice" title="语音">🎤</button>
      <input v-model="input" @keyup.enter="send()" placeholder="问我关于宝贝的事…"/>
      <button @click="send()">➤</button>
    </div>
  </div></transition>
  <button class="ai-fab" @click="open=!open">{{open?'💬':'🤖'}}</button>
</div>` };

/* ---------- ROOT APP ---------- */
const AuthGate={ setup(){
  const tab=ref('login'); const form=reactive({u:'',p:'',code:'',remember:false}); const err=ref(''); const busy=ref(false);
  const regHint='请向管理员索取邀请码';
  onMounted(()=>{try{const r=JSON.parse(LS.getItem('bgt_remember')||'null');if(r&&r.u){form.u=r.u;form.remember=true;}}catch(e){}});
  async function login(){err.value='';busy.value=true;try{const fd=new FormData();fd.append('username',form.u);fd.append('password',form.p);await API.req('POST','/auth/login',{form:fd});API.setToken('');if(form.remember)LS.setItem('bgt_remember',JSON.stringify({u:form.u}));else LS.removeItem('bgt_remember');await refresh();go('home');}catch(e){err.value=e.message||'登录失败';}busy.value=false;}
  async function register(){err.value='';if(!form.u||form.p.length<8){err.value='请填写用户名，密码至少 8 位';return;}busy.value=true;try{await API.post('/auth/register',{username:form.u,password:form.p,code:form.code});API.setToken('');await refresh();go('home');}catch(e){err.value=e.message||'注册失败';}busy.value=false;}
  function submit(){tab.value==='login'?login():register();}
  return {tab,form,err,busy,submit,regHint,state};
}, template:`
<div class="login-wrap"><div class="card login-card">
  <div style="text-align:center;margin-bottom:16px"><div style="display:flex;justify-content:center;margin-bottom:6px"><img v-if="state.db.settings.faviconUrl" :src="state.db.settings.faviconUrl" alt="站点图标" style="width:64px;height:64px;border-radius:16px;object-fit:contain;background:#fff;box-shadow:var(--shadow-sm);padding:6px"/><div v-else style="font-size:2.4rem">🍼</div></div><h2>{{tab==='login'?'欢迎回来':'注册家庭账号'}}</h2><p style="color:var(--c-muted);font-size:.9rem">{{tab==='login'?'登录后查看宝贝的成长记录':'凭管理员邀请码创建账号'}}</p></div>
  <div style="display:flex;gap:6px;margin-bottom:18px"><button class="btn sm" :class="{gray:tab!=='login'}" style="flex:1" @click="tab='login';err=''">登录</button><button class="btn sm" :class="{gray:tab!=='register'}" style="flex:1" @click="tab='register';err=''">注册</button></div>
  <div class="field"><label>用户名</label><input v-model="form.u" @keyup.enter="submit" placeholder="用户名"/></div>
  <div class="field"><label>密码</label><input v-model="form.p" type="password" @keyup.enter="submit" placeholder="密码"/></div>
  <div class="field" v-if="tab==='register'"><label>邀请码</label><input v-model="form.code" @keyup.enter="submit" placeholder="管理员提供的邀请码"/></div>
  <label class="checkline" v-if="tab==='login'" style="margin-bottom:16px"><input type="checkbox" v-model="form.remember"/> 记住用户名（本设备）</label>
  <p v-if="err" style="color:#e0576a;margin-bottom:12px">⚠️ {{err}}</p>
  <button class="btn" style="width:100%" :disabled="busy" @click="submit">{{busy?'请稍候…':(tab==='login'?'登 录':'注册并进入')}}</button>
  <p v-if="tab==='register'" style="text-align:center;color:var(--c-muted);font-size:.82rem;margin-top:14px">{{regHint}}</p>
</div></div>` };

const AdInvites={ setup(){
  const list=ref([]);
  async function load(){try{list.value=await API.get('/invites');}catch(e){list.value=[];}}
  async function gen(){try{await API.post('/invites',{});await load();}catch(e){alert(e.message);}}
  async function del(i){if(await confirmDialog('撤销邀请码 '+i.code+' ？')){try{await API.del('/invites/'+i.id);await load();}catch(e){alert(e.message);}}}
  onMounted(load);
  return {list,gen,del};
}, template:`
<div>
  <div class="admin-head"><h2>🎟️ 邀请码管理</h2><button class="btn" @click="gen">+ 生成邀请码</button></div>
  <p style="color:var(--c-muted);margin-bottom:14px">家人凭一个未使用的邀请码即可注册账号登录查看。</p>
  <div class="list-row" v-for="i in list" :key="i.id">
    <div class="grow"><b style="font-family:monospace;font-size:1.05rem;letter-spacing:1px">{{i.code}}</b><small>{{i.note||'—'}} · {{i.used?('已被 '+i.usedBy+' 使用'):'未使用'}}</small></div>
    <span class="pill" :class="i.used?'ok':'pend'">{{i.used?'已使用':'可用'}}</span>
    <button v-if="!i.used" class="btn danger sm" @click="del(i)">撤销</button>
  </div>
  <p v-if="!list.length" style="color:var(--c-muted)">还没有邀请码，点右上角生成一个发给家人。</p>
</div>` };

const App={ components:{SiteNav,SiteFooter,Lightbox,AiWidget,AuthGate,ShareView}, setup(){
  const views={home:Home,timeline:Timeline,gallery:Gallery,videos:Videos,growth:Growth,vaccine:Vaccine,daily:Daily,diary:Diary,messages:Messages,about:About,profile:Profile,admin:Admin};
  const cur=computed(()=>{const n=route.name;const v=views[n];if(!v)return Home;
    if(['timeline','gallery','videos','growth','vaccine','daily','diary','messages','about'].includes(n)&&state.db.settings.modules[n]===false)return Home;if(n==='admin'&&state.session.role!=='admin')return Home;return v;});
  const showFooter=computed(()=>route.name!=='admin');
  watch(()=>[route.name,route.params.id],()=>observeReveals());
  let clockTimer;onMounted(()=>{clockTimer=setInterval(()=>{clockTick.value++;},30000);});onUnmounted(()=>clearInterval(clockTimer));
  return {cur,showFooter,state,route,startup,retryBootstrap,toasts,pending:pendingActions,up:uploadState,cancel:cancelUpload,cf:confirmState,confirmYes,confirmNo};
}, template:`
<div>
  <ShareView v-if="route.name==='share'"/>
  <div v-else-if="startup.loading" class="startup-state"><div><div class="startup-icon">🍼</div><p>正在加载家庭成长记录…</p></div></div>
  <div v-else-if="startup.error" class="startup-state"><div class="card startup-error"><div class="startup-icon">🌧️</div><h2>暂时无法加载</h2><p>{{startup.error}}</p><button class="btn" @click="retryBootstrap">重新加载</button></div></div>
  <AuthGate v-else-if="!state.session.loggedIn"/>
  <template v-else>
    <SiteNav/>
    <main><component :is="cur"/></main>
    <SiteFooter v-if="showFooter"/>
    <AiWidget/>
  </template>
  <div class="toast-stack" aria-live="polite" aria-atomic="false"><div class="toast" v-for="item in toasts.items" :key="item.id" :class="item.type"><span>{{item.type==='success'?'✓':item.type==='error'?'!':'i'}}</span><p>{{item.message}}</p><button @click="toasts.remove(item.id)" aria-label="关闭提示">✕</button></div></div>
  <div v-if="pending.size&&!up.active" class="action-busy" role="status">处理中…</div>
  <div v-if="up.active" class="upbar"><div class="upbar-card"><div class="upbar-row"><span>⬆️ {{up.cancellable?'正在上传':'正在处理'}} {{up.label}}<template v-if="up.total>1"> · {{up.index}}/{{up.total}}</template></span><div style="display:flex;align-items:center;gap:10px"><b>{{up.pct}}%</b><button class="upbar-cancel" v-if="!up.cancelled&&up.cancellable" @click="cancel" title="取消上传">取消</button><span v-else-if="up.cancelled" class="upbar-hint">取消中...</span><span v-else class="upbar-hint">请稍候...</span></div></div><div class="upbar-track"><i :style="{width:up.pct+'%'}"></i></div></div></div>
  <div v-if="cf.open" class="modal-bg" style="z-index:210" @click.self="confirmNo">
    <div class="card" style="max-width:360px;padding:26px;text-align:center">
      <div style="font-size:2rem">🗑️</div>
      <p style="margin:12px 0 22px;color:#5b5870;white-space:pre-wrap">{{cf.message}}</p>
      <div style="display:flex;gap:10px;justify-content:center"><button class="btn gray" @click="confirmNo">取消</button><button class="btn danger" @click="confirmYes">确定删除</button></div>
    </div>
  </div>
  <Lightbox/>
</div>` };

/* ---------- bootstrap ---------- */
const app=createApp(App);
app.config.globalProperties.isVideo=isVideo;app.config.globalProperties.vxInfo=vxInfo;app.config.globalProperties.vxMonLabel=vxMonLabel;
[['AdOverview',AdOverview],['AdBaby',AdBaby],['AdMilestones',AdMilestones],['AdAlbums',AdAlbums],['AdGrowth',AdGrowth],['AdDaily',AdDaily],['AdDiary',AdDiary],['AdMessages',AdMessages],['AdSettings',AdSettings],['AdVideos',AdVideos],['AdInvites',AdInvites],['AdMembers',AdMembers],['AdRecaps',AdRecaps],['AdVaccines',AdVaccines],['Toggle',Toggle],['MediaThumb',MediaThumb],['HistoryPager',HistoryPager],['AuthGate',AuthGate],['ShareView',ShareView]].forEach(([n,c])=>app.component(n,c));
parseHash();
window.addEventListener('hashchange',parseHash);
// 迁移：清除旧版本可能残留在 localStorage 里的明文密码，只保留用户名
try{const r=JSON.parse(LS.getItem('bgt_remember')||'null');if(r&&('p' in r)){if(r.u)LS.setItem('bgt_remember',JSON.stringify({u:r.u}));else LS.removeItem('bgt_remember');}}catch(e){}
// 上传中拦截页面关闭/刷新，弹出系统级确认框防止意外丢失（浏览器只支持通用文案）
window.addEventListener('beforeunload',e=>{ if(uploadState.active){ e.preventDefault(); e.returnValue='正在上传中，离开会中断上传'; return e.returnValue; } });
app.mount('#app');
applyTheme();
API.setToken(API.token);
async function bootstrapApp(){
  if(API.token){try{await API.post('/auth/session');}catch(e){}finally{API.setToken('');}}
  await loadBranding();
  await refresh();
}
async function retryBootstrap(){
  if(startup.loading)return;
  startup.loading=true;startup.error='';state.ready=false;
  try{await bootstrapApp();}
  catch(e){if(e&&e.status!==401){startup.error=startupErrorMessage(e);console.error('bootstrap 失败',e);}}
  finally{startup.loading=false;state.ready=true;observeReveals();}
}
retryBootstrap();
