import React,{useEffect,useMemo,useRef,useState} from 'react';
import {Job,Metrics,ModelInfo,SystemData,Account,Provider,DirectoryUser,Status,req,uploadMedia,downloadVideo,downloadBlob,saveBlob,baseName,shortId,getApiKey,asDate,asTime,size,lang,isActive,isFailed,isYouTubeUrl,sourceLabel} from './api';
import {Icon,Badge,Toggle,Progress,Avatar,Tabs,Sparkline} from './ui';

export type Ctx={
 account:Account|null;providers:Provider[];isAdmin:boolean;
 metrics:Metrics;jobs:Job[];models:ModelInfo|null;system:SystemData|null;
 hostHistory:{cpu:number[];mem:number[];disk:number[]};
 refresh:()=>Promise<void>;go:(path:string)=>void;
 notify:(msg:string,kind?:'ok'|'err')=>void;
};
const isReal=(m:ModelInfo|null)=>m?.mode==='real_subtitles';
const dubbingFor=(m:ModelInfo|null,source:string)=>isReal(m)&&source==='en'&&!!m?.khmer_dubbing_enabled;

/* ---------- Page header ---------- */
export function PageHead({title,sub,children}:{title:string;sub:string;children?:React.ReactNode}){
 return <div className="page-head"><div><h1>{title}</h1><p>{sub}</p></div>{children&&<div className="page-head-extra">{children}</div>}</div>;
}

/* ---------- 1. Login ---------- */
export function Login({providers,onKey,error}:{providers:Provider[];onKey:(k:string,remember:boolean)=>Promise<void>;error:string}){
 const [key,setKey]=useState(''),[show,setShow]=useState(false),[remember,setRemember]=useState(true),[busy,setBusy]=useState(false);
 const submit=async(e:React.FormEvent)=>{e.preventDefault();if(!key.trim())return;setBusy(true);try{await onKey(key.trim(),remember)}finally{setBusy(false)}};
 const social=(id:string)=>providers.find(p=>p.id===id);
 return <div className="login-screen">
  <div className="login-art" aria-hidden="true"><svg viewBox="0 0 400 220" preserveAspectRatio="xMidYMax slice"><defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#0b2a6b"/><stop offset=".55" stopColor="#3b6fd8"/><stop offset="1" stopColor="#f3a96b"/></linearGradient></defs><rect width="400" height="220" fill="url(#sky)"/><g fill="#0a1d45"><path d="M150 160h100v-30l-6-4v-22l-5-4V78l-4-6-5-22-5 22-4 6v22l-5 4v22l-6 4z"/><path d="M110 165h40v-25l-4-3v-16l-4-4-4-16-4 16-4 4v16l-4 3zM250 165h40v-25l-4-3v-16l-4-4-4-16-4 16-4 4v16l-4 3z"/><path d="M90 168h220v8H90zM30 175c10-30 20-40 22-60 2 20 12 30 22 60zM330 175c8-25 16-34 18-50 2 16 10 25 18 50z"/><rect y="176" width="400" height="44" opacity=".85"/></g></svg></div>
  <form className="login-card" onSubmit={submit}>
   <span className="login-logo"><svg viewBox="0 0 32 32" width="30" height="30" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M5 9l7 7-7 7M27 9l-7 7 7 7M12 16h8"/></svg></span>
   <h1>KhmerLive AI</h1>
   <p className="login-sub">Video Translation &amp; Dubbing</p>
   <p className="login-pair">English ⇔ Khmer</p>
   <label className="login-field"><Icon name="key"/><input type={show?'text':'password'} placeholder="Administrator API key" aria-label="API key" value={key} onChange={e=>setKey(e.target.value)} autoComplete="current-password"/><button type="button" className="icon-btn" aria-label={show?'Hide key':'Show key'} onClick={()=>setShow(v=>!v)}><Icon name="eye"/></button></label>
   <div className="login-row"><label><input type="checkbox" checked={remember} onChange={e=>setRemember(e.target.checked)}/> Remember me</label><a href="/api/docs" target="_blank" rel="noopener">API docs</a></div>
   {error&&<div className="login-error" role="alert">{error}</div>}
   <button className="btn btn-primary btn-block" disabled={busy||!key.trim()}>{busy?'Signing in…':'Sign In'}</button>
   <div className="login-or"><span>or continue with</span></div>
   <div className="login-social">{(['google','github','facebook'] as const).filter(id=>social(id)).map(id=>{const p=social(id)!;return <button type="button" key={id} className="btn btn-light" disabled={!p.enabled} title={p.enabled?'Sign in with '+p.name:p.name+' OAuth is not configured on the server'} onClick={()=>{window.location.href='/api/auth/login/'+id}}>{id==='google'?<b className="g">G</b>:id==='github'?<b>◈</b>:<b className="f">f</b>}{p.name}</button>})}</div>
   <p className="login-foot">Use the <code>API_KEY</code> from your <code>.env</code>, or a configured social account.</p>
  </form>
 </div>;
}

