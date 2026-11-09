"""The website's design system: colours, type, spacing and components as one small stylesheet, plus the logo and
the one script (search, copy-link, click-to-play videos). No web fonts, no frameworks: the pages stay fast on
phones anywhere. Colours meet WCAG AA: Electric Blue (#4776F5) is used for accents only; links and buttons use the
deeper #2F5BD8 (5.8:1 on white)."""

CSS = r"""
:root{
  --navy:#101B32;--blue:#4776F5;--blue-ink:#2F5BD8;--gold:#F0BC55;--paper:#F5F7FB;--surface:#FFFFFF;--ink:#202736;
  --muted:#5A6478;--line:#E1E6EF;--focus:#F0BC55;--shadow:0 1px 2px rgba(16,27,50,.06),0 6px 20px rgba(16,27,50,.06);
  --r:14px;--w:1160px;--read:720px;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  --serif:Charter,"Bitstream Charter","Sitka Text",Cambria,Georgia,serif;
}
@media (prefers-color-scheme:dark){:root{
  --paper:#0B1222;--surface:#131C30;--ink:#E6EAF2;--muted:#A9B3C7;--line:#24304A;--blue-ink:#8FB0FF;--shadow:none}}
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-padding-top:80px}
body{margin:0;background:var(--paper);color:var(--ink);font:17px/1.6 var(--sans);overflow-x:hidden}
img{max-width:100%;height:auto;display:block}
a{color:var(--blue-ink);text-underline-offset:3px}
a:hover{text-decoration-thickness:2px}
:focus-visible{outline:3px solid var(--focus);outline-offset:2px;border-radius:4px}
.skip{position:absolute;left:-999px;top:8px;background:var(--navy);color:#fff;padding:10px 14px;border-radius:8px;z-index:20}
.skip:focus{left:8px}
.wrap{max-width:var(--w);margin:0 auto;padding:0 max(16px,env(safe-area-inset-left)) 0 max(16px,env(safe-area-inset-right))}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
/* header */
.top{position:sticky;top:0;z-index:10;background:var(--navy);color:#fff}
.top .wrap{display:flex;align-items:center;gap:16px;min-height:64px}
.brand{display:flex;align-items:center;gap:10px;min-height:44px;color:#fff;text-decoration:none;font-weight:800;font-size:20px;letter-spacing:-.01em}
.nav{margin-left:auto;display:flex;align-items:center;gap:4px}
.nav a{color:#DCE3F2;text-decoration:none;font-size:15px;padding:10px 12px;border-radius:10px}
.nav a:hover,.nav a[aria-current=page]{background:rgba(255,255,255,.1);color:#fff}
.menu{display:none;margin-left:auto}
.menu summary{list-style:none;cursor:pointer;color:#fff;padding:10px 12px;border:1px solid rgba(255,255,255,.25);border-radius:10px;font-size:15px}
.menu summary::-webkit-details-marker{display:none}
.menu[open] .nav{display:flex;position:absolute;left:0;right:0;top:64px;flex-direction:column;align-items:stretch;background:var(--navy);padding:8px 16px 16px;border-top:1px solid rgba(255,255,255,.1)}
.menu[open] .nav a{padding:14px 12px;font-size:17px}
@media (max-width:760px){.top .nav.desktop{display:none}.menu{display:block}}
@media (min-width:761px){.menu{display:none}}
/* hero */
.hero{background:var(--navy);color:#fff;padding:56px 0 64px;position:relative;overflow:hidden}
.hero::after{content:"";position:absolute;right:-120px;top:-120px;width:420px;height:420px;border-radius:50%;background:radial-gradient(circle,rgba(71,118,245,.35),transparent 70%)}
.hero h1{font-size:clamp(32px,5.2vw,56px);line-height:1.08;margin:0 0 16px;max-width:820px;letter-spacing:-.02em}
.hero h1 em{font-style:normal;color:var(--gold)}
.hero p{font-size:clamp(17px,2vw,20px);color:#C9D3E8;max-width:640px;margin:0 0 28px}
.cta{display:flex;flex-wrap:wrap;gap:12px}
.btn{display:inline-flex;align-items:center;gap:8px;min-height:48px;padding:12px 20px;border-radius:12px;font-weight:700;text-decoration:none;font-size:16px}
.btn.primary{background:var(--gold);color:var(--navy)}
.btn.ghost{color:#fff;border:1px solid rgba(255,255,255,.35)}
.btn.solid{background:var(--blue-ink);color:#fff}
@media (prefers-color-scheme:dark){.btn.solid{color:#0B1222}}
/* sections and cards */
.section{padding:44px 0}
.section h2.title{font-size:clamp(22px,2.6vw,28px);margin:0 0 6px;letter-spacing:-.01em}
.section .lead{color:var(--muted);margin:0 0 22px}
.row{display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap}
.grid{display:grid;gap:22px;grid-template-columns:repeat(auto-fill,minmax(min(100%,300px),1fr))}
.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);overflow:hidden;box-shadow:var(--shadow);display:flex;flex-direction:column}
.card a.cover{display:block;aspect-ratio:16/9;background:var(--line)}
.card a.cover img{width:100%;height:100%;object-fit:cover}
.card .body{padding:16px 18px 18px;display:flex;flex-direction:column;gap:8px;flex:1}
.card h3{font-size:19px;line-height:1.3;margin:0}
.card h3 a{color:var(--ink);text-decoration:none}
.card h3 a:hover{color:var(--blue-ink)}
.card p{margin:0;color:var(--muted);font-size:15px}
.meta{font-size:14px;color:var(--muted)}
.lead-story{display:grid;gap:24px;grid-template-columns:1.3fr 1fr;align-items:center;background:var(--surface);border:1px solid var(--line);border-radius:var(--r);overflow:hidden;box-shadow:var(--shadow);margin-bottom:26px}
.lead-story .cover{aspect-ratio:16/9;background:var(--line)}
.lead-story .cover img{width:100%;height:100%;object-fit:cover}
.lead-story .body{padding:20px 24px 24px}
.lead-story h3{font-size:clamp(22px,2.8vw,32px);line-height:1.2;margin:8px 0 10px}
.lead-story h3 a{color:var(--ink);text-decoration:none}
@media (max-width:860px){.lead-story{grid-template-columns:1fr}}
.noimg{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;width:100%;height:100%;min-height:180px;background:linear-gradient(135deg,#101B32,#1d2d55);color:#fff;font:800 15px var(--sans);letter-spacing:.08em;text-transform:uppercase}.noimg.money{background:linear-gradient(135deg,#101B32,#5c3d00)}
.tag{display:inline-block;font-size:12px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;padding:3px 9px;border-radius:999px;text-decoration:none;width:max-content}
.tag.ai{background:#E5ECFF;color:#1E3FA8}.tag.money{background:#FCEBC6;color:#5C3D00}
.pager{display:flex;justify-content:space-between;gap:12px;margin-top:28px}
.empty{background:var(--surface);border:1px dashed var(--line);border-radius:var(--r);padding:26px;color:var(--muted)}
/* article */
.crumbs{font-size:14px;color:var(--muted);padding:18px 0 0}
.crumbs ol{list-style:none;display:flex;flex-wrap:wrap;gap:6px;margin:0;padding:0}
.crumbs li+li::before{content:"›";margin-right:6px}
.article{max-width:var(--read);margin:0 auto}
.article h1{font-size:clamp(30px,4.4vw,46px);line-height:1.12;margin:14px 0 14px;letter-spacing:-.02em}
.byline{display:flex;flex-wrap:wrap;gap:6px 14px;color:var(--muted);font-size:15px;margin-bottom:22px}
.prose{font:19px/1.75 var(--serif)}
.prose p{margin:0 0 1.15em}
.prose p.intro{font-size:21px;color:var(--ink)}
.prose h2{font:700 24px/1.3 var(--sans);margin:1.8em 0 .6em;letter-spacing:-.01em}
.figure{margin:0 0 26px;border-radius:var(--r);overflow:hidden;background:var(--line)}
.toc{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:14px 18px;margin:0 0 26px;font-size:15px}
.toc summary{cursor:pointer;font-weight:700}
.toc ol{margin:10px 0 0;padding-left:20px}.toc li{margin:4px 0}
.note{background:var(--surface);border:1px solid var(--line);border-left:4px solid var(--blue);border-radius:10px;padding:14px 16px;margin:24px 0;font-size:15px;line-height:1.55}
.note.money{border-left-color:var(--gold)}
.sources{font-size:15px;line-height:1.55;padding-left:22px}.sources li{margin:8px 0;overflow-wrap:anywhere}
.share{display:flex;flex-wrap:wrap;gap:8px;margin:26px 0}
.share a,.share button{font:600 14px var(--sans);min-height:44px;display:inline-flex;align-items:center;padding:10px 14px;border-radius:10px;border:1px solid var(--line);background:var(--surface);color:var(--ink);text-decoration:none;cursor:pointer}
.video{position:relative;aspect-ratio:16/9;border-radius:var(--r);overflow:hidden;background:#000;margin:0 0 26px}
.video img{width:100%;height:100%;object-fit:cover;opacity:.9}
.video a.play,.video button.play{position:absolute;inset:0;display:grid;place-items:center;background:none;border:0;cursor:pointer;color:#fff;font:700 16px var(--sans);text-decoration:none}
.video .play span{background:rgba(16,27,50,.85);padding:14px 20px;border-radius:999px}
.video iframe{position:absolute;inset:0;width:100%;height:100%;border:0}
.related{border-top:1px solid var(--line);margin-top:36px;padding-top:26px}
/* search and forms */
.field{display:flex;gap:8px;flex-wrap:wrap}
.field input{flex:1 1 200px;min-width:0;min-height:48px;font:17px var(--sans);padding:10px 14px;border-radius:12px;border:1px solid var(--line);background:var(--surface);color:var(--ink)}
.field button{flex:0 0 auto;min-height:48px;padding:0 18px;border-radius:12px;border:0;background:var(--blue-ink);color:#fff;font:700 16px var(--sans);cursor:pointer}
.results{list-style:none;padding:0;margin:20px 0 0;display:grid;gap:14px}
.results li{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.results a{font-weight:700;font-size:18px}
.newsletter{background:var(--navy);color:#fff;border-radius:var(--r);padding:28px}
.newsletter p{color:#C9D3E8}
.newsletter label.consent{display:flex;gap:10px;align-items:flex-start;font-size:14px;color:#C9D3E8;margin-top:10px}
.big{font-size:clamp(28px,4vw,40px)}.h2s{font-size:22px}.newsletter a{color:#fff}
.page{max-width:var(--read);margin:0 auto;padding:34px 0 10px}
.page h1{font-size:clamp(28px,4vw,40px);margin:0 0 14px;letter-spacing:-.02em}
.page h2{margin:1.6em 0 .5em}
/* footer */
.foot{background:var(--navy);color:#C9D3E8;margin-top:56px;padding:40px 0 calc(28px + env(safe-area-inset-bottom))}
.foot a{color:#fff;text-decoration:none}.foot a:hover{text-decoration:underline}
.foot .cols{display:grid;gap:26px;grid-template-columns:repeat(auto-fit,minmax(180px,1fr))}
.foot h2{font-size:14px;letter-spacing:.08em;text-transform:uppercase;color:var(--gold);margin:0 0 10px}
.foot ul{list-style:none;margin:0;padding:0}.foot li{margin:8px 0}
.foot .small{font-size:14px;margin-top:26px;border-top:1px solid rgba(255,255,255,.12);padding-top:18px}
@media (prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important;animation:none!important}}
@media print{.top,.foot,.share,.related,.menu,.skip,.video{display:none!important}body{background:#fff;color:#000}.prose{font-size:12pt}a{color:#000}}
"""

