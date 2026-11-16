import React,{useEffect,useMemo,useRef,useState} from 'react';
import {Job,JobEvent,MediaItem,TrashItem,Metrics,ModelInfo,LLMInfo,SystemData,Account,Provider,DirectoryUser,YouTubeInfo,req,uploadMedia,downloadVideo,downloadBlob,saveBlob,getApiKey,baseName,shortId,asDate,asTime,size,lang,isActive,isFailed,isYouTubeUrl,sourceLabel,fmtDur,timeLeft,outputsLabel} from './api';
import {Icon,Logo,Badge,Bar,Avatar,Seg,Card,Thumb,confirmDialog} from './ui';

export type Ctx={
 account:Account|null;providers:Provider[];isAdmin:boolean;userName:string;
 metrics:Metrics;jobs:Job[];models:ModelInfo|null;system:SystemData|null;
 refresh:()=>Promise<void>;go:(path:string)=>void;
 notify:(msg:string,kind?:'ok'|'err')=>void;
 openBell:()=>void;unread:number;
};
const real=(m:ModelInfo|null)=>m?.mode==='real_subtitles';
const errText=(e:unknown)=>String(e instanceof Error?e.message:e);
const srcName=(j:Job)=>j.source_kind==='youtube'?'YouTube':j.source_kind==='url'?'Video link':'Upload';

export function Head({title,sub,crumb,children}:{title:React.ReactNode;sub?:React.ReactNode;crumb?:React.ReactNode;children?:React.ReactNode}){
 return <header className="head">{crumb&&<nav className="crumb" aria-label="Breadcrumb">{crumb}</nav>}<div className="head-row"><div className="head-txt"><h1>{title}</h1>{sub&&<p>{sub}</p>}</div>{children&&<div className="head-act">{children}</div>}</div></header>;
}
function NewBtn({go}:{go:(p:string)=>void}){return <button className="btn btn-primary" onClick={()=>go('/new')}><Icon name="plus"/>New translation</button>}