/* ---------- 2. Dashboard ---------- */
const DAY=86400000;
function bucketDays(jobs:Job[],days:number){
 const today=new Date();today.setHours(0,0,0,0);
 const start=today.getTime()-(days-1)*DAY;
 const counts=Array.from({length:days},()=>0);
 for(const j of jobs){if(!j.created_at)continue;const t=new Date(j.created_at).getTime();const i=Math.floor((t-start)/DAY);if(i>=0&&i<days)counts[i]++}
 return counts.map((n,i)=>({n,date:new Date(start+i*DAY)}));
}
function LineChart({data}:{data:{n:number;date:Date}[]}){
 const W=520,H=210,L=34,B=26,T=10,R=26;
 const max=Math.max(4,...data.map(d=>d.n));const nice=Math.ceil(max/4)*4;
 const x=(i:number)=>L+(data.length<2?0:i*(W-L-R)/(data.length-1));const y=(v:number)=>T+(H-T-B)*(1-v/nice);
 const line=data.map((d,i)=>(i?'L':'M')+x(i).toFixed(1)+','+y(d.n).toFixed(1)).join(' ');
 const every=Math.ceil(data.length/7);
 return <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Jobs created per day">
  <defs><linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="var(--primary)" stopOpacity=".28"/><stop offset="1" stopColor="var(--primary)" stopOpacity="0"/></linearGradient></defs>
  {[0,1,2,3,4].map(i=>{const v=nice*i/4;return <g key={i}><line x1={L} x2={W-R} y1={y(v)} y2={y(v)} className="grid"/><text x={L-8} y={y(v)+4} textAnchor="end">{v}</text></g>})}
  <path d={line+` L${x(data.length-1)},${y(0)} L${x(0)},${y(0)} Z`} fill="url(#area)"/>
  <path d={line} fill="none" stroke="var(--primary)" strokeWidth="2.5"/>
  {data.map((d,i)=><g key={i}><circle cx={x(i)} cy={y(d.n)} r={data.length>31?0:4} className="dot"><title>{d.date.toLocaleDateString()}: {d.n} jobs</title></circle>{i%every===0&&<text x={x(i)} y={H-6} textAnchor="middle">{d.date.toLocaleDateString(undefined,{month:'short',day:'numeric'})}</text>}</g>)}
 </svg>;
}
function Donut({parts,total}:{parts:{label:string;value:number;color:string}[];total:number}){
 const r=46,c=2*Math.PI*r;let acc=0;
 return <svg viewBox="0 0 120 120" className="donut" role="img" aria-label="Jobs by source">
  <circle cx="60" cy="60" r={r} fill="none" stroke="var(--line)" strokeWidth="13"/>
  {total>0&&parts.map(p=>{const len=c*p.value/total;const el=<circle key={p.label} cx="60" cy="60" r={r} fill="none" stroke={p.color} strokeWidth="13" strokeDasharray={`${len} ${c-len}`} strokeDashoffset={-acc} transform="rotate(-90 60 60)"/>;acc+=len;return el})}
  <text x="60" y="60" textAnchor="middle" className="donut-n">{total}</text><text x="60" y="76" textAnchor="middle" className="donut-l">Jobs</text>
 </svg>;
}
export function Dashboard({ctx}:{ctx:Ctx}){
 const [range,setRange]=useState<'7'|'30'|'90'>('7');
 const {metrics:m,jobs}=ctx;
 const pct=(n:number)=>m.total?Math.round(n*100/m.total):0;
 const data=useMemo(()=>bucketDays(jobs,Number(range)),[jobs,range]);
 const srcCount=(k:string)=>jobs.filter(j=>(j.source_kind||'upload')===k).length;
 const sources=[{label:'YouTube',value:srcCount('youtube'),color:'var(--red)',ico:'play',cls:'yt'},{label:'Upload',value:srcCount('upload'),color:'var(--primary)',ico:'upload',cls:'up'},{label:'Stream URL',value:srcCount('url'),color:'var(--sky)',ico:'link',cls:'url'}];
 const srcTotal=jobs.length;
 const stats:[string,number,string,string,string][]= [
  ['Total Jobs',m.total,'layers','blue',''],
  ['Completed',m.completed,'check','green',pct(m.completed)+'%'],
  ['Processing',m.processing+m.queued,'refresh','sky',pct(m.processing+m.queued)+'%'],
  ['Failed',m.failed,'x','red',pct(m.failed)+'%'],
 ];
 return <>
  <PageHead title="Dashboard" sub="Overview of video translation and dubbing"><span className="chip"><Icon name="calendar" size={15}/>Last {range} Days</span></PageHead>
  <div className="stat-grid">{stats.map(([t,n,ic,k,p])=><div className={'card stat stat-'+k} key={t}><span className="stat-ico"><Icon name={ic} size={22}/></span><div><b>{n}</b><small>{t}</small></div>{p&&<div className="stat-foot"><Progress value={parseInt(p)} kind={k}/><em>{p}</em></div>}</div>)}</div>
  <div className="dash-grid">
   <section className="card pad"><div className="card-title"><h2>Job Activity</h2><Tabs items={[['7','7 Days'],['30','30 Days'],['90','90 Days']]} value={range} onChange={setRange}/></div><LineChart data={data}/>{jobs.length>=100&&<p className="muted small">Chart uses the 100 most recent jobs.</p>}</section>
   <section className="card pad"><div className="card-title"><h2>Jobs by Source</h2></div><div className="donut-wrap"><Donut total={srcTotal} parts={sources}/>
    <ul className="legend">{sources.map(x=><li key={x.label}><span className={'src-ico '+x.cls}><Icon name={x.ico} size={15}/></span>{x.label}<b>{srcTotal?Math.round(x.value*100/srcTotal):0}%</b></li>)}</ul></div></section>
  </div>
  <section className="card"><div className="card-title pad-x"><h2>Recent Jobs</h2><button className="btn btn-ghost" onClick={()=>ctx.go('/jobs')}>View all <Icon name="arrowR" size={15}/></button></div><JobTable jobs={jobs.slice(0,5)} go={ctx.go}/></section>
 </>;
}