# One small script, loaded with `defer`: search on /search/, the copy-link button, and click-to-play videos (the
# YouTube player loads only when a reader asks for it). Without JavaScript every page still works.
JS = r"""
(function(){
  document.querySelectorAll('[data-copy]').forEach(function(b){
    b.hidden=false;
    b.addEventListener('click',function(){
      var done=function(){b.textContent='Link copied';setTimeout(function(){b.textContent='Copy link'},2000)};
      if(navigator.clipboard){navigator.clipboard.writeText(b.getAttribute('data-copy')).then(done,function(){})}
    });
  });
  document.querySelectorAll('[data-yt]').forEach(function(box){
    var btn=box.querySelector('button.play');if(!btn)return;btn.hidden=false;
    var link=box.querySelector('a.play');if(link)link.hidden=true;
    btn.addEventListener('click',function(){
      var f=document.createElement('iframe');
      f.src='https://www.youtube-nocookie.com/embed/'+box.getAttribute('data-yt')+'?autoplay=1&rel=0';
      f.title=box.getAttribute('data-title')||'Video';
      f.allow='accelerometer; autoplay; encrypted-media; gyroscope; picture-in-picture';f.allowFullscreen=true;
      box.innerHTML='';box.appendChild(f);
    });
  });
  var form=document.getElementById('search-form');if(!form)return;
  var input=form.querySelector('input'),out=document.getElementById('results'),status=document.getElementById('search-status'),index=null;
  function esc(s){return String(s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
  function run(){
    var q=input.value.trim().toLowerCase();var words=q.split(/\s+/).filter(Boolean);
    if(!words.length){out.innerHTML='';status.textContent='';return}
    var hits=index.map(function(a){var hay=(a.t+' '+a.d+' '+a.c+' '+a.k).toLowerCase(),score=0;
      words.forEach(function(w){if(hay.indexOf(w)>=0)score+=a.t.toLowerCase().indexOf(w)>=0?3:1});
      return {a:a,s:words.every(function(w){return hay.indexOf(w)>=0})?score:0}})
      .filter(function(x){return x.s>0}).sort(function(x,y){return y.s-x.s});
    status.textContent=hits.length?hits.length+' result'+(hits.length===1?'':'s')+' for "'+input.value.trim()+'"':'No articles match "'+input.value.trim()+'". Try a shorter word, or browse the categories.';
    out.innerHTML=hits.map(function(h){return '<li><a href="'+esc(h.a.u)+'">'+esc(h.a.t)+'</a><div class="meta">'+esc(h.a.c)+' · '+esc(h.a.p)+'</div><p>'+esc(h.a.d)+'</p></li>'}).join('');
  }
  fetch('/search-index.json').then(function(r){return r.json()}).then(function(d){index=d;
    var q=new URLSearchParams(location.search).get('q');if(q){input.value=q;run()}
    input.addEventListener('input',run);form.addEventListener('submit',function(e){e.preventDefault();run();
      history.replaceState(null,'','?q='+encodeURIComponent(input.value.trim()))});
  }).catch(function(){status.textContent='Search is unavailable right now. Browse the categories instead.'});
})();
"""