/* Submit a job from any source. Returns the job id. */
async function createUrlJob(url:string,source:'en'|'km',seconds=30){
 const r=await req<{job_id:string}>('/api/jobs/from-url',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:url.trim(),capture_seconds:seconds,source_lang:source,target_lang:source==='en'?'km':'en'})});
 return r.job_id;
}
async function createUploadJob(file:File,source:'en'|'km',onPct:(n:number)=>void){
 const media=await uploadMedia(file,onPct);
 const r=await req<{job_id:string}>('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({media_id:media.media_id,source_lang:source,target_lang:source==='en'?'km':'en'})});
 return r.job_id;
}
async function jobAction(ctx:Ctx,j:Job,which:'cancel'|'retry',after?:()=>void,force?:boolean){
 if(which==='cancel'&&!force&&!await confirmDialog({tone:'warn',icon:'x',title:'Cancel this job?',
  message:<>“<b>{baseName(j.filename)}</b>” stops right away. The step that's running is interrupted and nothing is published.</>,
  details:['You can start it again later with Retry.'],confirmLabel:'Cancel job',cancelLabel:'Keep running'}))return;
 try{const r=await req<{status?:string}>('/api/jobs/'+j.id+'/'+which,{method:'POST'});ctx.notify(which==='cancel'?(r.status==='cancelled'?'Job cancelled':'Stopping job…'):'Job queued again');after?.();void ctx.refresh()}catch(e){ctx.notify(errText(e),'err')}
}

async function trashJob(ctx:Ctx,j:Job,after?:()=>void){
 if(isActive(j.status)){ctx.notify('Cancel the job before deleting it','err');return}
 if(!await confirmDialog({tone:'danger',title:'Move job to Trash?',
  message:<>“<b>{baseName(j.filename)}</b>” will disappear from your Jobs list.</>,
  details:[ctx.isAdmin?'You can restore it from the Trash.':'An administrator can restore it if needed.','The source video is kept.'],
  confirmLabel:'Move to Trash',cancelLabel:'Keep job'}))return;
 try{await req('/api/jobs/'+j.id,{method:'DELETE'});ctx.notify('Job moved to the Trash');after?.();void ctx.refresh()}catch(e){ctx.notify(errText(e),'err')}
}
const JOB_SORTS:[string,string][]=[['newest','Newest first'],['oldest','Oldest first'],['updated','Recently updated'],['name_asc','Name A–Z'],['name_desc','Name Z–A'],['status','Status']];

/* ================= Sign in ================= */
export function Login({providers,onKey,error}:{providers:Provider[];onKey:(k:string,remember:boolean)=>Promise<void>;error:string}){
 const [key,setKey]=useState(''),[show,setShow]=useState(false),[remember,setRemember]=useState(true),[busy,setBusy]=useState(false);
 const submit=async(e:React.FormEvent)=>{e.preventDefault();if(!key.trim())return;setBusy(true);try{await onKey(key.trim(),remember)}finally{setBusy(false)}};
 const google=providers.find(p=>p.id==='google'),github=providers.find(p=>p.id==='github');
 const social=(p:Provider|undefined,label:string,icon:React.ReactNode)=>p&&<button type="button" className="btn btn-outline btn-lg" disabled={!p.enabled} title={p.enabled?undefined:label+' sign-in is not configured on this server'} onClick={()=>{window.location.href='/api/auth/login/'+p.id}}>{icon}{label}</button>;
 return <div className="login">
  <aside className="login-hero">
   <div className="login-brand"><Logo size={40}/><span>KhmerLive<b> AI</b></span></div>
   <div>
    <p className="login-km km">នាំវីដេអូពីពិភពលោក មកជាភាសាខ្មែរ</p>
    <h1>Translate and dub any English video into natural Khmer.</h1>
    <ul>
     <li><Icon name="check"/>Khmer voice-over and Khmer subtitles, generated offline on your own server</li>
     <li><Icon name="check"/>Review the bilingual transcript and download MP4, SRT and TXT</li>
     <li><Icon name="check"/>Works with YouTube links, uploads and streaming URLs</li>
    </ul>
   </div>
  </aside>
  <main className="login-main">
   <form className="login-form" onSubmit={submit}>
    <h2>Sign in</h2>
    <p className="muted">Use a connected account, or the administrator API key from <code>.env</code>.</p>
    {(google||github)&&<div className="login-social">
     {social(google,'Google',<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.27-4.74 3.27-8.1z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.230 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23z"/><path fill="#FBBC05" d="M5.84 14.09a6.6 6.6 0 0 1 0-4.18V7.07H2.18a11 11 0 0 0 0 9.86l3.66-2.84z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15A11 11 0 0 0 2.18 7.07l3.66 2.84C6.71 7.31 9.14 5.38 12 5.38z"/></svg>)}
     {social(github,'GitHub',<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 .5a11.5 11.5 0 0 0-3.64 22.41c.58.1.79-.25.79-.56v-2c-3.2.7-3.88-1.37-3.88-1.37-.53-1.33-1.28-1.69-1.28-1.690-1.05-.71.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.68 0-1.26.45-2.28 1.19-3.090-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.77 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.83 1.19 3.09 0 4.41-2.69 5.38-5.26 5.67.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .5z"/></svg>)}
    </div>}
    <div className="or"><span>or with API key</span></div>
    <label className="field"><span>API key</span>
     <div className="input-wrap"><input type={show?'text':'password'} aria-label="API key" placeholder="API_KEY from .env" value={key} onChange={e=>setKey(e.target.value)} autoComplete="current-password"/><button type="button" className="icon-btn ghost" aria-label={show?'Hide key':'Show key'} onClick={()=>setShow(v=>!v)}><Icon name="eye"/></button></div>
    </label>
    <label className="check"><input type="checkbox" checked={remember} onChange={e=>setRemember(e.target.checked)}/>Keep me signed in on this browser</label>
    {error&&<div className="alert alert-err" role="alert">{error}</div>}
    <button className="btn btn-primary btn-lg btn-block" disabled={busy||!key.trim()}>{busy?'Signing in…':'Sign in'}</button>
    <p className="login-foot"><a href="/api/docs" target="_blank" rel="noopener">API documentation</a></p>
   </form>
  </main>
 </div>;
}

/* ================= Dashboard ================= */
const DAY=86400000;
function perDay(jobs:Job[],days:number){
 const t=new Date();t.setHours(0,0,0,0);const start=t.getTime()-(days-1)*DAY;
 const n=Array.from({length:days},()=>0);
 for(const j of jobs){if(!j.created_at)continue;const i=Math.floor((new Date(j.created_at).getTime()-start)/DAY);if(i>=0&&i<days)n[i]++}
 return n.map((v,i)=>({v,d:new Date(start+i*DAY)}));
}
function Bars({data}:{data:{v:number;d:Date}[]}){
 const max=Math.max(1,...data.map(x=>x.v));const top=data.reduce((a,b,i)=>b.v>data[a].v?i:a,0);
 const every=Math.ceil(data.length/7);
 return <div className="bars" role="img" aria-label="Jobs created per day">
  {data.map((x,i)=><div className="bar-col" key={i} title={x.d.toLocaleDateString()+': '+x.v+' jobs'}>
   <span className={'bar-n'+(i===top&&x.v?' top':'')}>{data.length<=14&&x.v?x.v:''}</span>
   <i className={i===top&&x.v?'top':''} style={{height:(x.v?Math.max(4,x.v*100/max):0)+'%'}}/>
   <small>{i%every===0||i===data.length-1?x.d.toLocaleDateString(undefined,data.length<=7?{weekday:'short',day:'numeric'}:{month:'short',day:'numeric'}):''}</small>
  </div>)}
 </div>;
}
function usePlayback(job:Job|null){
 const [p,setP]=useState<{video_url:string;captions_url:string|null}|null>(null),[err,setErr]=useState('');
 useEffect(()=>{let closed=false;setP(null);setErr('');if(!job||!job.has_output)return;
  void req<{video_url:string;captions_url:string|null}>('/api/jobs/'+job.id+'/player-token').then(r=>{if(!closed)setP(r)}).catch(e=>{if(!closed)setErr(errText(e))});
  return()=>{closed=true}},[job?.id,job?.has_output]);
 return {p,err};
}
function VideoCard({job,go}:{job:Job;go:(p:string)=>void}){
 const {p}=usePlayback(job);const [dur,setDur]=useState<number|null>(null);
 return <button className="vcard" onClick={()=>go('/job/'+job.id)}>
  <span className="vthumb">{p&&<video muted preload="metadata" src={p.video_url+'#t=2'} onLoadedMetadata={e=>setDur(e.currentTarget.duration)}/>}<span className="vplay"><Icon name="play" size={14}/></span>{dur!=null&&<em>{fmtDur(dur)}</em>}</span>
  <span className="vmeta"><b title={job.filename}>{baseName(job.filename)}</b><small>{shortId(job.id)} · {outputsLabel(job)} · {asDate(job.updated_at||job.created_at)}</small></span>
 </button>;
}
export function Dashboard({ctx}:{ctx:Ctx}){
 const [range,setRange]=useState('7');const [link,setLink]=useState(''),[busy,setBusy]=useState(false);
 const {metrics:m,jobs}=ctx;
 const hour=new Date().getHours();const greet=hour<12?'Good morning':hour<18?'Good afternoon':'Good evening';
 const active=jobs.filter(j=>isActive(j.status)),failed=jobs.filter(j=>isFailed(j.status)).slice(0,3),done=jobs.filter(j=>j.status==='completed'&&j.has_output).slice(0,4);
 const data=useMemo(()=>perDay(jobs,Number(range)),[jobs,range]);
 const busiest=data.reduce((a,b)=>b.v>a.v?b:a,data[0]);
 const count=(k:string)=>jobs.filter(j=>(j.source_kind||'upload')===k).length;
 const sources:[string,number,string][]=[['YouTube',count('youtube'),'s1'],['File upload',count('upload'),'s2'],['Video link',count('url'),'s3']];
 const total=jobs.length;
 const pct=(n:number)=>m.total?Math.round(n*100/m.total):0;
 const quick=async()=>{const u=link.trim();if(!/^https?:\/\/.+/i.test(u)){ctx.notify('Paste a YouTube, MP4 or HLS link','err');return}
  setBusy(true);try{const id=await createUrlJob(u,'en');setLink('');ctx.notify(isYouTubeUrl(u)?'YouTube video queued':'Video link queued');void ctx.refresh();ctx.go('/job/'+id)}catch(e){ctx.notify(errText(e),'err')}finally{setBusy(false)}};
 const sub=[active.length?active.length+(active.length===1?' video is':' videos are')+' processing.':'Nothing is processing right now.',m.failed?' '+m.failed+' failed job'+(m.failed===1?' needs':'s need')+' your attention.':''].join('');
 return <>
  <Head title={greet+', '+ctx.userName.split(' ')[0]} sub={sub}>
   <select className="select" value={range} onChange={e=>setRange(e.target.value)} aria-label="Date range"><option value="7">Last 7 days</option><option value="30">Last 30 days</option></select>
   <button className="icon-btn" aria-label={'Notifications'+(ctx.unread?', '+ctx.unread+' new':'')} onClick={ctx.openBell}><Icon name="bell"/>{ctx.unread>0&&<i className="dot"/>}</button>
   <NewBtn go={ctx.go}/>
  </Head>
  <Card title="Quick translate">
   <form className="quick" onSubmit={e=>{e.preventDefault();void quick()}}>
    <label className="input-icon"><Icon name="link"/><input value={link} onChange={e=>setLink(e.target.value)} placeholder="Paste a YouTube, MP4 or HLS link" aria-label="Video link"/></label>
    <button className="btn btn-primary btn-lg" disabled={busy||!link.trim()}>{busy?'Starting…':'Translate'}</button>
    <button type="button" className="btn btn-outline btn-lg" onClick={()=>ctx.go('/new?src=upload')}><Icon name="upload"/>Upload file</button>
   </form>
   <p className="hint">English → Khmer{real(ctx.models)&&ctx.models?.khmer_dubbing_enabled?', with dubbing and subtitles':real(ctx.models)?', with subtitles':' (demo mode — no AI processing)'}. Need other options? <a href="#/new">Open the full form</a>.</p>
  </Card>
  <div className="stats">
   <div className="card pad stat"><small>Total jobs</small><b>{m.total}</b><span className="muted">All time</span></div>
   <div className="card pad stat"><small>Completed</small><b>{m.completed}</b><span className="ok">{pct(m.completed)}% success rate</span></div>
   <div className="card pad stat"><small>Processing</small><b>{m.processing+m.queued}</b><span className="info">{m.processing} running · {m.queued} queued</span></div>
   <div className="card pad stat"><small>Failed</small><b>{m.failed}</b>{m.failed?<a className="bad" href="#/jobs?status=failed">Review failed jobs →</a>:<span className="muted">None</span>}</div>
  </div>
  <div className="grid2">
   <Card title="In progress" extra={<a href="#/jobs?status=active">View all</a>}>
    {active.slice(0,3).map(j=><button key={j.id} className="prog-row" onClick={()=>ctx.go('/job/'+j.id)}><Thumb/><span className="prog-body"><span className="prog-top"><b>{baseName(j.filename)}</b><em>{j.progress}%</em></span><Bar value={j.progress}/><small>{j.stage?j.stage.charAt(0).toUpperCase()+j.stage.slice(1):'Queued'}{timeLeft(j)&&' · '+timeLeft(j)}</small></span></button>)}
    {!active.length&&<div className="empty-s"><Icon name="check"/>No jobs running. <a href="#/new">Start a translation</a></div>}
   </Card>
   <Card title="Needs attention" extra={failed.length?<span className="count-bad">{m.failed}</span>:undefined}>
    {failed.map(j=><div key={j.id} className="attn"><Icon name="alert" size={20}/><div><b>{baseName(j.filename)}</b><p>{j.error||'The job failed.'}</p><div className="attn-act"><button className="btn btn-outline btn-sm" onClick={()=>void jobAction(ctx,j,'retry')}>Retry</button><button className="btn btn-ghost btn-sm" onClick={()=>ctx.go('/job/'+j.id)}>Details</button></div></div></div>)}
    {!failed.length&&<div className="empty-s"><Icon name="check"/>Nothing needs your attention.</div>}
   </Card>
  </div>
  <div className="grid2">
   <Card title="Jobs per day">
    <p className="hint top">{data[0].d.toLocaleDateString(undefined,{month:'short',day:'numeric'})} – {data[data.length-1].d.toLocaleDateString(undefined,{month:'short',day:'numeric'})}{busiest.v?' · busiest day was '+busiest.d.toLocaleDateString(undefined,{weekday:'long'})+' ('+busiest.v+')':''}</p>
    <Bars data={data}/>
   </Card>
   <Card title="Where videos come from">
    <div className="stack" aria-hidden="true">{sources.map(([l,v,c])=>v?<i key={l} className={c} style={{flexGrow:v}}/>:null)}{!total&&<i className="s3" style={{flexGrow:1}}/>}</div>
    <ul className="src-list">{sources.map(([l,v,c])=><li key={l}><i className={c}/><span>{l}</span><em>{v} jobs</em><b>{total?Math.round(v*100/total):0}%</b></li>)}</ul>
    {jobs.length>=100&&<p className="hint">Based on the 100 most recent jobs.</p>}
   </Card>
  </div>
  <div className="sec-h"><h2>Recently completed</h2><a href="#/jobs?view=grid">Open library</a></div>
  <div className="vgrid">{done.map(j=><VideoCard key={j.id} job={j} go={ctx.go}/>)}{!done.length&&<p className="muted">Finished videos will appear here.</p>}</div>
 </>;
}

/* ================= New translation ================= */
export function NewTranslation({ctx,initialSrc}:{ctx:Ctx;initialSrc?:string}){
 const m=ctx.models;const isReal=real(m);
 const [src,setSrc]=useState<'youtube'|'upload'|'url'>(initialSrc==='upload'?'upload':initialSrc==='url'?'url':'youtube');
 const [yt,setYt]=useState(''),[info,setInfo]=useState<YouTubeInfo|null>(null),[infoState,setInfoState]=useState<'idle'|'loading'|'error'>('idle'),[infoErr,setInfoErr]=useState('');
 const [file,setFile]=useState<File|null>(null),[fileDur,setFileDur]=useState<number|null>(null),[drag,setDrag]=useState(false);
 const [url,setUrl]=useState(''),[seconds,setSeconds]=useState(30);
 const [spoken,setSpoken]=useState<'en'|'km'>('en');
 const [busy,setBusy]=useState(false),[pct,setPct]=useState<number|null>(null),[err,setErr]=useState('');
 const input=useRef<HTMLInputElement>(null);
 useEffect(()=>{if(initialSrc==='upload')setTimeout(()=>input.current?.click(),150)},[]);
 // YouTube preview (debounced)
 useEffect(()=>{setInfo(null);setInfoErr('');if(src!=='youtube'||!isYouTubeUrl(yt)){setInfoState('idle');return}
  setInfoState('loading');let off=false;
  const t=setTimeout(()=>{req<YouTubeInfo>('/api/youtube/info?url='+encodeURIComponent(yt.trim())).then(r=>{if(!off){setInfo(r);setInfoState('idle')}}).catch(e=>{if(!off){setInfoErr(errText(e).replace(/^\d+: /,''));setInfoState('error')}})},500);
  return()=>{off=true;clearTimeout(t)}},[yt,src]);
 const choose=(f?:File)=>{if(!f)return;if(!f.name.toLowerCase().endsWith('.mp4')){setErr('Only MP4 files are supported. Export your video as MP4 (H.264).');return}setErr('');setFile(f);setFileDur(null);
  const v=document.createElement('video');v.preload='metadata';v.onloadedmetadata=()=>{setFileDur(v.duration);URL.revokeObjectURL(v.src)};v.src=URL.createObjectURL(f)};
 const tgt=spoken==='en'?'km':'en';
 const dub=isReal&&spoken==='en'&&!!m?.khmer_dubbing_enabled;
 const missing=isReal&&(m?.subtitle_translation_configured===false||(dub&&!m?.speech_dubbing_available));
 const ytOk=isYouTubeUrl(yt)&&infoState!=='error'&&!info?.is_live;
 const urlOk=/^https?:\/\/.+/i.test(url.trim())&&!isYouTubeUrl(url);
 const ready=src==='youtube'?ytOk:src==='upload'?!!file:urlOk;
 const limit=m?.max_video_duration_seconds||600;
 const length=src==='youtube'?(info?.duration?Math.min(info.duration,limit):null):src==='upload'?fileDur:seconds;
 const estimate=length?(isReal?Math.max(1,Math.round(length*1.7/60)):1):null;
 const outputs=[dub&&'Dubbing',isReal&&'SRT','Transcript'].filter(Boolean).join(', ');
 let urlName='—';try{if(urlOk)urlName=new URL(url.trim()).pathname.split('/').pop()||'Video link'}catch{}
 const title=src==='youtube'?(info?.title||(isYouTubeUrl(yt)?'YouTube video':'—')):src==='upload'?(file?baseName(file.name):'—'):urlName;
 const submit=async()=>{setBusy(true);setErr('');
  try{let id:string;
   if(src==='upload'){setPct(0);id=await createUploadJob(file!,spoken,setPct)}
   else id=await createUrlJob(src==='youtube'?yt:url,spoken,seconds);
   ctx.notify('Translation started');void ctx.refresh();ctx.go('/job/'+id);
  }catch(e){setErr(errText(e).replace(/^\d+: /,''))}finally{setBusy(false);setPct(null)}};
 return <>
  <Head crumb={<><a href="#/dashboard">Dashboard</a> / New translation</>} title="New translation" sub="Everything on one page. Defaults are filled in — most videos only need a source."/>
  <div className="form-grid">
   <div className="form-col">
    <Card>
     <h2 className="step-h"><span>1</span>Video source</h2>
     <Seg label="Video source" value={src} onChange={setSrc} items={[['youtube','YouTube link'],['upload','Upload file'],['url','Video URL']]}/>
     {src==='youtube'&&<>
      <label className="field"><span>YouTube link</span><input value={yt} onChange={e=>setYt(e.target.value)} placeholder="https://www.youtube.com/watch?v=… or https://youtu.be/…" inputMode="url"/></label>
      {yt.trim()&&!isYouTubeUrl(yt)&&<p className="field-err">That isn't a YouTube link. For MP4 or HLS files use “Video URL”.</p>}
      {isYouTubeUrl(yt)&&<div className="preview">
       <span className="pthumb">{info?.thumbnail?<img src={info.thumbnail} alt="" referrerPolicy="no-referrer"/>:null}{info?.duration!=null&&<em>{fmtDur(info.duration)}</em>}</span>
       <div className="pinfo">{infoState==='loading'?<><span className="sk w60"/><span className="sk w40"/></>:infoState==='error'?<><b>Can't read this video</b><small className="bad">{infoErr}</small></>:info?<><b>{info.title}</b><small>{info.duration!=null&&fmtDur(info.duration)+' min'}{info.height?' · '+info.height+'p':''}{info.uploader?' · '+info.uploader:''}</small></>:null}</div>
       {info&&!info.is_live&&<span className={info.trimmed_to_seconds?'pstate warn':'pstate ok'}><Icon name={info.trimmed_to_seconds?'warn':'check'} size={16}/>{info.trimmed_to_seconds?'First '+Math.round(info.trimmed_to_seconds/60)+' min will be used':'Ready'}</span>}
       {info?.is_live&&<span className="pstate bad"><Icon name="x" size={16}/>Live streams aren't supported</span>}
      </div>}
     </>}
     {src==='upload'&&<div className={'drop'+(drag?' drag':'')} role="button" tabIndex={0} onClick={()=>input.current?.click()} onKeyDown={e=>{if(e.key==='Enter'||e.key===' ')input.current?.click()}} onDragOver={e=>{e.preventDefault();setDrag(true)}} onDragLeave={()=>setDrag(false)} onDrop={e=>{e.preventDefault();setDrag(false);choose(e.dataTransfer.files[0])}}>
      <Icon name="upload" size={26}/>{file?<><b>{file.name}</b><span>{size(file.size)}{fileDur?' · '+fmtDur(fileDur):''} · click to replace</span></>:<><b>Drop an MP4 here or click to browse</b><span>H.264 video · longer videos are limited to {Math.round(limit/60)} min</span></>}
      <input ref={input} type="file" accept=".mp4,video/mp4" hidden onChange={e=>choose(e.target.files?.[0])}/>
     </div>}
     {src==='url'&&<div className="row2">
      <label className="field grow"><span>MP4 or HLS (.m3u8) link</span><input value={url} onChange={e=>setUrl(e.target.value)} placeholder="https://media.example.org/live/index.m3u8" inputMode="url"/></label>
      <label className="field"><span>Record</span><select value={seconds} onChange={e=>setSeconds(Number(e.target.value))}>{[15,30,60,120].map(s=><option key={s} value={s}>{s} seconds</option>)}</select></label>
     </div>}
     {src==='url'&&url.trim()&&isYouTubeUrl(url)&&<p className="field-err">YouTube links go in the “YouTube link” tab.</p>}
     {src==='url'&&<p className="hint">The host must be in the server's <code>STREAM_ALLOWED_HOSTS</code> allowlist.</p>}
    </Card>
    <Card>
     <h2 className="step-h"><span>2</span>Language &amp; outputs</h2>
     <div className="lang">
      <label className="field"><span>Spoken language</span><select value={spoken} onChange={e=>setSpoken(e.target.value as 'en'|'km')}><option value="en">English</option><option value="km">Khmer (ខ្មែរ)</option></select></label>
      <Icon name="arrowR" className="lang-arrow"/>
      <label className="field"><span>Translate into</span><select value={tgt} onChange={e=>setSpoken(e.target.value==='km'?'en':'km')}><option value="km">Khmer (ខ្មែរ)</option><option value="en">English</option></select></label>
     </div>
     <p className="lbl">What you'll get</p>
     <div className="opts">
      <div className={'opt'+(dub?' on':' off')}><Icon name={dub?'check':'x'} size={16}/><div><b>Khmer dubbing</b><small>{dub?'Replaces the original voice with Khmer speech':spoken==='km'?'Khmer → English is subtitle-only':isReal?'Turned off on the server':'Not available in demo mode'}</small></div></div>
      <div className={'opt'+(isReal?' on':' off')}><Icon name={isReal?'check':'x'} size={16}/><div><b>Subtitle file (SRT)</b><small>{isReal?'Also embedded as a subtitle track':'Not available in demo mode'}</small></div></div>
      <div className="opt on"><Icon name="check" size={16}/><div><b>Bilingual transcript</b><small>{lang(spoken)} and {lang(tgt)}, as text</small></div></div>
     </div>
     <p className="hint">Outputs are decided by the server configuration ({isReal?'real AI mode':'demo mode'}); they can't be changed per job yet.</p>
    </Card>
    {dub&&<Card>
     <h2 className="step-h"><span>3</span>Khmer voice</h2>
     <div className="voice on"><div><b>MMS Khmer</b><small>facebook/mms-tts-khm · single voice · research licence (non-commercial)</small></div><Icon name="check"/></div>
     <p className="hint">The dubbed track replaces the original audio — background music is not kept. Long lines are spoken faster so they fit their timing.</p>
    </Card>}
   </div>
   <aside className="card pad summary">
    <h2>Summary</h2>
    <dl>
     <dt>Video</dt><dd title={title}>{title}</dd>
     <dt>Length</dt><dd>{length?fmtDur(length):'—'}</dd>
     <dt>Language</dt><dd>{lang(spoken)} → {lang(tgt)}</dd>
     <dt>Outputs</dt><dd>{outputs}</dd>
     <dt>Voice</dt><dd>{dub?'MMS Khmer':'—'}</dd>
    </dl>
    {estimate&&<div className="eta"><Icon name="clock"/><div><b>Ready in about {estimate} minute{estimate===1?'':'s'}</b><small>You can leave this page — the job keeps running.</small></div></div>}
    {missing&&<div className="alert alert-err">AI models are missing on the server. Install them before starting.</div>}
    {err&&<div className="alert alert-err" role="alert">{err}</div>}
    {pct!==null&&<div className="upl"><span>Uploading {pct}%</span><Bar value={pct}/></div>}
    <button className="btn btn-primary btn-lg btn-block" disabled={!ready||busy||missing} onClick={()=>void submit()}>{busy?(pct!==null?'Uploading…':'Starting…'):'Start translation'}</button>
    {!ready&&<p className="hint center">{src==='upload'?'Choose a video to continue.':'Paste a link to continue.'}</p>}
   </aside>
  </div>
 </>;
}

/* ================= Job: in progress / review ================= */
const stageLog=new Map<string,{t:Date;msg:string}[]>();
function record(j:Job){const log=stageLog.get(j.id)||[];const msg=j.stage||j.status;if(!log.length||log[log.length-1].msg!==msg){log.push({t:new Date(),msg});stageLog.set(j.id,log.slice(-50))}}
type StepState='done'|'run'|'next'|'wait'|'fail'|'skip';
function stepsFor(j:Job,dub:boolean){
 const p=j.progress||0,done=j.status==='completed',stopped=isFailed(j.status)||j.status==='cancelled';
 const acq=j.source_kind==='url'?15:25;
 const defs:[string,number,number,boolean][]=[['Download',0,acq,true],['Transcribe',acq,65,true],['Translate',45,65,true],['Khmer voice',70,85,dub],['Sync audio',65,dub?70:85,true],['Render video',85,101,true]];
 let nextSet=false;
 return defs.map(([title,s,e,applies])=>{
  let state:StepState;
  if(!applies)state='skip';
  else if(done||p>=e||(title==='Sync audio'&&dub&&p>=85))state='done';
  else if(p>=s)state=stopped?'fail':'run';
  else if(!nextSet&&!stopped){state='next';nextSet=true}
  else state='wait';
  return {title,state};
 });
}
export function JobPage({ctx,id}:{ctx:Ctx;id:string}){
 const [job,setJob]=useState<Job|null>(null),[err,setErr]=useState(''),[forceProgress,setForceProgress]=useState(false);
 const load=async()=>{try{const j=await req<Job>('/api/jobs/'+id);record(j);setJob(j);setErr('')}catch(e){setErr(errText(e))}};
 useEffect(()=>{setJob(null);setForceProgress(false);void load()},[id]);
 useEffect(()=>{if(!job||!isActive(job.status))return;const t=setInterval(()=>void load(),2500);return()=>clearInterval(t)},[job?.status,id]);
 if(err&&!job)return <><Head crumb={<><a href="#/jobs">Jobs</a> / {id.slice(0,8)}</>} title="Job not found"/><div className="alert alert-err">{err}</div></>;
 if(!job)return <div className="card pad"><span className="sk w60"/><span className="sk w40"/></div>;
 const view=job.status==='completed'&&!forceProgress?<Review ctx={ctx} job={job} onPipeline={()=>setForceProgress(true)}/>
  :<Progress ctx={ctx} job={job} reload={load} onResult={job.status==='completed'?()=>setForceProgress(false):undefined}/>;
 return <>{view}<JobLogs ctx={ctx} job={job}/></>;
}

/* ---------- Pipeline log (steps + LLM tasks) ---------- */
const STAGE_NAMES:Record<string,string>={job:'Job',prepare:'Prepare',download:'Source',extract_audio:'Audio',asr_translate:'Speech + translation',
 llm_postedit:'LLM post-edit',llm:'LLM',tts:'Khmer voice',mux:'Mux',upload:'Publish'};
const fmtSec=(s:number|null)=>s==null?'':s<1?Math.round(s*1000)+' ms':s<90?s.toFixed(1)+' s':Math.floor(s/60)+' min '+Math.round(s%60)+' s';
const fmtVal=(v:unknown):string=>v==null?'—':typeof v==='object'?Object.entries(v as Record<string,unknown>).map(([k,x])=>k+': '+fmtVal(x)).join(', '):String(v);
function JobLogs({ctx,job}:{ctx:Ctx;job:Job}){
 const [open,setOpen]=useState(isActive(job.status)||isFailed(job.status));
 const [tab,setTab]=useState<'steps'|'llm'>('steps');
 const [events,setEvents]=useState<JobEvent[]|null>(null);
 const [filter,setFilter]=useState<'all'|'changed'|'kept'>('all'),[q,setQ]=useState('');
 const load=async()=>{try{setEvents((await req<{items:JobEvent[]}>('/api/jobs/'+job.id+'/events')).items)}catch(e){ctx.notify(errText(e),'err')}};
 useEffect(()=>{if(open)void load()},[open,job.id,job.status,job.progress]);
 useEffect(()=>{if(!open||!isActive(job.status))return;const t=setInterval(()=>void load(),3000);return()=>clearInterval(t)},[open,job.status,job.id]);
 const steps=(events||[]).filter(e=>e.stage!=='llm');
 const llm=(events||[]).filter(e=>e.stage==='llm').map(e=>({...(e.data as Record<string,unknown>),level:e.level,id:e.id}) as {id:number;index:number;english:string;draft:string;output:string|null;status:string;seconds:number|null;error:string|null;level:string});
 const changed=llm.filter(t=>t.status==='edited'&&t.output!==t.draft).length;
 const shown=llm.filter(t=>(filter==='all'||(filter==='changed'?t.status==='edited':t.status!=='edited'))&&(!q||[t.english,t.draft,t.output].some(x=>x&&x.toLowerCase().includes(q.toLowerCase()))));
 const download=()=>saveBlob(new Blob([JSON.stringify(events||[],null,2)],{type:'application/json'}),'job-'+shortId(job.id)+'-log.json');
 return <section className="card logs">
  <button className="logs-toggle" aria-expanded={open} onClick={()=>setOpen(v=>!v)}>
   <Icon name="file"/><span><b>Pipeline log</b><small>Every step with timings{llm.length?' · '+llm.length+' LLM tasks':''}</small></span><Icon name={open?'chevron-up':'chevron-down'} size={18}/>
  </button>
  {open&&<div className="logs-body">
   <div className="logs-bar">
    <Seg label="Log view" value={tab} onChange={setTab} items={[['steps',<>Steps <em>{steps.length}</em></>],['llm',<>LLM tasks <em>{llm.length}</em></>]]}/>
    <div className="toolbar-r">
     {tab==='llm'&&<><label className="input-icon"><Icon name="search"/><input placeholder="Search text" value={q} onChange={e=>setQ(e.target.value)} aria-label="Search LLM tasks"/></label>
      <select className="select" value={filter} onChange={e=>setFilter(e.target.value as 'all')} aria-label="Filter LLM tasks"><option value="all">All lines</option><option value="changed">Edited by LLM</option><option value="kept">Kept original / failed</option></select></>}
     <button className="btn btn-outline btn-sm" onClick={()=>void load()}><Icon name="refresh" size={15}/>Refresh</button>
     <button className="btn btn-outline btn-sm" disabled={!events?.length} onClick={download}><Icon name="download" size={15}/>JSON</button>
    </div>
   </div>
   {!events&&<span className="sk w80"/>}
   {events&&tab==='steps'&&(steps.length?<ol className="logs-steps">{steps.map(e=><li key={e.id} className={'lv-'+e.level}>
     <time>{e.at?new Date(e.at).toLocaleTimeString(undefined,{hour12:false}):''}</time>
     <span className="logs-stage">{STAGE_NAMES[e.stage]||e.stage}</span>
     <div className="logs-msg"><b>{e.message}</b>{e.data&&<small>{Object.entries(e.data).map(([k,v])=><span key={k}><i>{k.replace(/_/g,' ')}</i> {fmtVal(v)}</span>)}</small>}</div>
     <span className="logs-dur">{fmtSec(e.seconds)}</span>
    </li>)}</ol>:<div className="empty"><b>No log entries yet</b><span>Jobs processed before this update have no step log.</span></div>)}
   {events&&tab==='llm'&&(llm.length?<>
    <p className="hint">{llm.length} lines sent to the LLM · {changed} changed · {llm.filter(t=>t.status!=='edited').length} kept the machine translation · avg {fmtSec(llm.reduce((a,t)=>a+(t.seconds||0),0)/llm.length)} per line</p>
    <div className="table-wrap"><table className="table logs-llm"><thead><tr><th>#</th><th>English</th><th>Machine draft</th><th>LLM output</th><th>Result</th><th>Time</th></tr></thead><tbody>
     {shown.map(t=><tr key={t.id} className="no-click">
      <td className="nowrap">{t.index+1}</td><td>{t.english}</td><td className="km">{t.draft}</td>
      <td className="km">{t.output??<span className="muted">—</span>}</td>
      <td><span className={'badge badge-'+(t.status==='edited'?'ok':'warn')} title={t.error||undefined}>{t.status==='edited'?(t.output===t.draft?'Unchanged':'Edited'):t.status}</span>{t.error&&<small className="clip" title={t.error}>{t.error}</small>}</td>
      <td className="nowrap">{fmtSec(t.seconds)}</td></tr>)}
     {!shown.length&&<tr><td colSpan={6}><div className="empty"><b>No lines match</b></div></td></tr>}
    </tbody></table></div></>
    :<div className="empty"><b>No LLM tasks</b><span>LLM post-editing was off for this job or hasn't run yet.</span></div>)}
  </div>}
 </section>;
}
function jobMeta(j:Job,extra?:string){return [srcName(j),j.capture_seconds&&j.source_kind!=='youtube'?j.capture_seconds+' s capture':'',lang(j.source_lang)+' → '+lang(j.target_lang),outputsLabel(j),extra].filter(Boolean).join(' · ')}
function Progress({ctx,job,reload,onResult}:{ctx:Ctx;job:Job;reload:()=>Promise<void>;onResult?:()=>void}){
 const dub=job.processing_mode==='real_subtitles'&&job.target_lang==='km'&&(job.has_khmer_voice||!!ctx.models?.khmer_dubbing_enabled);
 const steps=stepsFor(job,dub);const applicable=steps.filter(s=>s.state!=='skip');
 const curIdx=applicable.findIndex(s=>s.state==='run'||s.state==='fail');
 const cur=curIdx>=0?applicable[curIdx]:null;
 const log=stageLog.get(job.id)||[];
 const stopped=isFailed(job.status)||job.status==='cancelled';
 const heading=job.status==='completed'?'All steps finished':stopped?(job.status==='cancelled'?'Cancelled':'Stopped at '+(cur?.title||'a step')):cur?'Step '+(curIdx+1)+' of '+applicable.length+' — '+(job.stage?job.stage.charAt(0).toUpperCase()+job.stage.slice(1):cur.title):'Waiting for a worker';
 const lines=(job.translation||'').trim();
 return <>
  <Head crumb={<><a href="#/jobs">Jobs</a> / {shortId(job.id)}</>} title={<>{baseName(job.filename)} <span className="head-badge"><Badge status={job.status}/></span></>} sub={jobMeta(job,'Started '+asDate(job.created_at))}>
   {onResult&&<button className="btn btn-outline" onClick={onResult}>View result</button>}
   {isActive(job.status)?<button className="btn btn-outline btn-danger-text" title={job.status==='cancelling'?'Stop it now':undefined} onClick={()=>void jobAction(ctx,job,'cancel',reload,job.status==='cancelling')}>{job.status==='cancelling'?'Cancelling… · Stop now':'Cancel job'}</button>:stopped&&<><button className="btn btn-outline btn-danger-text" onClick={()=>void trashJob(ctx,job,()=>ctx.go('/jobs'))}><Icon name="trash"/>Delete</button><button className="btn btn-primary" onClick={()=>void jobAction(ctx,job,'retry',reload)}><Icon name="refresh"/>Retry</button></>}
  </Head>
  <Card>
   <div className="pg-head"><h2>{heading}</h2><span><b>{job.progress}%</b>{timeLeft(job)&&' · '+timeLeft(job)}</span></div>
   <Bar value={job.progress} kind={stopped?'bad':job.status==='completed'?'ok':''}/>
   <ol className="steps">{steps.map(s=><li key={s.title} className={'st-'+s.state}>
    <span className="st-state">{s.state==='done'?<><Icon name="check" size={14}/>Done</>:s.state==='run'?<><span className="spin"/>Running</>:s.state==='fail'?<><Icon name="x" size={14}/>Stopped</>:s.state==='next'?'Up next':s.state==='skip'?'Not used':'Waiting'}</span>
    <b>{s.title}</b>
    <small>{s.state==='run'?(job.stage||''):s.state==='skip'?(job.target_lang==='km'?'Dubbing is off':'Subtitle-only'):''}</small>
   </li>)}</ol>
   {job.error&&<div className="alert alert-err"><b>What went wrong:</b> {job.error}</div>}
  </Card>
  <div className="grid2">
   <Card title="Translation preview" extra={<span className="hint">Lines appear as they're ready</span>}>
    {lines?<div className="tp"><p className="tp-en">{job.transcript}</p><p className="tp-km km">{job.translation}</p></div>
     :<div className="tp-wait"><span className="sk w80"/><span className="sk w60"/><span className="sk w70"/><p className="hint">{job.source_kind==='url'?'Captions appear after each recorded chunk.':'The transcript appears once speech recognition and translation finish.'}</p></div>}
   </Card>
   <Card title="Activity">
    <ul className="activity">{[...log].reverse().map((l,i)=><li key={i}><time>{asTime(l.t)}</time><span>{l.msg.charAt(0).toUpperCase()+l.msg.slice(1)}</span></li>)}<li><time>{job.created_at?asTime(new Date(job.created_at)):''}</time><span>Job created</span></li></ul>
    <details className="tech"><summary>Technical details</summary><dl><dt>Job ID</dt><dd className="mono">{job.id}</dd><dt>Mode</dt><dd>{job.processing_mode==='real_subtitles'?'Real AI':'Demo'}</dd><dt>Source size</dt><dd>{size(job.size_bytes)}</dd><dt>Last update</dt><dd>{asDate(job.updated_at)}</dd></dl></details>
   </Card>
  </div>
 </>;
}
type Line={start:string;text:string};
function parseSrt(s:string):Line[]{
 return s.replace(/\r/g,'').split(/\n\n+/).map(b=>{const ls=b.trim().split('\n');const ti=ls.findIndex(l=>l.includes('-->'));if(ti<0)return null;
  const st=ls[ti].split('-->')[0].trim().replace(/,\d+$/,'').replace(/^00:/,'');return {start:st,text:ls.slice(ti+1).join(' ')}}).filter((x):x is Line=>!!x&&!!x.text);
}
function Review({ctx,job,onPipeline}:{ctx:Ctx;job:Job;onPipeline:()=>void}){
 const {p,err}=usePlayback(job);
 const [lines,setLines]=useState<Line[]|null>(null),[q,setQ]=useState(''),[dur,setDur]=useState<number|null>(null);
 const video=useRef<HTMLVideoElement>(null);
 useEffect(()=>{setLines(null);if(!job.has_subtitles)return;(async()=>{try{const h:Record<string,string>={};const k=getApiKey();if(k)h['X-API-Key']=k;const r=await fetch('/api/jobs/'+job.id+'/subtitles',{headers:h});setLines(r.ok?parseSrt(await r.text()):[])}catch{setLines([])}})()},[job.id]);
 const fail=(e:unknown)=>ctx.notify(errText(e),'err');
 const txt=`${lang(job.source_lang)}\n\n${job.transcript||''}\n\n${lang(job.target_lang)}\n\n${job.translation||''}\n`;
 const seek=(t:string)=>{const s=t.split(':').map(Number).reduce((a,b)=>a*60+b,0);if(video.current){video.current.currentTime=s;void video.current.play().catch(()=>{})}};
 const shown=(lines||[]).filter(l=>!q||l.text.toLowerCase().includes(q.toLowerCase()));
 const share=async()=>{try{await navigator.clipboard.writeText(location.origin+'/#/job/'+job.id);ctx.notify('Link copied — people need access to this workspace to open it')}catch{ctx.notify('Could not copy the link','err')}};
 return <>
  <Head crumb={<><a href="#/jobs">Jobs</a> / {shortId(job.id)}</>} title={<>{baseName(job.filename)} <span className="head-badge"><span className="badge badge-ok"><Icon name="check" size={13}/>Completed</span></span></>} sub={jobMeta(job,(dur?fmtDur(dur)+' · ':'')+'Finished '+asDate(job.updated_at))}>
   <button className="btn btn-outline btn-danger-text" onClick={()=>void trashJob(ctx,job,()=>ctx.go('/jobs'))}><Icon name="trash"/>Delete</button>
   <button className="btn btn-outline" onClick={onPipeline}>Pipeline</button>
   <button className="btn btn-outline" onClick={()=>void share()}><Icon name="share"/>Share</button>
   <button className="btn btn-primary" onClick={()=>void downloadVideo(job).catch(fail)}><Icon name="download"/>Download video</button>
  </Head>
  <div className="review">
   <div className="review-l">
    <div className="player">{p?<video ref={video} controls playsInline preload="metadata" src={p.video_url} onLoadedMetadata={e=>setDur(e.currentTarget.duration)} aria-label="Translated video">{p.captions_url&&<track kind="subtitles" default srcLang={job.target_lang} label={lang(job.target_lang)} src={p.captions_url}/>}</video>:<div className="player-empty"><Icon name="play" size={34}/><small>{err||'Loading secure preview…'}</small></div>}</div>
    {job.processing_mode==='demo'&&<p className="hint">Demo output — the original audio is unchanged and no translation was performed.</p>}
    <Card title="Downloads">
     <div className="dl">
      <button className="dl-i" onClick={()=>void downloadVideo(job).catch(fail)}><Icon name="download" size={20}/><span><b>{job.has_khmer_voice?'Dubbed video':'Video'}</b><small>MP4{dur?' · '+fmtDur(dur):''}</small></span></button>
      <button className="dl-i" disabled={!job.has_subtitles} onClick={()=>void downloadBlob('/api/jobs/'+job.id+'/subtitles',baseName(job.filename)+'-'+job.target_lang+'.srt').catch(fail)}><Icon name="download" size={20}/><span><b>{lang(job.target_lang)} subtitles</b><small>{job.has_subtitles?'SRT':'Not created in demo mode'}</small></span></button>
      <button className="dl-i" disabled={!job.transcript&&!job.translation} onClick={()=>saveBlob(new Blob([txt],{type:'text/plain;charset=utf-8'}),baseName(job.filename)+'-transcript.txt')}><Icon name="download" size={20}/><span><b>Transcript</b><small>TXT · {lang(job.source_lang)} &amp; {lang(job.target_lang)}</small></span></button>
     </div>
    </Card>
   </div>
   <section className="card lines-card">
    <div className="card-h pad-x pt"><h2>Translation{lines?' · '+lines.length+' lines':''}</h2></div>
    {job.has_subtitles?<>
     <div className="pad-x"><label className="input-icon"><Icon name="search"/><input placeholder={'Search '+lang(job.target_lang)} value={q} onChange={e=>setQ(e.target.value)} aria-label="Search subtitles"/></label></div>
     <ol className="lines">{lines===null?<li><span className="sk w80"/></li>:shown.map((l,i)=><li key={i}><button className="ts" onClick={()=>seek(l.start)} title="Play from here">{l.start}</button><p className={job.target_lang==='km'?'km':''}>{l.text}</p></li>)}{lines&&!shown.length&&<li className="muted">No matching lines.</li>}</ol>
     <p className="lines-foot">Click a time to jump there. Line editing isn't available yet — download the SRT to edit.</p>
    </>:<div className="pad"><div className="tp"><p className="tp-en">{job.transcript||'No transcript'}</p><p className="tp-km km">{job.translation||''}</p></div></div>}
   </section>
  </div>
 </>;
}

/* ================= Jobs (with library grid) ================= */
export function Jobs({ctx,query}:{ctx:Ctx;query:URLSearchParams}){
 const initial=query.get('status')||'';
 const [status,setStatus]=useState<'all'|'active'|'completed'|'failed'>((['active','completed','failed'].includes(initial)?initial:'all') as 'all');
 const [view,setView]=useState<'list'|'grid'>(query.get('view')==='grid'?'grid':'list');
 const [q,setQ]=useState(''),[search,setSearch]=useState(''),[source,setSource]=useState('all'),[offset,setOffset]=useState(0),[sort,setSort]=useState('newest');
 const mediaId=query.get('media')||'';
 const limit=view==='grid'?12:10;
 const [data,setData]=useState<{items:Job[];total:number}|null>(null);
 const load=async()=>{try{const p=new URLSearchParams({limit:String(limit),offset:String(offset),status:view==='grid'&&status==='all'?'completed':status,source,sort});if(search)p.set('search',search);if(mediaId)p.set('media_id',mediaId);setData(await req('/api/jobs?'+p))}catch(e){ctx.notify(errText(e),'err')}};
 useEffect(()=>{void load()},[status,search,source,offset,view,sort]);
 useEffect(()=>{const t=setInterval(()=>void load(),6000);return()=>clearInterval(t)},[status,search,source,offset,view,sort]);
 useEffect(()=>{const t=setTimeout(()=>{setSearch(q.trim());setOffset(0)},300);return()=>clearTimeout(t)},[q]);
 const m=ctx.metrics;
 return <>
  <Head title="Jobs" sub="Every translation, in progress or finished. Switch to grid to browse finished videos."><NewBtn go={ctx.go}/></Head>
  <div className="toolbar">
   <Seg label="Status" value={status} onChange={v=>{setStatus(v);setOffset(0)}} items={[['all',<>All <em>{m.total}</em></>],['active',<>In progress <em>{m.processing+m.queued}</em></>],['completed',<>Completed <em>{m.completed}</em></>],['failed',<>Failed <em>{m.failed}</em></>]]}/>
   <div className="toolbar-r">
    <label className="input-icon"><Icon name="search"/><input placeholder="Search title, ID or link" value={q} onChange={e=>setQ(e.target.value)} aria-label="Search jobs"/></label>
    <select className="select" value={sort} onChange={e=>{setSort(e.target.value);setOffset(0)}} aria-label="Sort jobs">{JOB_SORTS.map(([v,l])=><option key={v} value={v}>{l}</option>)}</select>
    <select className="select" value={source} onChange={e=>{setSource(e.target.value);setOffset(0)}} aria-label="Source"><option value="all">All sources</option><option value="youtube">YouTube</option><option value="upload">Upload</option><option value="url">Video link</option></select>
    <Seg label="View" value={view} onChange={v=>{setView(v);setOffset(0)}} items={[['list',<Icon name="list" key="l"/>],['grid',<Icon name="grid" key="g"/>]]}/>
   </div>
  </div>
  {mediaId&&<div className="alert alert-info filter-chip">Showing jobs for one video · <a href="#/jobs">Show all jobs</a></div>}
  {view==='list'?<section className="card">
   <div className="table-wrap"><table className="table"><thead><tr><th>Video</th><th>Source</th><th>Status</th><th>Created</th><th><span className="sr">Action</span></th></tr></thead><tbody>
    {data?.items.map(j=><tr key={j.id} onClick={()=>ctx.go('/job/'+j.id)}>
     <td><div className="vcell"><Thumb label={j.source_lang.toUpperCase()+'→'+j.target_lang.toUpperCase()}/><div><b title={j.filename}>{baseName(j.filename)}</b><small>{shortId(j.id)} · {outputsLabel(j)}</small></div></div></td>
     <td>{sourceLabel(j.source_kind,j.capture_seconds)}</td>
     <td><div className="scell"><Badge status={j.status}/>{isActive(j.status)&&j.status!=='queued'&&<><Bar value={j.progress}/><small>{j.stage||''} · {j.progress}%</small></>}{j.status==='queued'&&<small>Waiting for a worker</small>}{isFailed(j.status)&&<small className="clip" title={j.error||''}>{j.error||'Failed'}</small>}</div></td>
     <td className="nowrap">{asDate(j.created_at)}</td>
     <td className="act" onClick={e=>e.stopPropagation()}><div className="act-row">{isFailed(j.status)||j.status==='cancelled'?<button className="btn btn-outline btn-sm" onClick={()=>void jobAction(ctx,j,'retry',load)}>Retry</button>:<button className="btn btn-outline btn-sm" onClick={()=>ctx.go('/job/'+j.id)}>{j.status==='completed'?'Open':'View'}</button>}<button className="btn btn-ghost btn-sm btn-icon btn-danger-text" disabled={isActive(j.status)} title={isActive(j.status)?'Cancel the job before deleting it':'Move to Trash'} aria-label={'Delete '+baseName(j.filename)} onClick={()=>void trashJob(ctx,j,load)}><Icon name="trash" size={16}/></button></div></td>
    </tr>)}
    {data&&!data.items.length&&<tr><td colSpan={5}><div className="empty"><b>No jobs match</b><span>Try another filter, or start a new translation.</span></div></td></tr>}
    {!data&&<tr><td colSpan={5}><span className="sk w80"/></td></tr>}
   </tbody></table></div>
   <Pager data={data} offset={offset} limit={limit} setOffset={setOffset}/>
  </section>:<>
   <div className="vgrid">{data?.items.map(j=>j.has_output?<VideoCard key={j.id} job={j} go={ctx.go}/>:<button key={j.id} className="vcard" onClick={()=>ctx.go('/job/'+j.id)}><span className="vthumb"><span className="vplay"><Icon name="play" size={14}/></span></span><span className="vmeta"><b>{baseName(j.filename)}</b><small><Badge status={j.status}/></small></span></button>)}</div>
   {data&&!data.items.length&&<div className="card pad empty"><b>No finished videos yet</b></div>}
   <Pager data={data} offset={offset} limit={limit} setOffset={setOffset} bare/>
  </>}
 </>;
}
function Pager({data,offset,limit,setOffset,bare}:{data:{total:number;items:Job[]}|null;offset:number;limit:number;setOffset:(n:number)=>void;bare?:boolean}){
 if(!data)return null;
 return <div className={'pager'+(bare?' bare':'')}><span>Showing {data.total?offset+1:0}–{offset+data.items.length} of {data.total}</span><div><button className="btn btn-outline btn-sm" disabled={offset===0} onClick={()=>setOffset(Math.max(0,offset-limit))}>Previous</button><button className="btn btn-outline btn-sm" disabled={offset+limit>=data.total} onClick={()=>setOffset(offset+limit)}>Next</button></div></div>;
}

/* ================= System health & models ================= */
const SVC:[string,string,string][]=[['api','API','FastAPI'],['database','Database','PostgreSQL'],['redis','Cache','Redis'],['storage','File storage','MinIO'],['worker','Job workers','Celery']];
export function System({ctx}:{ctx:Ctx}){
 const s=ctx.system?.services||{},lat=ctx.system?.latency_ms||{},h=ctx.system?.host,m=ctx.models;
 const down=SVC.filter(([k])=>s[k]==='offline'),unknown=SVC.filter(([k])=>!s[k]||s[k]==='unknown');
 const pct=(u?:number|null,t?:number|null)=>u!=null&&t?u*100/t:null;
 const res:[string,number|null,string][]=[
  ['CPU (load)',h?.cpu_percent??null,h?.cpu_percent!=null?h.cpu_percent+'%':'—'],
  ['Memory',pct(h?.memory_used_bytes,h?.memory_total_bytes),h?.memory_used_bytes!=null?size(h.memory_used_bytes)+' of '+size(h.memory_total_bytes):'—'],
  ['Disk',pct(h?.disk_used_bytes,h?.disk_total_bytes),h?.disk_used_bytes!=null?size(h.disk_used_bytes)+' of '+size(h.disk_total_bytes):'—'],
 ];
 const isReal=real(m);
 const modelRow=(step:string,comp:string,ok:boolean|undefined,off?:boolean)=>{const inst=m?.installed?.[comp];const st=!isReal?['Demo','muted']:off?['Off','muted']:ok?['Ready','ok']:['Missing','bad'];
  return <tr key={comp}><td><b>{step}</b></td><td>{inst?<><span>{inst.id.split('/').pop()}</span><small className="mono">{inst.id}</small></>:<span className="muted">Not installed</span>}</td><td>{inst?.license?<span className={inst.license.includes('nc')?'lic nc':'lic'}>{inst.license.toUpperCase()}</span>:'—'}</td><td><span className={'badge badge-'+st[1]}>{st[0]}</span></td></tr>};
 const llm=m?.llm;
 const llmRow=()=>{
  if(!llm)return <tr key="llm"><td><b>Polish translation</b><small>LLM post-edit</small></td><td><span className="muted">Not reported</span></td><td>—</td><td><span className="badge badge-muted">Unknown</span></td></tr>;
  const st:[string,string]=!isReal?['Demo','muted']:llm.status==='ready'?['Ready','ok']:llm.status==='model_missing'?['Model not pulled','bad']:llm.status==='offline'?['Server offline','bad']:llm.status==='misconfigured'?['Misconfigured','bad']:['Off','muted'];
  const srv=llm.server==='online'?'server online':llm.server==='offline'?'server not running':'server unknown';
  const proc:[string,string,string]|null=llm.processor==='gpu'?['GPU','ok',llm.gpu_percent!=null?llm.gpu_percent+'% on GPU':'Runs on GPU']:llm.processor==='split'?[`${llm.gpu_percent}% GPU`,'warn',`Only ${llm.gpu_percent}% of the model fits in VRAM; the rest runs on CPU`]:llm.processor==='cpu'?['CPU','warn','Running on CPU only (slow)']:llm.processor==='idle'?['Not loaded','muted','Loads into memory on the next job']:null;
  return <tr key="llm"><td><b>Polish translation</b><small>LLM post-edit (optional)</small></td><td><span>{llm.model}</span><small className="mono">{llm.provider} · {srv}{llm.server==='online'?(llm.model_available?' · model pulled':' · model not pulled'):''}</small></td><td>—</td><td><div className="llm-proc"><span className={'badge badge-'+st[1]}>{st[0]}</span>{proc&&<span className={'badge badge-'+proc[1]} title={proc[2]}>{proc[0]}</span>}</div></td></tr>;
 };
 return <>
  <Head title="System health" sub="Services, server resources and the AI models behind each step. Refreshes every few seconds."><button className="btn btn-outline" onClick={()=>void ctx.refresh()}><Icon name="refresh"/>Refresh now</button></Head>
  <div className={'banner '+(down.length?'bad':unknown.length?'warn':'ok')}><Icon name={down.length?'alert':'check'} size={22}/><div><b>{down.length?down.map(d=>d[1]).join(', ')+(down.length>1?' are':' is')+' offline':unknown.length?'Most services are running · '+unknown.map(u=>u[1]).join(', ')+' not responding to pings':'All 5 services are running normally'}</b><span>{isReal?'Real AI mode':'Demo mode'} · {m?.installed&&Object.keys(m.installed).length?Object.keys(m.installed).length+' models installed':'no models installed'}</span></div></div>
  <div className="grid2">
   <Card title="Services">
    <ul className="svc">{SVC.map(([k,n,sub])=>{const v=s[k]||'unknown';return <li key={k}><i className={'sdot '+v}/><div><b>{n}</b><small>{sub}</small></div><em>{lat[k]!=null&&v==='online'?lat[k]+' ms':'—'}</em><span className={'badge badge-'+(v==='online'?'ok':v==='offline'?'bad':'muted')}>{v==='online'?'Healthy':v==='offline'?'Offline':'Unknown'}</span></li>})}</ul>
   </Card>
   <Card title="Resources">
    {res.map(([n,v,label])=><div className="res" key={n}><div><span>{n}</span><b>{label}</b></div><Bar value={v??0} kind={v!=null&&v>85?'warn':''}/></div>)}
    <p className="hint">Measured inside the API container.</p>
   </Card>
  </div>
  <section className="card">
   <div className="card-h pad-x pt"><div><h2>AI models</h2><p className="hint top">One model per pipeline step, loaded offline from <code>models/</code>.</p></div></div>
   <div className="table-wrap"><table className="table"><thead><tr><th>Step</th><th>Model</th><th>Licence</th><th>Status</th></tr></thead><tbody>
    {modelRow('Transcribe','asr',m?.subtitle_translation_configured)}
    {modelRow('Translate','mt',m?.subtitle_translation_configured)}
    {modelRow('Khmer voice','tts',m?.speech_dubbing_available,!m?.khmer_dubbing_enabled)}
    {llmRow()}
   </tbody></table></div>
   {llm&&isReal&&llm.status!=='ready'&&<p className="hint pad-x">{llmHint(llm)}</p>}
   {llm&&isReal&&llm.status==='ready'&&(llm.processor==='cpu'||llm.processor==='split')&&<p className="hint pad-x">{llmProcHint(llm)}</p>}
   <p className="hint pad-x pb">To add or update models run <code>python3 scripts/download-models.py</code> on the server, then restart the worker.</p>
  </section>
 </>;
}

function llmHint(l:LLMInfo){
 const pull=l.provider==='ollama'?<>Pull it with <code>docker compose exec ollama ollama pull {l.model}</code>. </>:null;
 if(l.status==='model_missing')return <>The {l.provider} server is running but <b>{l.model}</b> isn't downloaded, so jobs skip polishing. {pull}</>;
 if(l.status==='offline')return <>Post-editing is on but the {l.provider} server isn't reachable. Start it with the <code>compose.{l.provider}.yaml</code> override. Jobs still finish without polishing.</>;
 if(l.status==='misconfigured')return <>Post-editing is misconfigured: {l.detail}</>;
 return <>Optional AI polishing of Khmer translations is off. {l.server==='online'&&!l.model_available?pull:null}To turn it on set <code>{l.provider==='vllm'?'VLLM_POSTEDIT_ENABLED':'LLM_POSTEDIT_ENABLED'}=true</code> in <code>.env</code> and restart api and worker.</>;
}

function llmProcHint(l:LLMInfo){
 if(l.processor==='cpu')return <>Post-editing is running on the <b>CPU</b>, so each subtitle line takes several seconds. To use an NVIDIA GPU, install the NVIDIA Container Toolkit and add <code>-f compose.ollama-gpu.yaml</code> when starting the stack.</>;
 return <>Only <b>{l.gpu_percent}%</b> of <b>{l.model}</b> fits in GPU memory; the rest runs on the CPU, which slows post-editing. Lower <code>OLLAMA_CONTEXT_LENGTH</code> or use a smaller model.</>;
}

/* ================= Videos ================= */
const MEDIA_SORTS:[string,string][]=[['newest','Newest first'],['oldest','Oldest first'],['name_asc','Name A–Z'],['name_desc','Name Z–A'],['size_desc','Largest first'],['size_asc','Smallest first']];
const kindLabel=(k:string)=>k==='youtube'?'YouTube':k==='url'?'Video link':'Upload';
export function Videos({ctx}:{ctx:Ctx}){
 const [q,setQ]=useState(''),[search,setSearch]=useState(''),[source,setSource]=useState('all'),[sort,setSort]=useState('newest'),[offset,setOffset]=useState(0);
 const limit=15;
 const [data,setData]=useState<{items:MediaItem[];total:number}|null>(null);
 const load=async()=>{try{const p=new URLSearchParams({limit:String(limit),offset:String(offset),source,sort});if(search)p.set('search',search);setData(await req('/api/media?'+p))}catch(e){ctx.notify(errText(e),'err')}};
 useEffect(()=>{void load()},[search,source,sort,offset]);
 useEffect(()=>{const t=setTimeout(()=>{setSearch(q.trim());setOffset(0)},300);return()=>clearTimeout(t)},[q]);
 const remove=async(m:MediaItem)=>{
  if(m.active){ctx.notify('This video has jobs in progress. Cancel them first.','err');return}
  if(!await confirmDialog({tone:'danger',title:'Move video to Trash?',
   message:<>“<b>{baseName(m.filename)}</b>” will disappear from Videos{m.jobs?<> together with its <b>{m.jobs} translation job{m.jobs===1?'':'s'}</b></>:null}.</>,
   details:[ctx.isAdmin?'You can restore everything from the Trash.':'An administrator can restore it if needed.'],
   confirmLabel:'Move to Trash',cancelLabel:'Keep video'}))return;
  try{const r=await req<{jobs_trashed:number}>('/api/media/'+m.id,{method:'DELETE'});ctx.notify('Video moved to the Trash'+(r.jobs_trashed?' with '+r.jobs_trashed+' job'+(r.jobs_trashed===1?'':'s'):''));void load();void ctx.refresh()}catch(e){ctx.notify(errText(e),'err')}};
 const pg=data?{total:data.total,items:data.items as unknown as Job[]}:null;
 return <>
  <Head title="Videos" sub="Source videos you uploaded or linked. Deleting a video also removes its translation jobs."><NewBtn go={ctx.go}/></Head>
  <div className="toolbar">
   <span className="muted">{data?data.total+' video'+(data.total===1?'':'s'):''}</span>
   <div className="toolbar-r">
    <label className="input-icon"><Icon name="search"/><input placeholder="Search name, ID or link" value={q} onChange={e=>setQ(e.target.value)} aria-label="Search videos"/></label>
    <select className="select" value={source} onChange={e=>{setSource(e.target.value);setOffset(0)}} aria-label="Source"><option value="all">All sources</option><option value="youtube">YouTube</option><option value="upload">Upload</option><option value="url">Video link</option></select>
    <select className="select" value={sort} onChange={e=>{setSort(e.target.value);setOffset(0)}} aria-label="Sort videos">{MEDIA_SORTS.map(([v,l])=><option key={v} value={v}>{l}</option>)}</select>
   </div>
  </div>
  <section className="card"><div className="table-wrap"><table className="table"><thead><tr><th>Video</th><th>Source</th><th>Size</th><th>Jobs</th><th>Added</th><th><span className="sr">Actions</span></th></tr></thead><tbody>
   {data?.items.map(m=><tr key={m.id} onClick={()=>ctx.go('/jobs?media='+m.id)}>
    <td><div className="vcell"><Thumb/><div><b title={m.filename}>{baseName(m.filename)}</b><small className="clip" title={m.source_url||m.id}>{m.source_url||shortId(m.id)}</small></div></div></td>
    <td>{kindLabel(m.source_kind)}</td>
    <td className="nowrap">{m.size_bytes?size(m.size_bytes):'—'}</td>
    <td className="nowrap">{m.jobs}{m.active?<small>{m.active} in progress</small>:m.completed?<small>{m.completed} completed</small>:null}</td>
    <td className="nowrap">{asDate(m.created_at)}</td>
    <td className="act" onClick={e=>e.stopPropagation()}><div className="act-row"><button className="btn btn-outline btn-sm" onClick={()=>ctx.go('/jobs?media='+m.id)}>Jobs</button><button className="btn btn-ghost btn-sm btn-icon btn-danger-text" disabled={m.active>0} title={m.active?'Cancel its jobs before deleting':'Move to Trash'} aria-label={'Delete '+baseName(m.filename)} onClick={()=>void remove(m)}><Icon name="trash" size={16}/></button></div></td>
   </tr>)}
   {data&&!data.items.length&&<tr><td colSpan={6}><div className="empty"><b>No videos match</b><span>Try another search, or start a new translation.</span></div></td></tr>}
   {!data&&<tr><td colSpan={6}><span className="sk w80"/></td></tr>}
  </tbody></table></div>
  <Pager data={pg} offset={offset} limit={limit} setOffset={setOffset}/></section>
 </>;
}

/* ================= Trash (admin) ================= */
const TRASH_SORTS:[string,string][]=[['deleted_newest','Recently deleted'],['deleted_oldest','Oldest deleted'],['name_asc','Name A–Z'],['name_desc','Name Z–A']];
export function Trash({ctx}:{ctx:Ctx}){
 const [kind,setKind]=useState<'all'|'job'|'video'>('all'),[q,setQ]=useState(''),[search,setSearch]=useState(''),[sort,setSort]=useState('deleted_newest');
 const [data,setData]=useState<{items:TrashItem[];total:number}|null>(null),[busy,setBusy]=useState(false);
 const load=async()=>{if(!ctx.isAdmin)return;try{const p=new URLSearchParams({kind,sort,limit:'200'});if(search)p.set('search',search);setData(await req('/api/trash?'+p))}catch(e){ctx.notify(errText(e),'err')}};
 useEffect(()=>{void load()},[kind,search,sort,ctx.isAdmin]);
 useEffect(()=>{const t=setTimeout(()=>setSearch(q.trim()),300);return()=>clearTimeout(t)},[q]);
 if(!ctx.isAdmin)return <><Head title="Trash"/><div className="alert alert-err">Only administrators can open the Trash.</div></>;
 const label=(i:TrashItem)=>i.kind==='video'?'video':'job';
 const restore=async(i:TrashItem)=>{try{const r=await req<{jobs_restored:number}>(`/api/trash/${i.kind}/${i.id}/restore`,{method:'POST'});ctx.notify('Restored '+label(i)+(r.jobs_restored?' and '+r.jobs_restored+' job'+(r.jobs_restored===1?'':'s'):''));void load();void ctx.refresh()}catch(e){ctx.notify(errText(e),'err')}};
 const purge=async(i:TrashItem)=>{
  if(!await confirmDialog({tone:'danger',title:'Delete forever?',
   message:<>“<b>{baseName(i.filename)}</b>” and its files will be erased from storage.</>,
   details:[...(i.kind==='video'&&i.jobs?[`Its ${i.jobs} job${i.jobs===1?'':'s'} will be deleted too.`]:[]),'This cannot be undone.'],
   confirmLabel:'Delete forever',cancelLabel:'Keep in Trash'}))return;
  try{const r=await req<{storage_cleaned:boolean}>(`/api/trash/${i.kind}/${i.id}`,{method:'DELETE'});ctx.notify(r.storage_cleaned?'Permanently deleted':'Deleted, but some files could not be removed from storage',r.storage_cleaned?undefined:'err');void load()}catch(e){ctx.notify(errText(e),'err')}};
 const empty=async()=>{
  if(!data?.total)return;
  if(!await confirmDialog({tone:'danger',title:'Empty the Trash?',
   message:<>All <b>{data.total} item{data.total===1?'':'s'}</b> in the Trash and their files will be permanently deleted.</>,
   details:['This cannot be undone.'],confirmLabel:'Empty Trash',cancelLabel:'Keep items'}))return;
  setBusy(true);try{const r=await req<{jobs_deleted:number;videos_deleted:number;storage_cleaned:boolean}>('/api/trash',{method:'DELETE'});ctx.notify('Trash emptied · '+r.videos_deleted+' video'+(r.videos_deleted===1?'':'s')+', '+r.jobs_deleted+' job'+(r.jobs_deleted===1?'':'s')+' deleted'+(r.storage_cleaned?'':' (some files could not be removed)'),r.storage_cleaned?undefined:'err');void load()}catch(e){ctx.notify(errText(e),'err')}finally{setBusy(false)}};
 return <>
  <Head title="Trash" sub="Jobs and videos deleted by anyone. Restore them, or delete permanently to erase their files."><button className="btn btn-outline btn-danger-text" disabled={busy||!data?.total} onClick={()=>void empty()}><Icon name="trash"/>{busy?'Emptying…':'Empty Trash'}</button></Head>
  <div className="toolbar">
   <Seg label="Type" value={kind} onChange={setKind} items={[['all','All'],['video','Videos'],['job','Jobs']]}/>
   <div className="toolbar-r">
    <label className="input-icon"><Icon name="search"/><input placeholder="Search name or ID" value={q} onChange={e=>setQ(e.target.value)} aria-label="Search Trash"/></label>
    <select className="select" value={sort} onChange={e=>setSort(e.target.value)} aria-label="Sort Trash">{TRASH_SORTS.map(([v,l])=><option key={v} value={v}>{l}</option>)}</select>
   </div>
  </div>
  <section className="card"><div className="table-wrap"><table className="table"><thead><tr><th>Item</th><th>Type</th><th>Owner</th><th>Deleted</th><th><span className="sr">Actions</span></th></tr></thead><tbody>
   {data?.items.map(i=><tr key={i.kind+i.id} className="no-click">
    <td><div className="vcell"><Thumb/><div><b title={i.filename}>{baseName(i.filename)}</b><small>{shortId(i.id)}{i.kind==='video'?' · '+kindLabel(i.source_kind)+(i.jobs?' · '+i.jobs+' job'+(i.jobs===1?'':'s'):''):''}</small></div></div></td>
    <td>{i.kind==='video'?'Video':<>Job {i.status&&<Badge status={i.status}/>}</>}</td>
    <td>{i.owner_name||(i.owner_user_id?shortId(i.owner_user_id):'Administrator')}</td>
    <td className="nowrap">{asDate(i.deleted_at)}<small>by {i.deleted_by_name||'unknown'}</small></td>
    <td className="act"><div className="act-row"><button className="btn btn-outline btn-sm" onClick={()=>void restore(i)}><Icon name="restore" size={15}/>Restore</button><button className="btn btn-ghost btn-sm btn-danger-text" onClick={()=>void purge(i)}>Delete forever</button></div></td>
   </tr>)}
   {data&&!data.items.length&&<tr><td colSpan={5}><div className="empty"><b>Trash is empty</b><span>Deleted jobs and videos appear here until you delete them permanently.</span></div></td></tr>}
   {!data&&<tr><td colSpan={5}><span className="sk w80"/></td></tr>}
  </tbody></table></div></section>
 </>;
}

/* ================= Datasets ================= */
export function Datasets({ctx}:{ctx:Ctx}){
 const rows=ctx.jobs.filter(j=>j.status==='completed'&&j.transcript&&j.translation&&j.processing_mode==='real_subtitles');
 const exportJsonl=()=>saveBlob(new Blob([rows.map(j=>JSON.stringify({job_id:j.id,source_lang:j.source_lang,target_lang:j.target_lang,source:j.transcript,target:j.translation})).join('\n')+'\n'],{type:'application/jsonl'}),'khmerlive-parallel-text.jsonl');
 return <>
  <Head title="Datasets" sub="Parallel English ⇔ Khmer text produced by finished real-mode jobs."><button className="btn btn-primary" disabled={!rows.length} onClick={exportJsonl}><Icon name="download"/>Export JSONL</button></Head>
  <section className="card"><div className="table-wrap"><table className="table"><thead><tr><th>Video</th><th>Pair</th><th>Source text</th><th>Translation</th></tr></thead><tbody>
   {rows.map(j=><tr key={j.id} onClick={()=>ctx.go('/job/'+j.id)}><td><b>{baseName(j.filename)}</b><small className="mono">{shortId(j.id)}</small></td><td>{j.source_lang.toUpperCase()}→{j.target_lang.toUpperCase()}</td><td className="clip">{j.transcript}</td><td className="clip km">{j.translation}</td></tr>)}
   {!rows.length&&<tr><td colSpan={4}><div className="empty"><b>No parallel text yet</b><span>Demo-mode jobs only produce placeholder text, so they're excluded.</span></div></td></tr>}
  </tbody></table></div></section>
 </>;
}

/* ================= Users ================= */
export function Users({ctx}:{ctx:Ctx}){
 const [dir,setDir]=useState<{items:DirectoryUser[];total:number}|null>(null),[err,setErr]=useState('');
 useEffect(()=>{if(!ctx.isAdmin)return;req<{items:DirectoryUser[];total:number}>('/api/users?limit=100').then(setDir).catch(e=>setErr(errText(e)))},[ctx.isAdmin]);
 const a=ctx.account;
 return <>
  <Head title="Users" sub="Who can sign in, and how."/>
  {err&&<div className="alert alert-err">{err}</div>}
  <section className="card"><div className="table-wrap"><table className="table"><thead><tr><th>User</th><th>Role</th><th>Sign-in</th><th>Joined</th></tr></thead><tbody>
   {ctx.isAdmin&&<tr><td><div className="ucell"><Avatar name="Administrator" size={32}/><div><b>Administrator</b><small>API key from .env</small></div></div></td><td>Admin</td><td>API key</td><td>—</td></tr>}
   {ctx.isAdmin?dir?.items.map(u=><tr key={u.id}><td><div className="ucell"><Avatar name={u.display_name} size={32}/><div><b>{u.display_name}</b><small>{u.email||'No email'}</small></div></div></td><td>Member</td><td>{u.providers.join(', ')||'—'}</td><td>{asDate(u.created_at)}</td></tr>)
    :a?.user&&<tr><td><div className="ucell"><Avatar name={a.user.name} src={a.user.avatar_url} size={32}/><div><b>{a.user.name}</b><small>{a.user.email||'No email'}</small></div></div></td><td>Member</td><td>{a.identities.map(i=>i.provider).join(', ')}</td><td>—</td></tr>}
  </tbody></table></div></section>
  <div className="grid2">
   <Card title="Admin"><p className="hint top">Signs in with the server's <code>API_KEY</code>. Sees every job, the user list, and can submit YouTube and stream links.</p></Card>
   <Card title="Member"><p className="hint top">Signs in with Google or GitHub. Sees and manages only their own jobs.</p>
    {a?.authenticated&&<div className="link-row">{ctx.providers.map(p=>{const linked=a.identities.some(i=>i.provider===p.id);return <button key={p.id} className="btn btn-outline btn-sm" disabled={!p.enabled||linked} onClick={()=>{window.location.href='/api/auth/link/'+p.id}}>{linked?'✓ '+p.name+' linked':'Link '+p.name}</button>})}</div>}
   </Card>
  </div>
 </>;
}

/* ================= Settings ================= */
export function Settings({ctx,theme,setTheme,onSignOut}:{ctx:Ctx;theme:string;setTheme:(t:string)=>void;onSignOut:()=>void}){
 const m=ctx.models;
 const row=(t:string,d:React.ReactNode,c:React.ReactNode)=><div className="set-row"><div><b>{t}</b><small>{d}</small></div>{c}</div>;
 return <>
  <Head title="Settings" sub="Appearance, account and server configuration."/>
  <Card title="Appearance">{row('Theme','Saved in this browser',<Seg label="Theme" value={theme||'system'} onChange={v=>setTheme(v==='system'?'':v)} items={[['system','System'],['light','Light'],['dark','Dark']]}/>)}</Card>
  <Card title="Account">
   {row('Signed in as',ctx.account?.authenticated?ctx.account.user?.name+' (Google/GitHub)':'Administrator (API key)',<button className="btn btn-outline" onClick={onSignOut}><Icon name="logout"/>Sign out</button>)}
   {row('API documentation','OpenAPI / Swagger UI',<a className="btn btn-outline" href="/api/docs" target="_blank" rel="noopener">Open</a>)}
  </Card>
  <Card title="Server (read-only)">
   {row('Processing mode',<>Set with <code>MODEL_MODE</code>; restart the API and worker to change.</>,<span className={'badge badge-'+(real(m)?'ok':'muted')}>{real(m)?'Real AI':'Demo'}</span>)}
   {row('Khmer dubbing',<code>ENABLE_KHMER_DUBBING</code>,<span className={'badge badge-'+(m?.khmer_dubbing_enabled?'ok':'muted')}>{m?.khmer_dubbing_enabled?'On':'Off'}</span>)}
   {row('YouTube links',<code>YOUTUBE_ENABLED</code>,<span className={'badge badge-'+(m?.youtube_enabled?'ok':'muted')}>{m?.youtube_enabled?'On':'Off'}</span>)}
   {row('Longest video',<code>MAX_VIDEO_DURATION_SECONDS</code>,<b>{m?.max_video_duration_seconds?Math.round(m.max_video_duration_seconds/60)+' min':'—'}</b>)}
  </Card>
 </>;
}

/* ================= Search (⌘K) ================= */
export function SearchDialog({onClose,go}:{onClose:()=>void;go:(p:string)=>void}){
 const [q,setQ]=useState(''),[items,setItems]=useState<Job[]>([]),[i,setI]=useState(0);
 const pages:[string,string][]=[['Dashboard','/dashboard'],['New translation','/new'],['Jobs','/jobs'],['System health','/system'],['Settings','/settings']];
 useEffect(()=>{const t=setTimeout(()=>{req<{items:Job[]}>('/api/jobs?limit=8&offset=0&status=all'+(q.trim()?'&search='+encodeURIComponent(q.trim()):'')).then(r=>{setItems(r.items);setI(0)}).catch(()=>setItems([]))},150);return()=>clearTimeout(t)},[q]);
 const pg=pages.filter(([n])=>!q||n.toLowerCase().includes(q.toLowerCase()));
 const all:[string,string,React.ReactNode][]=[...pg.map(([n,p]):[string,string,React.ReactNode]=>[n,p,<span className="muted">Page</span>]),...items.map((j):[string,string,React.ReactNode]=>[baseName(j.filename),'/job/'+j.id,<Badge status={j.status}/>])];
 const pick=(p:string)=>{onClose();go(p)};
 return <div className="overlay" onClick={onClose}><div className="dialog" role="dialog" aria-modal="true" aria-label="Search" onClick={e=>e.stopPropagation()}>
  <label className="dlg-search"><Icon name="search"/><input autoFocus placeholder="Search jobs and pages…" value={q} onChange={e=>setQ(e.target.value)} onKeyDown={e=>{if(e.key==='Escape')onClose();if(e.key==='ArrowDown'){e.preventDefault();setI(v=>Math.min(all.length-1,v+1))}if(e.key==='ArrowUp'){e.preventDefault();setI(v=>Math.max(0,v-1))}if(e.key==='Enter'&&all[i])pick(all[i][1])}}/><kbd>Esc</kbd></label>
  <ul className="dlg-list">{all.map(([n,p,meta],k)=><li key={p}><button className={k===i?'on':''} onMouseEnter={()=>setI(k)} onClick={()=>pick(p)}><span>{n}</span>{meta}</button></li>)}{!all.length&&<li className="muted pad">No results</li>}</ul>
 </div></div>;
}