/* ---------- 3/4. New translation wizard ---------- */
export function NewJob({ctx}:{ctx:Ctx}){
 const [step,setStep]=useState<1|2|3>(1);
 const [source,setSource]=useState<'upload'|'url'|'youtube'>('upload');
 const [file,setFile]=useState<File|null>(null),[url,setUrl]=useState(''),[seconds,setSeconds]=useState(30);
 const [srcLang,setSrcLang]=useState<'en'|'km'>('en');
 const [busy,setBusy]=useState(false),[pct,setPct]=useState<number|null>(null),[err,setErr]=useState('');
 const [drag,setDrag]=useState(false);
 const input=useRef<HTMLInputElement>(null);
 const m=ctx.models;const real=isReal(m);const tgt=srcLang==='en'?'km':'en';
 const dub=dubbingFor(m,srcLang);
 const missing=real&&(m?.subtitle_translation_configured===false||(dub&&!m?.speech_dubbing_available));
 const choose=(f?:File)=>{if(!f)return;if(!f.name.toLowerCase().endsWith('.mp4')){setErr('Only MP4 files are supported. Export your video as MP4 (H.264).');return}setErr('');setFile(f)};
 const urlOk=/^https?:\/\/.+/i.test(url.trim());
 const ytMismatch=source==='youtube'&&urlOk&&!isYouTubeUrl(url);
 const ready1=source==='upload'?!!file:source==='youtube'?urlOk&&isYouTubeUrl(url):urlOk&&!isYouTubeUrl(url);
 const submit=async()=>{
  setBusy(true);setErr('');
  try{
   let id:string;
   if(source!=='upload'){id=(await req<{job_id:string}>('/api/jobs/from-url',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:url.trim(),capture_seconds:seconds,source_lang:srcLang,target_lang:tgt})})).job_id}
   else{setPct(0);const media=await uploadMedia(file!,setPct);id=(await req<{job_id:string}>('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({media_id:media.media_id,source_lang:srcLang,target_lang:tgt})})).job_id}
   ctx.notify(real?'Translation job queued':'Demo job queued');void ctx.refresh();ctx.go('/job/'+id);
  }catch(e){setErr(String(e instanceof Error?e.message:e))}finally{setBusy(false);setPct(null)}
 };
 const stepper=<div className="stepper">{(['Input','Settings','Review'] as const).map((l,i)=>{const n=(i+1) as 1|2|3;return <button key={l} className={'step'+(step===n?' current':'')+(step>n?' done':'')} onClick={()=>{if(n<step||(n===2&&ready1)||(n===3&&ready1))setStep(n)}}><span>{step>n?<Icon name="check" size={13}/>:n}</span>{l}</button>})}</div>;
 return <>
  <PageHead title={step===2?'Translation Settings':'New Translation Job'} sub={step===2?'Configure translation and dubbing options':'Translate and dub a video with AI'}/>
  <section className="card pad wizard">
   {stepper}
   {err&&<div className="alert alert-err">{err}</div>}
   {missing&&<div className="alert alert-err"><b>Offline models missing.</b> Install Whisper, M2M100{dub?' and Khmer MMS TTS':''} under <code>models/</code> and restart the real worker before submitting.</div>}
   {step===1&&<>
    <h2 className="sec">Choose Video Source</h2>
    <div className="source-cards">
     <button className={'source-card'+(source==='upload'?' active':'')} onClick={()=>setSource('upload')}><Icon name="upload" size={22}/><span><b>Upload Video</b><small>MP4 (H.264)</small></span></button>
     <button className={'source-card yt'+(source==='youtube'?' active':'')} onClick={()=>setSource('youtube')}><span className="yt-logo" aria-hidden="true"><Icon name="play" size={14}/></span><span><b>YouTube URL</b><small>youtube.com / youtu.be</small></span></button>
     <button className={'source-card'+(source==='url'?' active':'')} onClick={()=>setSource('url')}><Icon name="link" size={22}/><span><b>Video URL</b><small>MP4 / HLS (.m3u8)</small></span></button>
    </div>
    {source==='upload'?<div className={'dropzone'+(drag?' drag':'')} role="button" tabIndex={0} onClick={()=>input.current?.click()} onKeyDown={e=>{if(e.key==='Enter'||e.key===' ')input.current?.click()}} onDragOver={e=>{e.preventDefault();setDrag(true)}} onDragLeave={()=>setDrag(false)} onDrop={e=>{e.preventDefault();setDrag(false);choose(e.dataTransfer.files[0])}}>
      <Icon name="cloud" size={44}/>
      {file?<><b>{file.name}</b><span>{size(file.size)} · click to replace</span></>:<><b>Drag &amp; drop video here</b><span>or click to browse</span></>}
      <small>Supported: MP4 (H.264) · size limit set by server MAX_UPLOAD_MB</small>
      <input ref={input} type="file" accept=".mp4,video/mp4" hidden onChange={e=>choose(e.target.files?.[0])}/>
     </div>
     :source==='youtube'?<div className="url-box"><label className="field"><span>YouTube video link</span><input type="url" placeholder="https://www.youtube.com/watch?v=… or https://youtu.be/…" value={url} onChange={e=>setUrl(e.target.value)}/></label>{ytMismatch&&<p className="field-err">That is not a YouTube link. Use the Video URL option for direct MP4/HLS files.</p>}<p className="muted small">The server downloads the video (single public video, not live) and translates and dubs it like an upload. Videos longer than <code>MAX_VIDEO_DURATION_SECONDS</code> (default 10 min) are trimmed to their first 10 minutes. Only process videos you have the rights to use.</p></div>
     :<div className="url-box"><label className="field"><span>Stream or file URL</span><input type="url" placeholder="https://video.example.org/live/index.m3u8" value={url} onChange={e=>setUrl(e.target.value)}/></label><label className="field"><span>Capture duration</span><select value={seconds} onChange={e=>setSeconds(Number(e.target.value))}>{[15,30,60,120].map(s=><option key={s} value={s}>{s} seconds</option>)}</select></label>{urlOk&&isYouTubeUrl(url)&&<p className="field-err">YouTube links go in the YouTube URL option.</p>}<p className="muted small">The host must be listed in the server's <code>STREAM_ALLOWED_HOSTS</code>. URL capture is restricted to administrators unless <code>STREAM_URL_ALLOW_USERS</code> is enabled.</p></div>}
    <div className="wizard-foot"><span/><button className="btn btn-primary" disabled={!ready1} onClick={()=>setStep(2)}>Next <Icon name="arrowR" size={15}/></button></div>
   </>}
   {step===2&&<>
    <h3 className="sub">Language</h3>
    <div className="lang-row">
     <label className="field"><span>Source Language</span><select value={srcLang} onChange={e=>setSrcLang(e.target.value as 'en'|'km')}><option value="en">🇬🇧 English (en)</option><option value="km">🇰🇭 Khmer (km)</option></select></label>
     <button className="swap" aria-label="Swap languages" onClick={()=>setSrcLang(tgt)}><Icon name="arrowR"/></button>
     <label className="field"><span>Target Language</span><select value={tgt} onChange={e=>setSrcLang(e.target.value==='km'?'en':'km')}><option value="km">🇰🇭 Khmer (km)</option><option value="en">🇬🇧 English (en)</option></select></label>
    </div>
    <h3 className="sub">Dubbing Options</h3>
    <div className="opt"><div><b>Enable Dubbing</b><small>{dub?'Replace audio with offline Khmer voice (MMS TTS)':srcLang==='km'?'Khmer → English is subtitle-only':real?'Disabled on server (ENABLE_KHMER_DUBBING=false)':'Demo mode keeps the original audio'}</small></div><Toggle label="Enable dubbing" checked={dub} disabled/></div>
    <div className="opt"><div><b>Generate Subtitles</b><small>{real?'Translated SRT + embedded subtitle track':'Demo mode produces placeholder text only'}</small></div><Toggle label="Generate subtitles" checked={real} disabled/></div>
    <div className="opt"><div><b>Preserve Background Music</b><small>{dub?'Not separated: the dubbed track replaces source audio':'Original audio is kept unchanged'}</small></div><Toggle label="Preserve background music" checked={!dub} disabled/></div>
    <h3 className="sub">Voice &amp; Synchronization</h3>
    <div className="opt"><div><b>Voice</b><small>facebook/mms-tts-khm single-speaker model</small></div><span className="chip">{dub?'Khmer (MMS)':'—'}</span></div>
    {source==='url'&&<div className="opt"><div><b>Capture duration</b><small>Bounded recording, not continuous dubbing</small></div><span className="chip">{seconds}s</span></div>}
    <p className="muted small">Options are set by the server's <b>{real?'real_subtitles':'demo'}</b> mode; per-job overrides are not supported yet.</p>
    <div className="wizard-foot"><button className="btn btn-light" onClick={()=>setStep(1)}><Icon name="arrowL" size={15}/> Back</button><button className="btn btn-primary" onClick={()=>setStep(3)}>Next <Icon name="arrowR" size={15}/></button></div>
   </>}
   {step===3&&<>
    <h2 className="sec">Review</h2>
    <dl className="kv">
     <dt>Source</dt><dd className="break">{source==='upload'?(file?.name+' · '+size(file?.size)):source==='youtube'?'YouTube · '+url.trim()+' (first 10 min if longer)':url+' ('+seconds+'s capture)'}</dd>
     <dt>Translation</dt><dd>{lang(srcLang)} → {lang(tgt)}</dd>
     <dt>Mode</dt><dd><span className={'mode-pill '+(real?'real':'demo')}>{real?'Real (offline AI)':'Demo'}</span></dd>
     <dt>Output</dt><dd>{!real?'Remuxed video with original audio (no AI processing)':dub?'Khmer dubbed MP4 + Khmer subtitles (SRT)':'MP4 with translated subtitles + SRT'}</dd>
    </dl>
    {pct!==null&&<div className="upload-pct">Uploading {pct}%<Progress value={pct}/></div>}
    <div className="wizard-foot"><button className="btn btn-light" disabled={busy} onClick={()=>setStep(2)}><Icon name="arrowL" size={15}/> Back</button><button className="btn btn-primary" disabled={busy||missing||!ready1} onClick={()=>void submit()}>{busy?'Submitting…':'Start Translation'} <Icon name="arrowR" size={15}/></button></div>
   </>}
  </section>
 </>;
}

/* ---------- 5/6. Job processing + result ---------- */
const stageLog=new Map<string,{t:Date;msg:string}[]>();
function recordStage(j:Job){
 const log=stageLog.get(j.id)||[];const msg=j.stage||j.status;
 if(!log.length||log[log.length-1].msg!==msg){log.push({t:new Date(),msg});stageLog.set(j.id,log.slice(-40))}
 return log;
}
type StepState='done'|'run'|'wait'|'fail'|'skip';
function steps(j:Job,dub:boolean):{title:string;state:StepState;note:string}[]{
 const p=j.progress||0,done=j.status==='completed',failed=isFailed(j.status)||j.status==='cancelled';
 const acqEnd=j.source_kind==='url'?15:25;
 const defs:[string,number,number,boolean][]=[
  ['Video Acquisition',0,acqEnd,true],
  ['Speech Recognition (ASR)',acqEnd,65,true],
  ['Machine Translation (MT)',45,65,true],
  ['Text-to-Speech (TTS)',70,85,dub],
  ['Audio Synchronization',65,dub?70:85,true],
  ['Video Rendering',85,101,true],
 ];
 return defs.map(([title,s,e,applies])=>{
  if(!applies)return {title,state:'skip' as StepState,note:'Not used for this job'};
  if(done)return {title,state:'done' as StepState,note:'Completed'};
  if(p>=e||(title.startsWith('Audio')&&dub&&p>=85))return {title,state:'done' as StepState,note:'Completed'};
  if(p>=s)return failed?{title,state:'fail' as StepState,note:j.status==='cancelled'?'Cancelled':'Stopped'}:{title,state:'run' as StepState,note:j.stage||'Running'};
  return {title,state:'wait' as StepState,note:failed?'Not started':'Pending'};
 });
}
function VideoThumb({job,big}:{job:Job;big?:boolean}){
 return <div className={'thumb-art'+(big?' big':'')} aria-hidden="true"><span className="thumb-play"><Icon name="play" size={big?26:16}/></span><span className="thumb-lang">{job.source_lang.toUpperCase()} → {job.target_lang.toUpperCase()}</span></div>;
}
export function JobPage({ctx,id}:{ctx:Ctx;id:string}){
 const [job,setJob]=useState<Job|null>(null),[err,setErr]=useState('');
 const [view,setView]=useState<'auto'|'details'>('auto');
 const load=async()=>{try{const j=await req<Job>('/api/jobs/'+id);recordStage(j);setJob(j);setErr('')}catch(e){setErr(String(e instanceof Error?e.message:e))}};
 useEffect(()=>{setJob(null);setView('auto');void load()},[id]);
 useEffect(()=>{if(!job||!isActive(job.status))return;const t=window.setInterval(()=>void load(),2500);return()=>clearInterval(t)},[job?.status,id]);
 if(err&&!job)return <><PageHead title="Job" sub={id}/><div className="alert alert-err">{err}</div></>;
 if(!job)return <div className="card pad skeleton-block"/>;
 const action=async(which:'cancel'|'retry')=>{if(which==='cancel'&&!window.confirm('Cancel '+job.filename+'? The current step may need to finish first.'))return;try{await req('/api/jobs/'+job.id+'/'+which,{method:'POST'});ctx.notify(which==='cancel'?'Cancellation requested':'Job re-queued');await load();void ctx.refresh()}catch(e){ctx.notify(String(e instanceof Error?e.message:e),'err')}};
 if(job.status==='completed'&&view==='auto')return <JobResult ctx={ctx} job={job} onDetails={()=>setView('details')}/>;
 return <JobProcessing ctx={ctx} job={job} action={action} onResult={job.status==='completed'?()=>setView('auto'):undefined}/>;
}
function JobProcessing({ctx,job,action,onResult}:{ctx:Ctx;job:Job;action:(w:'cancel'|'retry')=>void;onResult?:()=>void}){
 const [tab,setTab]=useState<'logs'|'metrics'>('logs');
 const dub=job.processing_mode==='real_subtitles'&&job.source_lang==='en'&&(job.has_khmer_voice||!!ctx.models?.khmer_dubbing_enabled);
 const list=steps(job,dub);const log=stageLog.get(job.id)||[];
 const statusChip=job.status==='completed'?<span className="badge badge-ok"><Icon name="check" size={13}/>Completed</span>:isActive(job.status)?<span className="badge badge-run"><span className="spin"/>{job.status==='queued'?'Queued':job.status==='cancelling'?'Cancelling':'Processing'}</span>:<Badge status={job.status}/>;
 return <>
  <PageHead title="Job Details" sub={shortId(job.id)+' · '+baseName(job.filename)}>{onResult&&<button className="btn btn-light" onClick={onResult}>View result</button>}</PageHead>
  <section className="card pad">
   <div className="job-top"><VideoThumb job={job} big/><dl className="kv compact"><dt>Source</dt><dd>{job.source_kind==='url'?'Stream URL ('+(job.capture_seconds||30)+'s)':sourceLabel(job.source_kind,job.capture_seconds)+' · '+size(job.size_bytes)}</dd><dt>Source language</dt><dd>{lang(job.source_lang)}</dd><dt>Target</dt><dd>{lang(job.target_lang)}</dd><dt>Dubbing</dt><dd>{dub?'Enabled':'Disabled'}</dd><dt>Subtitles</dt><dd>{job.processing_mode==='real_subtitles'?'Enabled':'Demo'}</dd><dt>Created</dt><dd>{asDate(job.created_at)}</dd></dl><div className="job-status">{statusChip}</div></div>
   <div className="proc-head"><b>{job.status==='completed'?'Completed':isActive(job.status)?'Processing…':job.status==='cancelled'?'Cancelled':'Stopped'}</b><b>{job.progress}%</b></div>
   <Progress value={job.progress} kind={isFailed(job.status)?'red':job.status==='completed'?'green':''}/>
   <div className="proc-grid">
    <ol className="pipeline">{list.map((s,i)=><li key={s.title} className={'ps-'+s.state}><span className="ps-node">{s.state==='done'?<Icon name="check" size={14}/>:s.state==='run'?<span className="spin"/>:s.state==='fail'?<Icon name="x" size={14}/>:i+1}</span><div><b>{i+1}. {s.title}</b><small>{s.note}</small></div><em>{s.state==='done'?'Completed':s.state==='run'?'Running':s.state==='skip'?'Skipped':s.state==='fail'?'Stopped':'Pending'}</em></li>)}</ol>
    <div className="logs"><Tabs variant="line" items={[['logs','Logs'],['metrics','Metrics']]} value={tab} onChange={setTab}/>
     {tab==='logs'?<ul className="log-list">{log.map((l,i)=><li key={i}><time>{asTime(l.t)}</time><span>{l.msg}</span></li>)}{!log.length&&<li><span className="muted">Waiting for worker updates…</span></li>}</ul>
     :<dl className="kv compact"><dt>Progress</dt><dd>{job.progress}%</dd><dt>Mode</dt><dd>{job.processing_mode==='real_subtitles'?'Real (offline AI)':'Demo'}</dd><dt>File size</dt><dd>{size(job.size_bytes)}</dd><dt>Last update</dt><dd>{asDate(job.updated_at)}</dd><dt>Job ID</dt><dd className="mono">{job.id}</dd></dl>}
    </div>
   </div>
   {job.error&&<div className="alert alert-err"><b>Job failed.</b> {job.error}</div>}
   <div className="row-end">{isActive(job.status)?<button className="btn btn-danger" disabled={job.status==='cancelling'} onClick={()=>action('cancel')}><Icon name="x" size={15}/>{job.status==='cancelling'?'Cancelling…':'Cancel Job'}</button>:job.status!=='completed'&&<button className="btn btn-primary" onClick={()=>action('retry')}><Icon name="refresh" size={15}/>Retry Job</button>}</div>
  </section>
 </>;
}
function usePlayback(job:Job){
 const [p,setP]=useState<{video_url:string;captions_url:string|null}|null>(null),[err,setErr]=useState('');
 useEffect(()=>{let closed=false;setP(null);setErr('');
  const load=async()=>{try{const r=await req<{video_url:string;captions_url:string|null}>('/api/jobs/'+job.id+'/player-token');if(!closed)setP(r)}catch(e){if(!closed)setErr(String(e instanceof Error?e.message:e))}};
  void load();return()=>{closed=true}},[job.id]);
 return {p,err};
}
function JobResult({ctx,job,onDetails}:{ctx:Ctx;job:Job;onDetails:()=>void}){
 const [tab,setTab]=useState<'output'|'transcript'|'subtitles'>('output');
 const [srt,setSrt]=useState<string|null>(null);
 const {p,err}=usePlayback(job);
 const video=useRef<HTMLVideoElement>(null);const resume=useRef(0);
 const [duration,setDuration]=useState<number|null>(null);
 useEffect(()=>{if(tab!=='subtitles'||srt!==null||!job.has_subtitles)return;void (async()=>{try{const h:Record<string,string>={};const k=getApiKey();if(k)h['X-API-Key']=k;const r=await fetch('/api/jobs/'+job.id+'/subtitles',{headers:h});setSrt(r.ok?await r.text():'Subtitles unavailable ('+r.status+')')}catch(e){setSrt(String(e))}})()},[tab,job.id]);
 const fmt=(s:number|null)=>s==null?'—':Math.floor(s/60).toString().padStart(2,'0')+':'+Math.floor(s%60).toString().padStart(2,'0');
 const transcriptTxt=`${lang(job.source_lang)} transcript\n\n${job.transcript||''}\n\n${lang(job.target_lang)} translation\n\n${job.translation||''}\n`;
 const fail=(e:unknown)=>ctx.notify(String(e instanceof Error?e.message:e),'err');
 const share=async()=>{try{await navigator.clipboard.writeText(location.origin+'/#/job/'+job.id);ctx.notify('Link copied (viewers need access to this job)')}catch{ctx.notify('Could not copy link','err')}};
 return <>
  <PageHead title="Job Result" sub={shortId(job.id)+' · '+baseName(job.filename)}><button className="btn btn-light" onClick={()=>void share()}><Icon name="share" size={15}/>Share</button><button className="btn btn-light" onClick={onDetails}>Pipeline</button></PageHead>
  <div className="result-grid">
   <section className="card pad">
    <div className="row-end"><span className="badge badge-ok"><Icon name="check" size={13}/>Completed</span></div>
    <div className="player">{p?<video ref={video} key={p.video_url} controls playsInline preload="metadata" src={p.video_url} onLoadedMetadata={e=>{setDuration(e.currentTarget.duration);if(resume.current)e.currentTarget.currentTime=resume.current}} onTimeUpdate={e=>{resume.current=e.currentTarget.currentTime}} aria-label="Translated video">{p.captions_url&&<track kind="subtitles" default srcLang={job.target_lang} label={lang(job.target_lang)+' subtitles'} src={p.captions_url}/>}</video>:<div className="player-empty"><Icon name="play" size={32}/><small>{err||'Loading secure preview…'}</small></div>}</div>
    <p className="muted small">{job.has_khmer_voice?'Khmer voice dubbing + translated subtitles':job.has_subtitles?'Translated subtitles · original speech retained':'Demo output · original speech retained, no AI processing'}</p>
   </section>
   <section className="card pad">
    <Tabs variant="line" items={[['output','Output'],['transcript','Transcript'],['subtitles','Subtitles']]} value={tab} onChange={setTab}/>
    {tab==='output'&&<div className="outputs">
     <button className="out-row" onClick={()=>void downloadVideo(job).catch(fail)}><Icon name="download"/><span><b>{job.has_khmer_voice?'Dubbed Video (MP4)':'Video (MP4)'}</b><small>{size(job.size_bytes)} source</small></span><Icon name="download" size={16}/></button>
     <button className="out-row" disabled={!job.has_subtitles} onClick={()=>void downloadBlob('/api/jobs/'+job.id+'/subtitles',baseName(job.filename)+'-'+job.target_lang+'.srt').catch(fail)}><Icon name="file"/><span><b>Subtitles (SRT)</b><small>{job.has_subtitles?lang(job.target_lang):'Not generated in demo mode'}</small></span><Icon name="download" size={16}/></button>
     <button className="out-row" disabled={!job.transcript&&!job.translation} onClick={()=>saveBlob(new Blob([transcriptTxt],{type:'text/plain;charset=utf-8'}),baseName(job.filename)+'-transcript.txt')}><Icon name="file"/><span><b>Transcript (TXT)</b><small>{lang(job.source_lang)} &amp; {lang(job.target_lang)}</small></span><Icon name="download" size={16}/></button>
    </div>}
    {tab==='transcript'&&<div className="transcript"><h4>{lang(job.source_lang)}</h4><p>{job.transcript||'No transcript'}</p><h4>{lang(job.target_lang)}</h4><p className="km">{job.translation||'No translation'}</p></div>}
    {tab==='subtitles'&&<pre className="srt">{job.has_subtitles?(srt??'Loading…'):'No subtitle file for this job.'}</pre>}
    <h3 className="sub">Job Info</h3>
    <dl className="kv compact"><dt>Source</dt><dd>{sourceLabel(job.source_kind,job.capture_seconds)}</dd><dt>Duration</dt><dd>{fmt(duration)}</dd><dt>Created</dt><dd>{asDate(job.created_at)}</dd><dt>Mode</dt><dd>{job.processing_mode==='real_subtitles'?'Real':'Demo'}</dd></dl>
   </section>
  </div>
 </>;
}

/* ---------- 7. My Jobs ---------- */
export function JobTable({jobs,go,onAction}:{jobs:Job[];go:(p:string)=>void;onAction?:(j:Job,w:'cancel'|'retry')=>void}){
 return <div className="table-wrap"><table className="table"><thead><tr><th>#</th><th>Title</th><th>Source</th><th>Language</th><th>Status</th><th>Progress</th><th>Created</th>{onAction&&<th/>}</tr></thead><tbody>
  {jobs.map(j=><tr key={j.id} onClick={()=>go('/job/'+j.id)} tabIndex={0} onKeyDown={e=>{if(e.key==='Enter')go('/job/'+j.id)}}>
   <td className="mono">{shortId(j.id)}</td><td className="title-cell" title={j.filename}>{baseName(j.filename)}</td>
   <td><span className={'src-ico '+(j.source_kind==='youtube'?'yt':j.source_kind==='url'?'url':'up')} title={sourceLabel(j.source_kind)}><Icon name={j.source_kind==='youtube'?'play':j.source_kind==='url'?'link':'upload'} size={15}/></span></td>
   <td>{j.source_lang.toUpperCase()} → {j.target_lang.toUpperCase()}</td>
   <td><Badge status={j.status}/></td>
   <td><div className="prog-cell"><Progress value={j.progress} kind={j.status==='completed'?'':isFailed(j.status)?'red':''}/><span>{isFailed(j.status)||j.status==='cancelled'?'—':j.progress+'%'}</span></div></td>
   <td className="muted nowrap">{asDate(j.created_at)}</td>
   {onAction&&<td onClick={e=>e.stopPropagation()}>{j.has_output?<button className="btn btn-xs" title="Download MP4" onClick={()=>void downloadVideo(j)}><Icon name="download" size={14}/></button>:isActive(j.status)?<button className="btn btn-xs" disabled={j.status==='cancelling'} onClick={()=>onAction(j,'cancel')}>Cancel</button>:<button className="btn btn-xs" onClick={()=>onAction(j,'retry')}>Retry</button>}</td>}
  </tr>)}
  {!jobs.length&&<tr><td colSpan={8}><div className="empty"><b>No jobs yet</b><span>Start a new translation to see it here.</span><button className="btn btn-primary" onClick={()=>go('/new')}>New Translation</button></div></td></tr>}
 </tbody></table></div>;
}
export function MyJobs({ctx}:{ctx:Ctx}){
 const [filter,setFilter]=useState<'all'|'active'|'completed'|'failed'>('all');
 const [q,setQ]=useState(''),[search,setSearch]=useState(''),[offset,setOffset]=useState(0),[limit,setLimit]=useState(10);
 const [data,setData]=useState<{items:Job[];total:number}>({items:[],total:0}),[loading,setLoading]=useState(true);
 const load=async()=>{try{const p=new URLSearchParams({limit:String(limit),offset:String(offset),status:filter});if(search)p.set('search',search);setData(await req('/api/jobs?'+p))}catch(e){ctx.notify(String(e instanceof Error?e.message:e),'err')}finally{setLoading(false)}};
 useEffect(()=>{void load()},[filter,search,offset,limit]);
 useEffect(()=>{const t=window.setInterval(()=>void load(),6000);return()=>clearInterval(t)},[filter,search,offset,limit]);
 useEffect(()=>{const t=window.setTimeout(()=>{setSearch(q.trim());setOffset(0)},300);return()=>clearTimeout(t)},[q]);
 const m=ctx.metrics;const pages=Math.max(1,Math.ceil(data.total/limit));const page=Math.floor(offset/limit)+1;
 const action=async(j:Job,w:'cancel'|'retry')=>{if(w==='cancel'&&!window.confirm('Cancel '+j.filename+'?'))return;try{await req('/api/jobs/'+j.id+'/'+w,{method:'POST'});ctx.notify(w==='cancel'?'Cancellation requested':'Job re-queued');void load();void ctx.refresh()}catch(e){ctx.notify(String(e instanceof Error?e.message:e),'err')}};
 const nums=Array.from(new Set([1,page-1,page,page+1,pages].filter(n=>n>=1&&n<=pages))).sort((a,b)=>a-b);
 return <>
  <PageHead title="My Jobs" sub="Manage and track all translation jobs"><button className="btn btn-primary" onClick={()=>ctx.go('/new')}><Icon name="plus" size={16}/>New Translation</button></PageHead>
  <section className="card">
   <div className="toolbar"><Tabs items={[['all',`All (${m.total})`],['active',`Processing (${m.processing+m.queued})`],['completed',`Completed (${m.completed})`],['failed',`Failed (${m.failed})`]]} value={filter} onChange={v=>{setFilter(v);setOffset(0)}}/>
    <label className="search"><Icon name="search" size={16}/><input placeholder="Search by title or job ID" value={q} onChange={e=>setQ(e.target.value)} aria-label="Search jobs"/></label></div>
   {loading?<div className="pad"><div className="skeleton-block"/></div>:<JobTable jobs={data.items} go={ctx.go} onAction={(j,w)=>void action(j,w)}/>}
   <div className="pager"><label>Rows per page <select value={limit} onChange={e=>{setLimit(Number(e.target.value));setOffset(0)}}>{[10,25,50].map(n=><option key={n}>{n}</option>)}</select></label>
    <div><button aria-label="Previous page" disabled={page<=1} onClick={()=>setOffset(offset-limit)}>‹</button>{nums.map((n,i)=><React.Fragment key={n}>{i>0&&n-nums[i-1]>1&&<span>…</span>}<button className={n===page?'active':''} onClick={()=>setOffset((n-1)*limit)}>{n}</button></React.Fragment>)}<button aria-label="Next page" disabled={page>=pages} onClick={()=>setOffset(offset+limit)}>›</button></div></div>
  </section>
 </>;
}

/* ---------- 8. Video Library ---------- */
function LibraryCard({job,go,grid}:{job:Job;go:(p:string)=>void;grid:boolean}){
 const {p}=usePlayback(job);const [dur,setDur]=useState<number|null>(null);
 return <button className={'lib-card'+(grid?'':' row')} onClick={()=>go('/job/'+job.id)}>
  <div className="lib-thumb"><VideoThumb job={job}/>{p&&<video muted preload="metadata" src={p.video_url+'#t=1'} onLoadedMetadata={e=>setDur(e.currentTarget.duration)}/>}<span className="thumb-play"><Icon name="play" size={16}/></span>{dur!=null&&<em>{Math.floor(dur/60).toString().padStart(2,'0')}:{Math.floor(dur%60).toString().padStart(2,'0')}</em>}</div>
  <div className="lib-meta"><b title={job.filename}>{baseName(job.filename)}</b><small>{shortId(job.id)} · {asDate(job.created_at)}</small><small>{job.has_khmer_voice?'Khmer dubbed':job.has_subtitles?'Subtitled':'Demo'} · {job.source_lang.toUpperCase()}→{job.target_lang.toUpperCase()}</small></div>
 </button>;
}
export function Library({ctx}:{ctx:Ctx}){
 const [q,setQ]=useState(''),[grid,setGrid]=useState(true);
 const items=ctx.jobs.filter(j=>j.status==='completed'&&j.has_output&&(!q||j.filename.toLowerCase().includes(q.toLowerCase())));
 return <>
  <PageHead title="Video Library" sub="Manage your translated videos"/>
  <section className="card pad">
   <div className="toolbar flat"><label className="search"><Icon name="search" size={16}/><input placeholder="Search videos…" value={q} onChange={e=>setQ(e.target.value)} aria-label="Search videos"/></label><div className="seg"><button aria-label="Grid view" className={grid?'active':''} onClick={()=>setGrid(true)}><Icon name="grid" size={16}/></button><button aria-label="List view" className={!grid?'active':''} onClick={()=>setGrid(false)}><Icon name="list" size={16}/></button></div></div>
   <div className={grid?'lib-grid':'lib-list'}>{items.map(j=><LibraryCard key={j.id} job={j} go={ctx.go} grid={grid}/>)}</div>
   {!items.length&&<div className="empty"><b>No translated videos yet</b><span>Completed jobs with an output video appear here.</span></div>}
  </section>
 </>;
}

/* ---------- 9. AI Models ---------- */
export function Models({ctx}:{ctx:Ctx}){
 const m=ctx.models;const real=isReal(m);
 const [help,setHelp]=useState(false);
 const st=(ok:boolean|undefined,off?:boolean)=>!real?['Demo stub','badge-wait']:off?['Disabled','badge-muted']:ok?['Ready','badge-ok']:['Not installed','badge-bad'];
 const rows:[string,string,string,string[]][]=[
  ['Whisper (ASR)','mic','faster-whisper · models/asr',st(m?.subtitle_translation_configured)],
  ['M2M100 (MT)','translate','facebook/m2m100 · models/mt',st(m?.subtitle_translation_configured)],
  ['Khmer TTS (MMS)','voice','facebook/mms-tts-khm · models/tts',st(m?.speech_dubbing_available,!m?.khmer_dubbing_enabled)],
 ];
 return <>
  <PageHead title="AI Models" sub="Manage and monitor AI models"><span className={'mode-pill '+(real?'real':'demo')}>{real?'MODEL_MODE=real_subtitles':'MODEL_MODE=demo'}</span></PageHead>
  <section className="card pad">
   {rows.map(([name,ic,path,[s,cls]])=><div className="model-row" key={name}><span className="model-ico"><Icon name={ic} size={22}/></span><div><b>{name}</b><small>{path}</small></div><span className={'badge '+cls}>{s==='Ready'&&<Icon name="check" size={13}/>}{s}</span></div>)}
   {m?.note&&<p className="muted small">{m.note}{' '}TTS weights are CC-BY-NC 4.0 (non-commercial).</p>}
   <div className="center"><button className="btn btn-primary" onClick={()=>setHelp(v=>!v)}><Icon name="download" size={16}/>Download / Update Models</button></div>
   {help&&<div className="code-help"><p>Model weights are installed on the server, not from the browser. On the host run:</p><pre>python3 scripts/download-models.py{'\n'}scripts/verify-local-models.sh{'\n'}docker compose -f compose.yaml -f compose.real.yaml up -d --build</pre></div>}
  </section>
 </>;
}

/* ---------- Datasets (parallel text gathered from finished jobs) ---------- */
export function Datasets({ctx}:{ctx:Ctx}){
 const rows=ctx.jobs.filter(j=>j.status==='completed'&&j.transcript&&j.translation&&j.processing_mode==='real_subtitles');
 const exportJsonl=()=>saveBlob(new Blob([rows.map(j=>JSON.stringify({job_id:j.id,source_lang:j.source_lang,target_lang:j.target_lang,source:j.transcript,target:j.translation})).join('\n')+'\n'],{type:'application/jsonl'}),'khmerlive-parallel-text.jsonl');
 return <>
  <PageHead title="Datasets" sub="Parallel EN ⇔ KM text produced by completed real-mode jobs"><button className="btn btn-primary" disabled={!rows.length} onClick={exportJsonl}><Icon name="download" size={16}/>Export JSONL</button></PageHead>
  <section className="card">
   <div className="table-wrap"><table className="table"><thead><tr><th>#</th><th>Title</th><th>Pair</th><th>Source text</th><th>Translation</th></tr></thead><tbody>
    {rows.map(j=><tr key={j.id} onClick={()=>ctx.go('/job/'+j.id)}><td className="mono">{shortId(j.id)}</td><td className="title-cell">{baseName(j.filename)}</td><td>{j.source_lang.toUpperCase()}→{j.target_lang.toUpperCase()}</td><td className="clip">{j.transcript}</td><td className="clip km">{j.translation}</td></tr>)}
    {!rows.length&&<tr><td colSpan={5}><div className="empty"><b>No parallel text yet</b><span>Demo-mode jobs produce placeholder text and are excluded.</span></div></td></tr>}
   </tbody></table></div>
  </section>
 </>;
}

/* ---------- 10. Users & Access ---------- */
export function Users({ctx}:{ctx:Ctx}){
 const [tab,setTab]=useState<'users'|'roles'|'activity'>('users');
 const [dir,setDir]=useState<{items:DirectoryUser[];total:number}|null>(null),[err,setErr]=useState('');
 useEffect(()=>{if(!ctx.isAdmin)return;req<{items:DirectoryUser[];total:number}>('/api/users?limit=100').then(setDir).catch(e=>setErr(String(e instanceof Error?e.message:e)))},[ctx.isAdmin]);
 const a=ctx.account;
 return <>
  <PageHead title="Users &amp; Access" sub="Manage users, roles and permissions"/>
  <section className="card">
   <div className="toolbar"><Tabs variant="line" items={[['users','Users'],['roles','Roles'],['activity','Activity']]} value={tab} onChange={setTab}/></div>
   {tab==='users'&&<>{err&&<div className="alert alert-err m">{err}</div>}<div className="table-wrap"><table className="table"><thead><tr><th>User</th><th>Role</th><th>Providers</th><th>Registered</th><th>Status</th></tr></thead><tbody>
    {ctx.isAdmin&&<tr><td><div className="user-cell"><Avatar name="API Admin" size={28}/><span>API key administrator<small>Local .env key</small></span></div></td><td>Administrator</td><td>API key</td><td>—</td><td><span className="badge badge-ok">Active</span></td></tr>}
    {ctx.isAdmin?dir?.items.map(u=><tr key={u.id}><td><div className="user-cell"><Avatar name={u.display_name} size={28}/><span>{u.display_name}<small>{u.email||'No email'}</small></span></div></td><td>User</td><td>{u.providers.join(', ')||'—'}</td><td className="muted">{asDate(u.created_at)}</td><td><span className={'badge '+(u.providers.length?'badge-ok':'badge-bad')}>{u.providers.length?'Active':'Inactive'}</span></td></tr>)
     :a?.user&&<tr><td><div className="user-cell"><Avatar name={a.user.name} src={a.user.avatar_url} size={28}/><span>{a.user.name}<small>{a.user.email||'No email'}</small></span></div></td><td>User</td><td>{a.identities.map(i=>i.provider).join(', ')}</td><td>—</td><td><span className="badge badge-ok">Active</span></td></tr>}
   </tbody></table></div>
   {!ctx.isAdmin&&<p className="muted small pad-x">Only API-key administrators can see the full user directory.</p>}
   {a?.authenticated&&<div className="pad-x link-providers"><h3 className="sub">Connected accounts</h3>{ctx.providers.map(p=>{const linked=a.identities.some(i=>i.provider===p.id);return <button key={p.id} className="btn btn-light" disabled={!p.enabled||linked} onClick={()=>{window.location.href='/api/auth/link/'+p.id}}>{linked?'✓ '+p.name+' linked':'Link '+p.name}</button>})}</div>}</>}
   {tab==='roles'&&<div className="pad roles"><div className="role"><b>Administrator</b><p>Authenticates with the server <code>API_KEY</code>. Sees every job, the user directory and may ingest stream URLs.</p></div><div className="role"><b>User</b><p>Signs in with Google, GitHub or Facebook OAuth. Sees and manages only their own jobs and media.</p></div></div>}
   {tab==='activity'&&<ul className="activity">{ctx.jobs.slice(0,15).map(j=><li key={j.id} onClick={()=>ctx.go('/job/'+j.id)}><Badge status={j.status}/><span><b>{baseName(j.filename)}</b><small>{shortId(j.id)} · {j.stage||j.status}</small></span><time>{asDate(j.updated_at||j.created_at)}</time></li>)}{!ctx.jobs.length&&<li className="muted">No activity yet.</li>}</ul>}
  </section>
 </>;
}

/* ---------- 11. System Health & Settings ---------- */
const svcName:Record<string,string>={api:'API Service',database:'Database (PostgreSQL)',redis:'Cache (Redis)',storage:'Storage (MinIO)',worker:'Worker (Celery)'};
export function SystemPage({ctx,initial='health',theme,setTheme,onSignOut}:{ctx:Ctx;initial?:'health'|'settings';theme:string;setTheme:(t:string)=>void;onSignOut:()=>void}){
 const [tab,setTab]=useState<'health'|'settings'>(initial);
 useEffect(()=>setTab(initial),[initial]);
 const s=ctx.system?.services||{};const h=ctx.system?.host;const hh=ctx.hostHistory;
 const pct=(u?:number|null,t?:number|null)=>u!=null&&t?Math.round(u*100/t):null;
 return <>
  <PageHead title={tab==='health'?'System Health':'Settings'} sub={tab==='health'?'Monitor system and service status':'Workspace, appearance and access'}><button className="btn btn-light" onClick={()=>void ctx.refresh()}><Icon name="refresh" size={15}/>Refresh</button></PageHead>
  <section className="card">
   <div className="toolbar"><Tabs variant="line" items={[['health','System Health'],['settings','Settings']]} value={tab} onChange={setTab}/></div>
   {tab==='health'?<div className="pad">
    <ul className="svc">{Object.keys(svcName).map(k=>{const v=s[k]||'unknown';return <li key={k}><span className={'svc-dot '+v}><Icon name={v==='online'?'check':v==='offline'?'x':'help'} size={13}/></span><b>{svcName[k]}</b><span className={'badge '+(v==='online'?'badge-ok':v==='offline'?'badge-bad':'badge-wait')}>{v==='online'?'Healthy':v==='offline'?'Offline':'Unknown'}</span></li>})}</ul>
    <div className="host-grid">
     <div className="host"><small>CPU (load)</small><Sparkline points={hh.cpu} color="var(--green)"/><b>{h?.cpu_percent!=null?h.cpu_percent+'%':'—'}</b></div>
     <div className="host"><small>Memory</small><Sparkline points={hh.mem} color="var(--primary)"/><b>{h?.memory_used_bytes!=null?size(h.memory_used_bytes)+' / '+size(h.memory_total_bytes):'—'}</b></div>
     <div className="host"><small>Disk</small><Sparkline points={hh.disk} color="var(--amber)"/><b>{h?.disk_used_bytes!=null?size(h.disk_used_bytes)+' / '+size(h.disk_total_bytes):'—'}</b>{pct(h?.disk_used_bytes,h?.disk_total_bytes)!=null&&<Progress value={pct(h?.disk_used_bytes,h?.disk_total_bytes)!}/>}</div>
    </div>
    <p className="muted small">Metrics are measured inside the API container. Worker ping can report "unknown" while it is busy.</p>
   </div>:<div className="pad settings">
    <div className="opt"><div><b>Processing mode</b><small>Set with MODEL_MODE on the server; restart API + worker to change.</small></div><span className={'mode-pill '+(isReal(ctx.models)?'real':'demo')}>{isReal(ctx.models)?'Real (offline AI)':'Demo'}</span></div>
    <div className="opt"><div><b>Khmer dubbing</b><small>ENABLE_KHMER_DUBBING · {ctx.models?.speech_dubbing_available?'TTS model installed':'TTS model not available'}</small></div><Toggle label="Khmer dubbing" checked={!!ctx.models?.khmer_dubbing_enabled} disabled/></div>
    <div className="opt"><div><b>Dark theme</b><small>Stored in this browser</small></div><Toggle label="Dark theme" checked={theme==='dark'} onChange={v=>setTheme(v?'dark':'light')}/></div>
    <div className="opt"><div><b>Signed in as</b><small>{ctx.account?.authenticated?ctx.account.user?.name+' (OAuth)':'API key administrator'}</small></div><button className="btn btn-light" onClick={onSignOut}><Icon name="logout" size={15}/>Sign out</button></div>
    <div className="opt"><div><b>API documentation</b><small>OpenAPI / Swagger UI</small></div><a className="btn btn-light" href="/api/docs" target="_blank" rel="noopener">Open</a></div>
   </div>}
  </section>
 </>;
}

export type {Status};