def logo(size: int = 32) -> str:
    """The symbol: Penny's gold coin and Pixel's blue pixel."""
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 32 32" aria-hidden="true" focusable="false">'
            '<rect width="32" height="32" rx="9" fill="#101B32"/><circle cx="12.5" cy="16" r="6.2" fill="#F0BC55"/>'
            '<rect x="17.5" y="9.8" width="9.5" height="12.4" rx="2.4" fill="#4776F5"/></svg>')


FAVICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="9" fill="#101B32"/>'
           '<circle cx="12.5" cy="16" r="6.2" fill="#F0BC55"/><rect x="17.5" y="9.8" width="9.5" height="12.4" rx="2.4" '
           'fill="#4776F5"/></svg>')

JS += r"""
const raiseForm = document.querySelector('#raise-calculator');
if (raiseForm) raiseForm.addEventListener('submit', (event) => {
  event.preventDefault();
  const fields = new FormData(raiseForm);
  const oldPay = Number(fields.get('old')), newPay = Number(fields.get('new')), inflation = Number(fields.get('inflation'));
  const result = document.querySelector('#raise-result');
  if (![oldPay,newPay,inflation].every(Number.isFinite) || oldPay <= 0 || newPay < 0 || inflation <= -100) {
    result.textContent = 'Enter positive old pay, non-negative new pay, and inflation above -100%.';
    return;
  }
  const nominal = (newPay / oldPay - 1) * 100;
  const real = ((newPay / oldPay) / (1 + inflation / 100) - 1) * 100;
  result.textContent = `Nominal change: ${nominal.toFixed(2)}%. Inflation-adjusted change: ${real.toFixed(2)}%. Based only on your inputs.`;
});
"""

JS += r"""
// Events contain no email, form values, identifiers or query strings. A form
// submission is an attempt, never a confirmed subscriber or sale.
function siteEvent(event) {
  const endpoint = document.querySelector('meta[name="site-events-url"]')?.content;
  if (!endpoint) return;
  fetch(endpoint, {method:'POST', credentials:'omit', keepalive:true,
    headers:{'Content-Type':'application/json'}, body:JSON.stringify({event,path:location.pathname})}).catch(()=>{});
}
document.addEventListener('click', (event) => {
  const a=event.target.closest('a');
  if (a?.dataset.event === 'affiliate_click') siteEvent('affiliate_click');
  else if (a?.hasAttribute('download')) siteEvent('download');
});
document.querySelector('.newsletter form')?.addEventListener('submit',()=>siteEvent('newsletter_submit'));
"""
