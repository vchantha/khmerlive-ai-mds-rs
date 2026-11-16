import React,{useEffect,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';
import {Job,Metrics,ModelInfo,SystemData,Account,Provider,req,setApiKey,getApiKey,saveKey,clearKey,baseName,asDate} from './api';
import {Icon,Logo,Avatar} from './ui';
import {Ctx,Login,Dashboard,NewJob,JobPage,MyJobs,Library,Models,Datasets,Users,SystemPage} from './pages';

const emptyMetrics:Metrics={total:0,queued:0,processing:0,completed:0,failed:0};
const nav:[string,string,string][]=[
 ['/dashboard','home','Dashboard'],['/new','plus','New Translation'],['/jobs','jobs','My Jobs'],['/library','library','Video Library'],
 ['/models','models','AI Models'],['/datasets','datasets','Datasets'],['/users','users','Users & Access'],['/system','health','System Health'],['/settings','settings','Settings'],
];
const readRoute=()=>location.hash.replace(/^#/,'')||'/dashboard';
const readTheme=()=>{try{return localStorage.getItem('khmerlive_theme')||''}catch{return ''}};

function App(){
 const [route,setRoute]=useState(readRoute());
 const [key,setKey]=useState(getApiKey());
 const [account,setAccount]=useState<Account|null>(null),[providers,setProviders]=useState<Provider[]>([]),[authChecked,setAuthChecked]=useState(false);
 const [loginError,setLoginError]=useState('');
 const [metrics,setMetrics]=useState<Metrics>(emptyMetrics),[jobs,setJobs]=useState<Job[]>([]);
 const [models,setModels]=useState<ModelInfo|null>(null),[system,setSystem]=useState<SystemData|null>(null);
 const [hostHistory,setHostHistory]=useState<{cpu:number[];mem:number[];disk:number[]}>({cpu:[],mem:[],disk:[]});
 const [toast,setToast]=useState<{msg:string;kind:'ok'|'err'}|null>(null);
 const [navOpen,setNavOpen]=useState(false),[bell,setBell]=useState(false),[banner,setBanner]=useState(true);
 const [theme,setThemeState]=useState(readTheme());
 const [seen,setSeen]=useState(()=>{try{return Number(localStorage.getItem('khmerlive_seen')||0)}catch{return 0}});
 const toastTimer=useRef<number|undefined>(undefined);
 const authed=!!key||!!account?.authenticated;

 useEffect(()=>{const f=()=>{setRoute(readRoute());setNavOpen(false);setBell(false)};addEventListener('hashchange',f);return()=>removeEventListener('hashchange',f)},[]);
 useEffect(()=>{const r=document.documentElement;if(theme)r.dataset.theme=theme;else delete r.dataset.theme},[theme]);
 const setTheme=(t:string)=>{setThemeState(t);try{localStorage.setItem('khmerlive_theme',t)}catch{}};
 const effectiveDark=theme==='dark'||(!theme&&matchMedia('(prefers-color-scheme: dark)').matches);
 const go=(p:string)=>{location.hash=p};
 const notify=(msg:string,kind:'ok'|'err'='ok')=>{setToast({msg,kind});clearTimeout(toastTimer.current);toastTimer.current=window.setTimeout(()=>setToast(null),kind==='err'?7000:3500)};

 const loadAccount=async()=>{try{const [a,p]=await Promise.all([fetch('/api/auth/me').then(r=>r.json()),fetch('/api/auth/providers').then(r=>r.json())]);setAccount(a);setProviders(p.providers||[])}catch{setAccount(null)}finally{setAuthChecked(true)}};
 useEffect(()=>{void loadAccount()},[]);

 const refresh=async()=>{
  if(!getApiKey()&&!account?.authenticated)return;
  try{
   const [m,list,mi,sys]=await Promise.all([req<Metrics>('/api/dashboard'),req<{items:Job[]}>('/api/jobs?limit=100&offset=0'),req<ModelInfo>('/api/models'),req<SystemData>('/api/system')]);
   setMetrics(m);setJobs(list.items);setModels(mi);setSystem(sys);
   const h=sys.host;if(h)setHostHistory(o=>({cpu:[...o.cpu,h.cpu_percent??0].slice(-30),mem:[...o.mem,h.memory_used_bytes??0].slice(-30),disk:[...o.disk,h.disk_used_bytes??0].slice(-30)}));
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
  if(!r.ok){setLoginError(r.status===401?'Invalid API key.':'Server error '+r.status+'. Is the API running?');return}
  saveKey(k,remember);setApiKey(k);setKey(k);if(!location.hash)go('/dashboard');
 };
 const signOut=async()=>{clearKey();setApiKey('');setKey('');try{await fetch('/api/auth/logout',{method:'POST'})}catch{}setAccount(null);setJobs([]);setMetrics(emptyMetrics);void loadAccount();go('/dashboard')};

 if(!authChecked)return <div className="boot"><Logo size={46}/></div>;
 if(!authed)return <Login providers={providers} onKey={signInWithKey} error={loginError}/>;

 const ctx:Ctx={account,providers,isAdmin:!!key&&!account?.authenticated,metrics,jobs,models,system,hostHistory,refresh,go,notify};
 const real=models?.mode==='real_subtitles';
 const userName=account?.authenticated?account.user?.name||'User':'Administrator';
 const updates=jobs.filter(j=>(j.status==='completed'||j.status==='failed'||j.status==='dispatch_failed')&&j.updated_at);
 const unread=updates.filter(j=>new Date(j.updated_at!).getTime()>seen).length;
 const openBell=()=>{setBell(v=>!v);const now=Date.now();setSeen(now);try{localStorage.setItem('khmerlive_seen',String(now))}catch{}};
 const [base,param]=(()=>{const p=route.split('/').filter(Boolean);return ['/'+(p[0]||'dashboard'),p[1]]})();
 const active=base==='/job'?'/jobs':base;
 const activeJobs=metrics.queued+metrics.processing;

 let page:React.ReactNode;
 switch(base){
  case '/new':page=<NewJob ctx={ctx}/>;break;
  case '/job':page=param?<JobPage ctx={ctx} id={param}/>:<MyJobs ctx={ctx}/>;break;
  case '/jobs':page=<MyJobs ctx={ctx}/>;break;
  case '/library':page=<Library ctx={ctx}/>;break;
  case '/models':page=<Models ctx={ctx}/>;break;
  case '/datasets':page=<Datasets ctx={ctx}/>;break;
  case '/users':page=<Users ctx={ctx}/>;break;
  case '/system':page=<SystemPage ctx={ctx} initial="health" theme={effectiveDark?'dark':'light'} setTheme={setTheme} onSignOut={()=>void signOut()}/>;break;
  case '/settings':page=<SystemPage ctx={ctx} initial="settings" theme={effectiveDark?'dark':'light'} setTheme={setTheme} onSignOut={()=>void signOut()}/>;break;
  default:page=<Dashboard ctx={ctx}/>;
 }

 return <div className={'shell'+(navOpen?' nav-open':'')}>
  <aside className="side" aria-label="Main navigation">
   <a className="side-brand" href="#/dashboard"><Logo/><b>KhmerLive AI</b></a>
   <nav>{nav.map(([path,ic,label])=><a key={path} href={'#'+path} className={active===path?'current':''} aria-current={active===path?'page':undefined}><Icon name={ic}/><span>{label}</span>{path==='/jobs'&&activeJobs>0&&<em>{activeJobs}</em>}</a>)}</nav>
   <div className="side-user"><Avatar name={userName} src={account?.user?.avatar_url} size={36}/><span><b>{userName}</b><small>{ctx.isAdmin?'Administrator':'User'}</small></span><button className="icon-btn" title="Sign out" aria-label="Sign out" onClick={()=>void signOut()}><Icon name="logout" size={17}/></button></div>
  </aside>
  {navOpen&&<button className="scrim" aria-label="Close navigation" onClick={()=>setNavOpen(false)}/>}
  <div className="content">
   <header className="top">
    <button className="icon-btn menu-btn" aria-label="Open navigation" onClick={()=>setNavOpen(true)}><Icon name="menu"/></button>
    <span className={'mode-pill '+(real?'real':'demo')} title={real?'Offline Whisper + M2M100'+(models?.khmer_dubbing_enabled?' + Khmer MMS TTS':''):'No real AI runs in demo mode'}>{models?(real?'Real mode':'Demo mode'):'…'}</span>
    <div className="top-actions">
     <button className="icon-btn" aria-label={effectiveDark?'Switch to light theme':'Switch to dark theme'} onClick={()=>setTheme(effectiveDark?'light':'dark')}><Icon name={effectiveDark?'sun':'moon'}/></button>
     <div className="bell-wrap"><button className="icon-btn" aria-label={'Notifications'+(unread?' ('+unread+' new)':'')} aria-expanded={bell} onClick={openBell}><Icon name="bell"/>{unread>0&&<i className="dot-badge"/>}</button>
      {bell&&<div className="dropdown"><b>Recent updates</b>{updates.slice(0,6).map(j=><a key={j.id} href={'#/job/'+j.id}><span className={'svc-dot '+(j.status==='completed'?'online':'offline')}><Icon name={j.status==='completed'?'check':'x'} size={12}/></span><span>{baseName(j.filename)}<small>{j.status==='completed'?'Completed':'Failed'} · {asDate(j.updated_at)}</small></span></a>)}{!updates.length&&<p className="muted small">No finished jobs yet.</p>}</div>}</div>
     <a className="icon-btn" href="/api/docs" target="_blank" rel="noopener" aria-label="API documentation"><Icon name="help"/></a>
     <a href="#/settings" aria-label="Account settings"><Avatar name={userName} src={account?.user?.avatar_url} size={34}/></a>
    </div>
   </header>
   {banner&&models&&<div className={'mode-banner '+(real&&models.subtitle_translation_configured?'real':'demo')}><Icon name={real&&models.subtitle_translation_configured?'check':'help'} size={17}/><p>{real?<><b>Real mode.</b> Offline Whisper ASR + M2M100 translation{models.khmer_dubbing_enabled?<> + Khmer MMS TTS dubbing for English → Khmer{!models.speech_dubbing_available&&' (TTS model not installed)'}</>:null}.{!models.subtitle_translation_configured&&<b> ASR/MT model weights are missing.</b>}</>:<><b>Demo mode.</b> Jobs run through the full pipeline UI, but no real speech recognition, translation or dubbing is performed.</>}</p><button className="icon-btn" aria-label="Dismiss" onClick={()=>setBanner(false)}><Icon name="x" size={16}/></button></div>}
   <main className="main">{page}</main>
  </div>
  {toast&&<div className={'toast '+toast.kind} role="status">{toast.msg}<button className="icon-btn" aria-label="Dismiss" onClick={()=>setToast(null)}><Icon name="x" size={14}/></button></div>}
 </div>;
}
createRoot(document.getElementById('root')!).render(<App/>);
