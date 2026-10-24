/* Football Analyzer Mobile · private sports analytics PWA */
const $ = (sel)=>document.querySelector(sel);
const view = $('#main');
const state = {screen:'home',league:'',scope:'upcoming',token:sessionStorage.getItem('fa_token')||'',
  match:null,player:null,detailTab:'analysis',scopeTab:'total',lineups:null,searchQuery:'', lastHome:null,
  matches:[],lastHistory:[], status:null};
const labels={GOALS:'Goluri',CORNERS:'Cornere',SHOTS_ON_TARGET:'Șuturi pe poartă',SHOTS:'Șuturi totale',
  OFFSIDES:'Ofsaiduri',SAVES:'Intervenții portar',FOULS:'Faulturi',YELLOW:'Cartonașe galbene',RED:'Cartonașe roșii'};
const leagues={'':'Toate ligile','eng.1':'Premier League','esp.1':'La Liga','ita.1':'Serie A','ger.1':'Bundesliga','fra.1':'Ligue 1'};
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const when=s=>{try{return new Date(s).toLocaleString('ro-RO',{timeZone:'Europe/Bucharest',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'})}catch(e){return '—'}};
const initials=name=>(name||'').trim().split(/\s+/).slice(0,2).map(w=>w[0]||'').join('').toUpperCase();
const pct=v=>typeof v==='number'?Number(v).toLocaleString('ro-RO',{maximumFractionDigits:1})+'%':'—';
function toast(msg){const el=$('#toast');el.textContent=msg;el.classList.add('visible');clearTimeout(window._toast);window._toast=setTimeout(()=>el.classList.remove('visible'),3800)}
function loading(txt='Încarc informațiile...'){view.innerHTML=`<div class="empty"><div class="loader"></div>${esc(txt)}</div>`}
function auth(show){$('#authOverlay').classList.toggle('hidden',!show);if(show)setTimeout(()=>$('#tokenInput').focus(),30)}
async function request(path,opts={}){
  const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),30000);
  try{
    const headers={'Accept':'application/json'};
    if(state.token)headers['X-FA-Token']=state.token;
    const result=await fetch(path,{...opts,headers:{...headers,...opts.headers},signal:controller.signal,cache:'no-store'});
    if(result.status===401){auth(true);throw new Error('Este necesar codul de acces la server.');}
    if(!result.ok){let msg;try{msg=(await result.json()).detail}catch(e){}throw new Error(msg||`Eroare HTTP ${result.status}`)}
    return await result.json();
  }finally{clearTimeout(timeout)}
}
function activate(tab){document.querySelectorAll('.nav-item').forEach(b=>b.classList.toggle('active',b.dataset.view===tab))}
function section(eye,title,lead=''){return `<section class="hero"><div class="eyebrow">${esc(eye)}</div><h1 class="section-title">${esc(title)}</h1>${lead?`<p class="lead">${esc(lead)}</p>`:''}</section>`}
function leagueSelect(){return `<select aria-label="Filtrează după ligă" class="select" id="leagueSelect">${Object.entries(leagues).map(([id,v])=>`<option value="${esc(id)}" ${state.league===id?'selected':''}>${esc(v)}</option>`).join('')}</select>`}
function matchCard(m){const complete=Boolean(m.completed);return `<button class="match-card" data-match="${esc(m.league)}|${esc(m.event_id)}">
  <div class="match-meta"><span>${esc(leagues[m.league]||m.league)}</span><span>${when(m.kickoff)}</span></div>
  <div class="match-teams"><div class="team"><span class="team-dot">${esc(initials(m.home_name))}</span><span class="team-name">${esc(m.home_name)}</span></div>
  <div class="match-center"><b>${complete&&m.home_goals!=null?`${m.home_goals} : ${m.away_goals}`:'VS'}</b><small>${complete?'FINAL':'PROGRAMAT'}</small></div>
  <div class="team away"><span class="team-dot">${esc(initials(m.away_name))}</span><span class="team-name">${esc(m.away_name)}</span></div></div>
  <div class="card-footer"><span>${complete?'Rezultat oficial ESPN':'Analiză statistică disponibilă'}</span><strong>Deschide ›</strong></div></button>`}
function empty(content){return `<div class="blank">${content}</div>`}
async function home(){state.screen='home';activate('home');loading();try{
  const [data,stat]=await Promise.all([request('/api/fixtures?scope=upcoming'+(state.league?'&league='+encodeURIComponent(state.league):'')),request('/api/status')]);
  state.matches=data.fixtures;state.status=stat;const syncing=stat.running;
  view.innerHTML=section('SPORTS INTELLIGENCE','Meciurile următoare','Cinci ligi europene. Date ESPN și analize realizate din rezultatele disponibile.')+
  `<div class="hero-row"><span class="pill"><span class="pulse"></span>${syncing?'Se actualizează':'Date ESPN'}</span><span class="minor">${stat.last_refresh?'Actualizat: '+when(stat.last_refresh):'Prima sincronizare în curs'}</span></div>
  <div class="section-head"><h2>Programul meciurilor <span class="minor">${data.fixtures.length}</span></h2>${leagueSelect()}</div>
  <div class="match-list">${data.fixtures.length?data.fixtures.map(matchCard).join(''):empty('Nu am găsit meciuri viitoare în baza locală. Apasă simbolul de actualizare. Dacă ESPN nu răspunde, vor apărea după ce conexiunea revine.')}</div>`;
  $('#leagueSelect').onchange=e=>{state.league=e.target.value;home()};
  if(syncing&&!window._homeRefresh){window._homeRefresh=setTimeout(()=>{window._homeRefresh=null;if(state.screen==='home')home()},10000)}
 }catch(e){view.innerHTML=section('FOOTBALL ANALYZER','Meciurile următoare')+empty(esc(e.message)+'<p>Verifică dacă serverul este online.</p>')}
}
function metricSummary(m){const goals=m.estimates.GOALS;if(!goals)return empty('Nu există încă suficiente meciuri pentru o estimare statistică a acestei partide.');
  return `<div class="card"><h3>Estimări pentru goluri</h3><div class="stat-grid"><div class="stat-mini"><b>${goals.home.toFixed(2)}</b><small>${esc(m.fixture.home_name)}</small></div><div class="stat-mini"><b>${goals.total.toFixed(2)}</b><small>Total estimat</small></div><div class="stat-mini"><b>${goals.away.toFixed(2)}</b><small>${esc(m.fixture.away_name)}</small></div></div><p class="hint">Estimări matematice din istoricul meciurilor, nu rezultate certe.</p></div>`}
function scopeTabs(){return `<div class="tabs">${[['total','Total meci'],['home','Gazde'],['away','Oaspeți']].map(([id,name])=>`<button class="tab ${state.scopeTab===id?'active':''}" data-scope="${id}">${name}</button>`).join('')}</div>`}
function metricRows(metric,details){const sub=details.levels[state.scopeTab];const expected=details[state.scopeTab];
  const initial=metric==='GOALS'?sub.slice(0,7):sub.filter((s,i)=>i===0 || (s.threshold+0.5)%2===0).slice(0,14);
  return `<section class="metric-card"><button class="metric-head" aria-expanded="false" data-metric="${esc(metric)}"><span>${esc(labels[metric])}</span><small>Medie ${expected.toFixed(2)} &nbsp;⌄</small></button><div class="metric-body" id="metric-${esc(metric)}" hidden><div class="row-stat"><span class="head">Prag statistic</span><span class="head" style="text-align:right">Mai mult</span><span class="head" style="text-align:right">Mai puțin</span></div>${initial.map(s=>`<div class="row-stat"><span>${s.threshold.toFixed(1).replace('.',',')}</span><b class="over">${pct(s.over)}</b><b class="under">${pct(s.under)}</b></div>`).join('')}</div></section>`}
function predictionMarkup(details){const entry=details.estimates||{};return `${metricSummary(details)}${scopeTabs()}<div class="section-divider">Statistici & probabilități</div><p class="hint">Alege categoria pentru estimările modelului Poisson. Sunt necesare minimum trei observații valide pentru fiecare echipă.</p><div class="metric-list">${Object.keys(labels).filter(k=>entry[k]).map(k=>metricRows(k,entry[k])).join('')||empty('Statistici insuficiente pentru această partidă.')}</div>`}
function realStatsMarkup(data){const stats=data.statistics||{};const metrics=Object.keys(labels);
  return `<div class="card"><h3>Statistici finale</h3><p class="hint">„—” înseamnă că ESPN nu a furnizat valoarea, nu zero.</p><table class="value-table"><thead><tr><th>Statistică</th><th>Gazde</th><th>Oaspeți</th><th>Total</th></tr></thead><tbody>${metrics.map(k=>`<tr><td>${labels[k]}</td>${['home','away','total'].map(s=>`<td>${stats[s]?.[k]??'—'}</td>`).join('')}</tr>`).join('')}</tbody></table><button class="tiny-btn" id="refreshMatch" style="margin-top:15px">↻ Descarcă statisticile meciului</button></div>`}
function archiveMarkup(data){if(!data.archive?.saved)return empty('Nu există o predicție salvată înaintea începerii acestui meci. Nu generăm predicții retroactive.');
 const evals=data.archive.entries.filter(e=>e.actual!=null).slice(0,16);
 const summary=data.archive.summary;
 return `<div class="card"><h3>Evaluarea predicțiilor</h3><p class="hint">${summary?.evaluated??0} rezultate evaluate · ${summary?.unavailable??0} date lipsă${summary?.brier!=null?' · Scor Brier '+summary.brier:''}</p><table class="value-table"><thead><tr><th>Estimare</th><th>Model</th><th>Real</th></tr></thead><tbody>${evals.map(e=>`<tr><td>${esc(labels[e.metric]||e.metric)} ${e.kind==='OVER'?'peste':'sub'} ${e.threshold.toFixed(1).replace('.',',')}</td><td>${pct(e.predicted)}</td><td class="${e.happened?'score-tag':'muted-tag'}">${e.actual}</td></tr>`).join('')}</tbody></table></div>`}
function verifiedPitch(club){
 // ESPN's formationPlace is a tactical slot, not a contiguous row number.
 // Draw a pitch only for schemas we have verified; otherwise show the safe list.
 const maps={
  '4-3-3':[[2,5,6,3],[7,4,8],[10,9,11]],
  '4-2-3-1':[[2,5,6,3],[4,7],[10,8,11],[9]],
  '4-4-2':[[2,5,6,3],[7,4,8,11],[9,10]]
 };
 const rows=maps[(club.formation||'').replaceAll(' ','')];
 if(!rows||club.players.length!==11)return '';
 const slots=new Map(club.players.map(p=>[p.formation_place,p]));
 if(slots.size!==11 || !slots.has(1) || !['GK','G','GOALKEEPER'].includes((slots.get(1).position||'').toUpperCase()))return '';
 const levels=rows.length===4?[70,53,37,19]:[70,48,22];
 function chip(p){return `<button class="pitch-player ${p.formation_place===1?'keeper':''}" data-player="${esc(state.match.fixture.league)}|${esc(club.team_id)}|${esc(p.player_id)}"><span>${esc(p.jersey||'—')}</span>${esc(p.name.split(' ').slice(-1)[0])}</button>`}
 return `<div class="mini-pitch" aria-label="Așezare tactică ESPN ${esc(club.formation)}"><div class="pitch-half"></div><div class="pitch-row" style="top:88%">${chip(slots.get(1))}</div>`+
 rows.map((r,i)=>`<div class="pitch-row" style="top:${levels[i]}%">${r.map(id=>slots.has(id)?chip(slots.get(id)):'').join('')}</div>`).join('')+`</div>`;
}
function lineupsMarkup(data){if(!data)return empty('Se verifică formațiile ESPN...');return ['home','away'].map(side=>{
  const c=data[side];const goalkeeper=c.players.find(p=>p.formation_place===1||['G','GK'].includes((p.position||'').toUpperCase()));
  const players=[...(goalkeeper?[goalkeeper]:[]),...c.players.filter(p=>p!==goalkeeper)];
  const formation=c.formation||'Formație necunoscută';
  return `<section class="lineup-side"><div class="section-head"><h2>${esc(c.name)}</h2><span class="pill" style="${c.confirmed?'':'background:#3f3a25;color:#f9d69b;border-color:#786235'}">${c.confirmed?'XI confirmat':'Ultimul XI'}</span></div><p class="hint">${esc(formation)} · ${esc(c.source)}</p>
  ${players.length?verifiedPitch(c)+`<div class="players-list">${players.map((p,i)=>`<button class="player-row" data-player="${esc(state.match.fixture.league)}|${esc(c.team_id)}|${esc(p.player_id)}"><span class="jersey">${esc(p.jersey||'—')}</span><span><b>${esc(p.name)}</b><small>${i===0&&p===goalkeeper?'Portar':esc(p.position||'Poziție ESPN indisponibilă')}</small></span><span class="arrow">›</span></button>`).join('')}</div>`:empty('ESPN nu a furnizat un XI complet verificabil pentru acest meci.')}</section>`}).join('')}
async function openMatch(league,id,tab='analysis'){
 state.screen='detail';state.detailTab=tab;activate('home');loading('Pregătesc analiza partidei...');
 try{
  const data=await request(`/api/match/${encodeURIComponent(league)}/${encodeURIComponent(id)}`);
  state.match=data;state.lineups=null;
  drawMatch();
 }catch(e){view.innerHTML=section('MECI','Date indisponibile')+empty(esc(e.message))}
}
function drawMatch(){const data=state.match;if(!data)return;const m=data.fixture;const score=m.completed?`${m.home_goals??'—'} : ${m.away_goals??'—'}`:'VS';
 view.innerHTML=`<section class="detail-top"><button class="back" id="goBack"><svg viewBox="0 0 24 24"><path d="m15 18-6-6 6-6"/></svg>Înapoi la meciuri</button><div class="eyebrow">${esc(leagues[m.league]||m.league)} · ${when(m.kickoff)}</div><h1 class="detail-names">${esc(m.home_name)} – ${esc(m.away_name)}</h1><p class="detail-sub">${m.completed?'Meci încheiat · Date ESPN':'Analiză pre-meci · Date ESPN'}</p></section>
 <div class="score-panel"><strong>${esc(m.home_name)}</strong><div class="score-numbers">${score}<small>${m.completed?'SCOR FINAL':'URMĂTORUL MECI'}</small></div><strong>${esc(m.away_name)}</strong></div>
 <div class="tabs">${[['analysis',m.completed?'Rezultat':'Analiză'],['lineups','Formații'],['history','Evaluare']].map(([k,label])=>`<button class="tab ${k===state.detailTab?'active':''}" data-detail="${k}">${label}</button>`).join('')}</div>
 <div id="detailContent">${state.detailTab==='analysis'?(m.completed?realStatsMarkup(data):predictionMarkup(data)):state.detailTab==='lineups'?lineupsMarkup(state.lineups):archiveMarkup(data)}</div>`;
 $('#goBack').onclick=()=>state.lastHome==='history'?history():home();
 document.querySelectorAll('[data-detail]').forEach(b=>b.onclick=async()=>{state.detailTab=b.dataset.detail;drawMatch();if(state.detailTab==='lineups'&&!state.lineups)await loadLineups()});
 document.querySelectorAll('[data-scope]').forEach(b=>b.onclick=()=>{state.scopeTab=b.dataset.scope;drawMatch()});
 document.querySelectorAll('[data-metric]').forEach(b=>b.onclick=()=>{const body=document.getElementById('metric-'+b.dataset.metric);body.hidden=!body.hidden;b.setAttribute('aria-expanded',String(!body.hidden))});
 if($('#refreshMatch'))$('#refreshMatch').onclick=async()=>{const btn=$('#refreshMatch');btn.disabled=true;btn.textContent='Se descarcă...';try{await request(`/api/match/${encodeURIComponent(m.league)}/${encodeURIComponent(m.event_id)}/refresh`,{method:'POST'});toast('Statisticile ESPN au fost reîncărcate.');openMatch(m.league,m.event_id)}catch(e){toast(e.message);btn.disabled=false;btn.textContent='↻ Încearcă din nou'}};
 document.querySelectorAll('[data-player]').forEach(b=>b.onclick=()=>{const parts=b.dataset.player.split('|');openPlayer(...parts)});
}
async function loadLineups(){const m=state.match.fixture;$('#detailContent').innerHTML=`<div class="empty"><div class="loader"></div>Verific primul XI din ESPN...</div>`;
 try{state.lineups=await request(`/api/match/${encodeURIComponent(m.league)}/${encodeURIComponent(m.event_id)}/lineups`);if(state.screen==='detail'&&state.detailTab==='lineups')drawMatch()}
 catch(e){if($('#detailContent'))$('#detailContent').innerHTML=empty(esc(e.message))}}
async function history(){state.screen='history';state.lastHome='history';activate('history');loading();try{
 const data=await request('/api/history'+(state.league?'?league='+encodeURIComponent(state.league):''));state.lastHistory=data.fixtures;
 view.innerHTML=section('ARHIVĂ ESPN','Meciuri încheiate','Rezultate reale, statistici disponibile și evaluarea predicțiilor salvate înainte de start.')+
 `<div class="section-head"><h2>${data.fixtures.length} meciuri recente</h2>${leagueSelect()}</div><div class="match-list">${data.fixtures.map(matchCard).join('')||empty('Niciun rezultat descărcat încă.')}</div>`;
 $('#leagueSelect').onchange=e=>{state.league=e.target.value;history()};
 }catch(e){view.innerHTML=section('ISTORIC','Istoric indisponibil')+empty(esc(e.message))}}
function playerResult(p){return `<button class="result-item" data-player="${esc(p.league)}|${esc(p.team_id)}|${esc(p.player_id)}"><span><b>${esc(p.name)}</b><small>${esc(p.team_name)} · ${esc(p.position||'Post indisponibil')}</small></span><b class="arrow">›</b></button>`}
let searchTimer;
async function search(){state.screen='search';activate('search');view.innerHTML=section('GĂSEȘTE RAPID','Caută în Football Analyzer','Meciuri viitoare și jucători salvați în baza ESPN.')+
 `<div class="search-box"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m16 16 5 5"/></svg><input id="searchInput" class="search-input" type="search" placeholder="Echipă, meci sau jucător..." value="${esc(state.searchQuery)}" autocomplete="off" aria-label="Caută meciuri și jucători"></div><div id="searchResults">${empty('Introdu un nume pentru a începe căutarea.')}</div>`;
 const input=$('#searchInput');input.oninput=()=>{state.searchQuery=input.value;clearTimeout(searchTimer);searchTimer=setTimeout(searchResults,260)};if(state.searchQuery.trim())await searchResults();}
async function searchResults(){const q=state.searchQuery.trim();const holder=$('#searchResults');if(!holder)return;
 if(q.length<2){holder.innerHTML=empty('Tastează minimum două caractere.');return}
 holder.innerHTML='<div class="empty"><div class="loader"></div>Se caută...</div>';
 try{const [matches,people]=await Promise.all([request('/api/fixtures?scope=upcoming&q='+encodeURIComponent(q)),request('/api/players?q='+encodeURIComponent(q))]);if(state.screen!=='search'||q!==state.searchQuery.trim())return;
 holder.innerHTML=`<div class="section-head"><h2>Meciuri viitoare</h2><span class="minor">${matches.fixtures.length}</span></div>${matches.fixtures.slice(0,12).map(matchCard).join('')||empty('Niciun meci găsit.')}
 <div class="section-head"><h2>Jucători</h2><span class="minor">${people.players.length}</span></div>${people.players.map(playerResult).join('')||empty('Niciun jucător în rapoartele ESPN locale.')}`;
 }catch(e){if(holder)holder.innerHTML=empty(esc(e.message))}}
async function openPlayer(league,team,id){state.screen='player';activate('search');loading('Încarc statisticile jucătorului...');try{
 const p=await request(`/api/player/${encodeURIComponent(league)}/${encodeURIComponent(team)}/${encodeURIComponent(id)}`);state.player=p;
 view.innerHTML=`<section class="detail-top"><button class="back" id="goBack">‹ Înapoi la căutare</button><div class="eyebrow">PROFIL ESPN · ${esc(leagues[p.league]||p.league)}</div><h1 class="section-title">${esc(p.name)}</h1><p class="lead">${esc(p.team)} · ${esc(p.position||'Post necunoscut')} · Nr. ${esc(p.jersey||'—')}</p></section>
 <div class="section-head"><h2>Medii din meciurile recente</h2><span class="minor">Date raportate ESPN</span></div>
 <div class="stat-grid">${Object.entries(p.averages).map(([k,val])=>`<div class="stat-mini"><b>${val.value.toFixed(2)}</b><small>${esc(val.label)}<br>${val.samples} apariții</small></div>`).join('')||empty('ESPN nu furnizează încă suficiente date statistice.')}</div>
 <div class="section-head"><h2>Ultimele apariții</h2></div>${p.games.map(g=>`<div class="card" style="padding:13px"><div class="status-row"><strong>${when(g.kickoff)}</strong><span>${g.starter?'Titular':'A intrat pe parcurs'}</span></div><div class="stat-grid">${Object.entries(g.stats).slice(0,6).map(([k,v])=>`<div class="stat-mini"><b>${v}</b><small>${esc(labels[k]||k)}</small></div>`).join('')||'<p class="hint">Statistici individuale indisponibile.</p>'}</div></div>`).join('')}`;
 $('#goBack').onclick=search;
 }catch(e){view.innerHTML=section('PROFIL JUCĂTOR','Date indisponibile')+empty(esc(e.message))}}
async function refresh(){const btn=$('#refreshBtn');btn.classList.add('refresh-spin');try{await request('/api/refresh',{method:'POST'});toast('Actualizarea ESPN a început. Revenim automat la listă.');setTimeout(()=>{if(state.screen==='home')home()},12000)}catch(e){toast(e.message)}finally{btn.classList.remove('refresh-spin')}}
function bind(){
 $('#refreshBtn').onclick=refresh;
 document.querySelectorAll('.nav-item').forEach(b=>b.onclick=()=>{if(b.dataset.view==='home')home();else if(b.dataset.view==='history')history();else search()});
 view.addEventListener('click',e=>{const m=e.target.closest('[data-match]');if(m){const [league,id]=m.dataset.match.split('|');state.lastHome=state.screen==='history'?'history':'home';openMatch(league,id);return;}
 const p=e.target.closest('[data-player]');if(p){openPlayer(...p.dataset.player.split('|'));}});
 $('#authForm').onsubmit=e=>{e.preventDefault();state.token=$('#tokenInput').value.trim();sessionStorage.setItem('fa_token',state.token);auth(false);home()};
}
bind();home();
if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{});
