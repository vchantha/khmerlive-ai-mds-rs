export type Status='queued'|'processing'|'cancelling'|'cancelled'|'completed'|'failed'|'dispatch_failed';
export type Job={id:string;filename:string;size_bytes:number;source_kind?:'upload'|'url'|'youtube';capture_seconds?:number|null;status:Status;progress:number;stage:string|null;source_lang:string;target_lang:string;created_at:string|null;updated_at?:string|null;error:string|null;has_output:boolean;has_subtitles?:boolean;has_khmer_voice?:boolean;processing_mode?:'demo'|'real_subtitles';cancel_requested:boolean;transcript:string|null;translation:string|null};
export type Metrics={total:number;queued:number;processing:number;completed:number;failed:number};
export type ModelInfo={mode:string;subtitle_translation_configured:boolean;speech_dubbing_available:boolean;khmer_dubbing_enabled?:boolean;note?:string;installed?:Record<string,{id:string;license:string;revision:string}>;max_video_duration_seconds?:number;youtube_enabled?:boolean;llm?:LLMInfo};
export type LLMInfo={enabled:boolean;provider:string;model:string;endpoint:string;server:'online'|'offline'|'unknown';model_available:boolean|null;available_models:string[];status:'off'|'ready'|'model_missing'|'offline'|'misconfigured';detail:string|null;processor?:'gpu'|'cpu'|'split'|'idle'|null;gpu_percent?:number|null};
export type JobEvent={id:number;at:string|null;stage:string;level:'info'|'warning'|'error';message:string;seconds:number|null;data:Record<string,unknown>|null};
export type Segment={index:number;start_ms:number;end_ms:number;source:string;machine:string|null;llm:string|null;final:string;corrected:string|null;approved_unchanged:boolean};
export type CorrectionSummary={pairs:number;edited:number;approved_unchanged:number;jobs:number;by_language_pair:Record<string,number>;recommended_minimum:number};
export type GlossaryItem={id:number;source_term:string;target_term:string;note:string|null;source_lang:string;target_lang:string;created_by:string|null;created_at:string|null};
export type MediaItem={id:string;filename:string;size_bytes:number;source_kind:'upload'|'url'|'youtube';source_url:string|null;capture_seconds:number|null;created_at:string|null;jobs:number;active:number;completed:number};
export type TrashItem={kind:'job'|'video';id:string;filename:string;source_kind:string;size_bytes:number;status:Status|null;jobs:number|null;media_id:string;owner_user_id:string|null;owner_name:string|null;deleted_by:string|null;deleted_by_name:string|null;deleted_at:string|null};
export type YouTubeInfo={id:string;title?:string;duration?:number;uploader?:string;height?:number;is_live?:boolean;thumbnail?:string;trimmed_to_seconds?:number|null};
export type Host={cpu_percent:number|null;memory_used_bytes:number|null;memory_total_bytes:number|null;disk_used_bytes:number|null;disk_total_bytes:number|null};
export type SystemData={services:Record<string,string>;latency_ms?:Record<string,number>;mode?:string;host?:Host};
export type Account={authenticated:boolean;user:{id:string;name:string;email:string|null;avatar_url:string|null}|null;identities:{provider:string;display_name:string|null}[]};
export type Provider={id:string;name:string;enabled:boolean};
export type DirectoryUser={id:string;display_name:string;email:string|null;created_at:string|null;providers:string[]};

const KEY='khmerlive_api_key';
export const storedKey=()=>{try{return sessionStorage.getItem(KEY)||localStorage.getItem(KEY)||''}catch{return ''}};
export const saveKey=(k:string,remember:boolean)=>{try{sessionStorage.setItem(KEY,k);if(remember)localStorage.setItem(KEY,k);else localStorage.removeItem(KEY)}catch{}};
export const clearKey=()=>{try{sessionStorage.removeItem(KEY);localStorage.removeItem(KEY)}catch{}};

let apiKey=storedKey();
export const setApiKey=(k:string)=>{apiKey=k};
export const getApiKey=()=>apiKey;

export async function req<T>(path:string,options:RequestInit={}):Promise<T>{
 const headers:Record<string,string>={...(options.headers as Record<string,string>||{})};
 if(apiKey)headers['X-API-Key']=apiKey;
 const r=await fetch(path,{...options,headers});
 if(!r.ok){let message=await r.text();try{message=JSON.parse(message).detail||message}catch{}throw new Error(r.status+': '+String(message).slice(0,240))}
 return await r.json() as T;
}

