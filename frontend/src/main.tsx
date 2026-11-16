import React,{useEffect,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';
import {Job,Metrics,ModelInfo,SystemData,Account,Provider,req,setApiKey,getApiKey,saveKey,clearKey,baseName,asDate} from './api';
import {Icon,Logo,Avatar,ConfirmHost} from './ui';
import {Ctx,Login,Dashboard,NewTranslation,JobPage,Jobs,System,Datasets,Users,Settings,SearchDialog,Videos,Trash,Glossary} from './pages';

const emptyMetrics:Metrics={total:0,queued:0,processing:0,completed:0,failed:0};
const WORK:[string,string,string][]=[['/dashboard','dashboard','Dashboard'],['/new','translate','New translation'],['/jobs','jobs','Jobs'],['/videos','video','Videos']];
const ADMIN:[string,string,string][]=[['/system','health','System health'],['/datasets','datasets','Datasets'],['/glossary','book','Glossary'],['/users','users','Users'],['/settings','settings','Settings']];
const readRoute=()=>location.hash.replace(/^#/,'')||'/dashboard';
const store={get:(k:string)=>{try{return localStorage.getItem(k)||''}catch{return ''}},set:(k:string,v:string)=>{try{localStorage.setItem(k,v)}catch{}}};

function App(){
 const [route,setRoute]=useState(readRoute());
 const [key,setKey]=useState(getApiKey());
 const [account,setAccount]=useState<Account|null>(null),[providers,setProviders]=useState<Provider[]>([]),[authChecked,setAuthChecked]=useState(false);
 const [loginError,setLoginError]=useState('');
 const [metrics,setMetrics]=useState<Metrics>(emptyMetrics),[jobs,setJobs]=useState<Job[]>([]);
 const [models,setModels]=useState<ModelInfo|null>(null),[system,setSystem]=useState<SystemData|null>(null);
 const [toast,setToast]=useState<{msg:string;kind:'ok'|'err'}|null>(null);
 const [expanded,setExpanded]=useState(store.get('khmerlive_nav')!=='rail'),[mobileNav,setMobileNav]=useState(false);
 const [search,setSearch]=useState(false),[bell,setBell]=useState(false);
 const [theme,setThemeState]=useState(store.get('khmerlive_theme'));
 const [seen,setSeen]=useState(Number(store.get('khmerlive_seen')||0));
 const toastTimer=useRef<number|undefined>(undefined);
 const authed=!!key||!!account?.authenticated;

 useEffect(()=>{const f=()=>{setRoute(readRoute());setMobileNav(false);setBell(false);window.scrollTo(0,0)};addEventListener('hashchange',f);return()=>removeEventListener('hashchange',f)},[]);
 useEffect(()=>{const r=document.documentElement;if(theme)r.dataset.theme=theme;else delete r.dataset.theme},[theme]);
 useEffect(()=>{const f=(e:KeyboardEvent)=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();setSearch(v=>!v)}if(e.key==='Escape'){setBell(false)}};addEventListener('keydown',f);return()=>removeEventListener('keydown',f)},[]);
 const setTheme=(t:string)=>{setThemeState(t);store.set('khmerlive_theme',t)};
 const go=(p:string)=>{location.hash=p};
 const notify=(msg:string,kind:'ok'|'err'='ok')=>{setToast({msg,kind});clearTimeout(toastTimer.current);toastTimer.current=window.setTimeout(()=>setToast(null),kind==='err'?7000:3500)};
 const toggleNav=()=>{setExpanded(v=>{store.set('khmerlive_nav',v?'rail':'full');return !v})};

 const loadAccount=async()=>{try{const [a,p]=await Promise.all([fetch('/api/auth/me').then(r=>r.json()),fetch('/api/auth/providers').then(r=>r.json())]);setAccount(a);setProviders(p.providers||[])}catch{setAccount(null)}finally{setAuthChecked(true)}};
 useEffect(()=>{void loadAccount()},[]);

 const refresh=async()=>{
  if(!getApiKey()&&!account?.authenticated)return;
  try{
   const [m,list,mi,sys]=await Promise.all([req<Metrics>('/api/dashboard'),req<{items:Job[]}>('/api/jobs?limit=100&offset=0'),req<ModelInfo>('/api/models'),req<SystemData>('/api/system')]);
   setMetrics(m);setJobs(list.items);setModels(mi);setSystem(sys);
  }catch(e){
   const msg=String(e instanceof Error?e.message:e);
   if(msg.startsWith('401')&&!account?.authenticated){clearKey();setApiKey('');setKey('');setLoginError('Your API key was rejected. Please sign in again.')}
   else notify(msg,'err');
  }
 };
 useEffect(()=>{void refresh()},[key,account?.authenticated]);
 useEffect(()=>{if(!authed)return;const t=window.setInterval(()=>void refresh(),5000);return()=>clearInterval(t)},[key,account?.authenticated]);

 const signInWithKey=async(k:string,remember:boolean)=>{
  setLoginError('');
  const r=await fetch('/api/dashboard',{headers:{'X-API-Key':k}});
  if(!r.ok){setLoginError(r.status===401?'That API key is not valid.':'Server error '+r.status+'. Is the API running?');return}
  saveKey(k,remember);setApiKey(k);setKey(k);
 };
 const signOut=async()=>{clearKey();setApiKey('');setKey('');try{await fetch('/api/auth/logout',{method:'POST'})}catch{}setAccount(null);setJobs([]);setMetrics(emptyMetrics);void loadAccount();go('/dashboard')};

 if(!authChecked)return <div className="boot"><Logo size={44}/></div>;
 if(!authed)return <Login providers={providers} onKey={signInWithKey} error={loginError}/>;

 const userName=account?.authenticated?account.user?.name||'User':'Administrator';
 const finished=jobs.filter(j=>(j.status==='completed'||j.status==='failed'||j.status==='dispatch_failed')&&j.updated_at);
 const unread=finished.filter(j=>new Date(j.updated_at!).getTime()>seen).length;
 const openBell=()=>{setBell(v=>!v);const now=Date.now();setSeen(now);store.set('khmerlive_seen',String(now))};
 const ctx:Ctx={account,providers,isAdmin:!!key&&!account?.authenticated,userName,metrics,jobs,models,system,refresh,go,notify,openBell,unread};
 const nav=ctx.isAdmin?[...ADMIN.slice(0,1),['/trash','trash','Trash'] as [string,string,string],...ADMIN.slice(1)]:ADMIN;
 const [path,qs]=route.split('?');const query=new URLSearchParams(qs||'');
 const parts=path.split('/').filter(Boolean);const base='/'+(parts[0]||'dashboard');
 const current=base==='/job'?'/jobs':base==='/library'?'/jobs':base==='/models'?'/system':base;
 const activeJobs=metrics.queued+metrics.processing;
 const real=models?.mode==='real_subtitles';

 let page:React.ReactNode;
 switch(base){
  case '/new':page=<NewTranslation key={route} ctx={ctx} initialSrc={query.get('src')||undefined}/>;break;
  case '/job':page=parts[1]?<JobPage ctx={ctx} id={parts[1]}/>:<Jobs ctx={ctx} query={query}/>;break;
  case '/jobs':page=<Jobs key={route} ctx={ctx} query={query}/>;break;
  case '/library':page=<Jobs key={route} ctx={ctx} query={new URLSearchParams('view=grid')}/>;break;
  case '/system':case '/models':page=<System ctx={ctx}/>;break;
  case '/videos':page=<Videos key={route} ctx={ctx}/>;break;
  case '/trash':page=<Trash ctx={ctx}/>;break;
  case '/datasets':page=<Datasets ctx={ctx}/>;break;
  case '/glossary':page=<Glossary ctx={ctx}/>;break;
  case '/users':page=<Users ctx={ctx}/>;break;
  case '/settings':page=<Settings ctx={ctx} theme={theme} setTheme={setTheme} onSignOut={()=>void signOut()}/>;break;
  default:page=<Dashboard ctx={ctx}/>;
 }
 const navLink=([p,ic,label]:[string,string,string])=><a key={p} href={'#'+p} className={'nv'+(current===p?' on':'')} aria-current={current===p?'page':undefined} title={expanded?undefined:label}>
  <Icon name={ic} size={20}/><span className="nv-l">{label}</span>
  {p==='/jobs'&&activeJobs>0&&<em className="nv-count" aria-label={activeJobs+' active'}>{activeJobs}</em>}
 </a>;

 return <div className={'shell'+(expanded?' wide':' rail')+(mobileNav?' mnav':'')}>
  <nav className="side" aria-label="Main">
   <a className="side-logo" href="#/dashboard" title={expanded?undefined:'KhmerLive AI'}><Logo/><span className="nv-l brand">KhmerLive<b> AI</b></span></a>
   <button className="side-search" onClick={()=>setSearch(true)} title={expanded?undefined:'Search (⌘K)'}><Icon name="search"/><span className="nv-l">Search</span><kbd className="nv-l">⌘K</kbd></button>
   <div className="nv-group"><span className="nv-h">Workspace</span>{WORK.map(navLink)}</div>
   <div className="nv-group"><span className="nv-h">Administration</span><i className="nv-sep"/>{nav.map(navLink)}</div>
   <div className="side-foot">
    <button className="nv" onClick={toggleNav} title={expanded?undefined:'Expand sidebar'} aria-label={expanded?'Collapse sidebar':'Expand sidebar'}><Icon name={expanded?'collapse':'expand'} size={20}/><span className="nv-l">Collapse</span></button>
    <a className="nv" href="/api/docs" target="_blank" rel="noopener" title={expanded?undefined:'Help & API docs'}><Icon name="help" size={20}/><span className="nv-l">Help &amp; API docs</span></a>
    <a className="nv user" href="#/settings" title={expanded?undefined:userName}><Avatar name={userName} src={account?.user?.avatar_url} size={34}/><span className="nv-l"><b>{userName}</b><small>{real?'Real AI mode':'Demo mode'}</small></span></a>
   </div>
  </nav>
  {mobileNav&&<button className="scrim" aria-label="Close menu" onClick={()=>setMobileNav(false)}/>}
  <div className="content">
   <div className="mtop"><button className="icon-btn" aria-label="Open menu" onClick={()=>setMobileNav(true)}><Icon name="menu"/></button><Logo size={28}/><b>KhmerLive AI</b><button className="icon-btn" aria-label="Search" onClick={()=>setSearch(true)}><Icon name="search"/></button></div>
   {models&&!real&&<div className="mode-note"><Icon name="alert" size={16}/><span><b>Demo mode</b> — jobs run through the pipeline, but no real speech recognition, translation or dubbing happens. Set <code>MODEL_MODE=real_subtitles</code> to use the AI models.</span></div>}
   {models&&real&&models.subtitle_translation_configured===false&&<div className="mode-note bad"><Icon name="alert" size={16}/><span><b>AI models missing.</b> Real mode is on, but the models aren't installed. See System health.</span></div>}
   <main className="main">{page}</main>
  </div>
  {bell&&<div className="pop" role="dialog" aria-label="Notifications"><div className="pop-h"><b>Notifications</b><button className="icon-btn ghost" aria-label="Close" onClick={()=>setBell(false)}><Icon name="x" size={16}/></button></div>
   {finished.slice(0,8).map(j=><a key={j.id} href={'#/job/'+j.id}><i className={'sdot '+(j.status==='completed'?'online':'offline')}/><span><b>{baseName(j.filename)}</b><small>{j.status==='completed'?'Finished':'Failed'} · {asDate(j.updated_at)}</small></span></a>)}
   {!finished.length&&<p className="hint pad">No finished jobs yet.</p>}
  </div>}
  {search&&<SearchDialog onClose={()=>setSearch(false)} go={go}/>}
  <ConfirmHost/>
  {toast&&<div className={'toast '+toast.kind} role="status">{toast.kind==='err'?<Icon name="alert" size={18}/>:<Icon name="check" size={18}/>}<span>{toast.msg}</span><button className="icon-btn ghost" aria-label="Dismiss" onClick={()=>setToast(null)}><Icon name="x" size={14}/></button></div>}
 </div>;
}
createRoot(document.getElementById('root')!).render(<App/>);