export function uploadMedia(file:File,onProgress:(pct:number)=>void):Promise<{media_id:string}>{
 return new Promise((resolve,reject)=>{
  const x=new XMLHttpRequest();x.open('POST','/api/media');if(apiKey)x.setRequestHeader('X-API-Key',apiKey);
  x.upload.onprogress=e=>{if(e.lengthComputable)onProgress(Math.round(e.loaded*100/e.total))};
  x.onerror=()=>reject(new Error('Network error while uploading video'));
  x.onload=()=>{if(x.status<200||x.status>=300){let m=x.responseText;try{m=JSON.parse(m).detail||m}catch{}reject(new Error('Upload failed '+x.status+': '+String(m).slice(0,180)));return}try{resolve(JSON.parse(x.responseText))}catch{reject(new Error('Unexpected upload response'))}};
  const d=new FormData();d.append('file',file);x.send(d);
 });
}

export async function downloadBlob(path:string,name:string){
 const headers:Record<string,string>={};if(apiKey)headers['X-API-Key']=apiKey;
 const r=await fetch(path,{headers});if(!r.ok)throw new Error('Download unavailable: '+r.status);
 saveBlob(await r.blob(),name);
}
export function saveBlob(blob:Blob,name:string){const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000)}

export async function downloadVideo(j:Job){
 // Stream straight from the S3 proxy instead of buffering a large MP4 in a Blob.
 const p=await req<{video_url:string}>('/api/jobs/'+j.id+'/player-token');
 const a=document.createElement('a');a.href=p.video_url+'&download=1';a.download=baseName(j.filename)+'-translated.mp4';document.body.appendChild(a);a.click();a.remove();
}

export const baseName=(n:string)=>n.replace(/\.mp4$/i,'');
export const shortId=(id:string)=>'KH-'+id.slice(0,6).toUpperCase();
export const asDate=(s:string|null|undefined)=>s?new Date(s).toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}):'—';
export const asTime=(d:Date)=>d.toLocaleTimeString(undefined,{hour12:false});
export const size=(n:number|null|undefined)=>n==null?'—':n>=1073741824?(n/1073741824).toFixed(1)+' GB':n>=1048576?(n/1048576).toFixed(1)+' MB':Math.max(1,Math.ceil(n/1024))+' KB';
export const lang=(c:string)=>c==='km'?'Khmer':'English';
export const isActive=(s:Status)=>s==='queued'||s==='processing'||s==='cancelling';
export const isFailed=(s:Status)=>s==='failed'||s==='dispatch_failed';
export const statusLabel=(s:Status)=>s==='dispatch_failed'?'Failed':s.charAt(0).toUpperCase()+s.slice(1);
export const isYouTubeUrl=(u:string)=>{try{const h=new URL(u.trim()).hostname.toLowerCase();return ['youtube.com','www.youtube.com','m.youtube.com','music.youtube.com','youtu.be','www.youtube-nocookie.com','youtube-nocookie.com'].includes(h)}catch{return false}};
export const sourceLabel=(k?:string,trimmed?:number|null)=>k==='youtube'?(trimmed?'YouTube (first '+Math.round(trimmed/60)+' min)':'YouTube'):k==='url'?'Stream URL':'Upload';
export const fmtDur=(sec?:number|null)=>{if(sec==null||!isFinite(sec))return '—';const s=Math.round(sec),h=Math.floor(s/3600),m=Math.floor(s%3600/60),r=s%60;return (h?h+':'+String(m).padStart(2,'0'):String(m))+':'+String(r).padStart(2,'0')};
export const timeLeft=(j:Job)=>{if(!j.created_at||j.progress<8||!isActive(j.status))return '';const el=(Date.now()-new Date(j.created_at).getTime())/1000;const rem=el*(100-j.progress)/j.progress;return rem<60?'under a minute left':'about '+Math.round(rem/60)+' min left'};
export const outputsLabel=(j:Job)=>j.has_khmer_voice?'Dubbed + SRT':j.has_subtitles?'Subtitles':j.processing_mode==='demo'?'Demo':isActive(j.status)?(j.target_lang==='km'&&j.processing_mode==='real_subtitles'?'Dubbing + SRT':'Subtitles'):'—';
