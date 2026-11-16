import React,{useEffect,useRef,useState} from 'react';
import {Status,isFailed} from './api';

/* Icon paths follow the redesign (lucide-style 24px strokes). */
const P:Record<string,string>={
 dashboard:'M4 3h5a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zM15 3h5a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1h-5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zM15 12h5a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1h-5a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1zM4 16h5a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1z',
 translate:'M5 8l6 6M4 14l6-6 2-3M2 5h12M7 2h1M22 22l-5-10-5 10M14 18h6',
 jobs:'M12 12H3M16 6H3M12 18H3M16 12l5 3-5 3z',
 models:'M12 20v2M12 2v2M17 20v2M17 2v2M2 12h2M2 17h2M2 7h2M20 12h2M20 17h2M20 7h2M7 20v2M7 2v2M6 4h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zM9 8h6a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z',
 datasets:'M3 5a9 3 0 1 0 18 0 9 3 0 1 0-18 0M3 5v14a9 3 0 0 0 18 0V5M3 12a9 3 0 0 0 18 0',
 users:'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75',
 health:'M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2',
 settings:'M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z',
 search:'M11 3a8 8 0 1 0 0 16 8 8 0 0 0 0-16zM21 21l-4.3-4.3',
 collapse:'M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zM9 3v18M16 15l-3-3 3-3',
 expand:'M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zM9 3v18M14 9l3 3-3 3',
 help:'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zM9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01',
 bell:'M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.94 1.94 0 0 0 3.4 0',
 plus:'M12 5v14M5 12h14',
 link:'M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71',
 upload:'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12',
 download:'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3',
 check:'M20 6L9 17l-5-5',
 x:'M18 6L6 18M6 6l12 12',
 alert:'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zM12 8v4M12 16h.01',
 warn:'M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0zM12 9v4M12 17h.01',
 arrowR:'M5 12h14M12 5l7 7-7 7',
 refresh:'M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8M21 3v5h-5M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16M8 16H3v5',
 share:'M18 2a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM6 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM18 16a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM8.59 13.51l6.83 3.98M15.41 6.51l-6.82 3.98',
 eye:'M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z',
 list:'M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01',
 grid:'M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z',
 clock:'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zM12 6v6l4 2',
 file:'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M16 13H8M16 17H8',
 'chevron-down':'M6 9l6 6 6-6',
 'chevron-up':'M18 15l-6-6-6 6',
 trash:'M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6',
 video:'M15 10l4.55-2.28A1 1 0 0 1 21 8.62v6.76a1 1 0 0 1-1.45.9L15 14M5 6h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z',
 restore:'M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5',
 logout:'M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9',
 key:'M2.586 17.414A2 2 0 0 0 2 18.828V21a1 1 0 0 0 1 1h3a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h1a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h.172a2 2 0 0 0 1.414-.586l.814-.814a6.5 6.5 0 1 0-4-4zM16.5 7.5h.01',
 moon:'M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9z',
 sun:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41',
 menu:'M4 6h16M4 12h16M4 18h16',
};
export function Icon({name,size=18,className,stroke=1.8}:{name:string;size?:number;className?:string;stroke?:number}){
 if(name==='play')return <svg className={'icon '+(className||'')} width={size} height={size} viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.5-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z" fill="currentColor"/></svg>;
 return <svg className={'icon '+(className||'')} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={P[name]||''}/></svg>;
}

export function Logo({size=32}:{size?:number}){
 return <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" style={{flex:'none'}}><rect width="32" height="32" rx="9" fill="#1D4ED8"/><path d="M9.5 11.2v9.6a1.2 1.2 0 0 0 1.85 1l7.3-4.8a1.2 1.2 0 0 0 0-2l-7.3-4.8a1.2 1.2 0 0 0-1.85 1z" fill="#fff"/><path d="M21.2 12.6a4.6 4.6 0 0 1 0 6.8M24.2 9.8a8.6 8.6 0 0 1 0 12.4" stroke="#fff" strokeWidth="2" strokeLinecap="round" fill="none" opacity=".9"/></svg>;
}

export function Badge({status}:{status:Status}){
 const kind=status==='completed'?'ok':isFailed(status)?'bad':status==='queued'||status==='cancelled'?'muted':'run';
 const label=status==='dispatch_failed'?'Failed':status==='cancelling'?'Cancelling':status.charAt(0).toUpperCase()+status.slice(1);
 return <span className={'badge badge-'+kind}>{label}</span>;
}

export function Bar({value,kind}:{value:number;kind?:string}){
 return <div className="bar" role="progressbar" aria-valuenow={Math.round(value)} aria-valuemin={0} aria-valuemax={100}><i className={kind||''} style={{width:Math.max(0,Math.min(100,value))+'%'}}/></div>;
}

export function Avatar({name,src,size=36}:{name:string;src?:string|null;size?:number}){
 const initials=name.split(/\s+/).map(s=>s[0]).join('').slice(0,2).toUpperCase()||'U';
 return src?<img className="avatar" src={src} alt="" width={size} height={size} referrerPolicy="no-referrer"/>:<span className="avatar" style={{width:size,height:size,fontSize:size*0.36}} aria-hidden="true">{initials}</span>;
}

export function Seg<T extends string>({items,value,onChange,label}:{items:[T,React.ReactNode][];value:T;onChange:(v:T)=>void;label?:string}){
 return <div className="seg" role="tablist" aria-label={label}>{items.map(([id,l])=><button type="button" key={id} role="tab" aria-selected={value===id} className={value===id?'on':''} onClick={()=>onChange(id)}>{l}</button>)}</div>;
}

export function Card({title,extra,children,className,pad=true}:{title?:React.ReactNode;extra?:React.ReactNode;children:React.ReactNode;className?:string;pad?:boolean}){
 return <section className={'card'+(pad?' pad':'')+(className?' '+className:'')}>{(title||extra)&&<div className="card-h"><h2>{title}</h2>{extra}</div>}{children}</section>;
}

export function Thumb({label,dur}:{label?:string;dur?:string}){
 return <span className="thumb" aria-hidden="true">{label&&<b>{label}</b>}{dur&&<em>{dur}</em>}</span>;
}


/* ================= Confirm dialog =================
   confirmDialog({...}) returns Promise<boolean>. Mount <ConfirmHost/> once in the app shell. */
export type ConfirmTone='danger'|'warn'|'primary';
export type ConfirmOptions={title:string;message?:React.ReactNode;details?:React.ReactNode[];confirmLabel?:string;cancelLabel?:string;tone?:ConfirmTone;icon?:string};
let openConfirm:((o:ConfirmOptions)=>Promise<boolean>)|null=null;
export function confirmDialog(o:ConfirmOptions):Promise<boolean>{
 return openConfirm?openConfirm(o):Promise.resolve(window.confirm(o.title));
}
export function ConfirmHost(){
 const [req,setReq]=useState<(ConfirmOptions&{resolve:(v:boolean)=>void})|null>(null);
 const box=useRef<HTMLDivElement>(null),cancelBtn=useRef<HTMLButtonElement>(null),okBtn=useRef<HTMLButtonElement>(null);
 const returnFocus=useRef<HTMLElement|null>(null);
 useEffect(()=>{openConfirm=o=>new Promise(resolve=>{returnFocus.current=document.activeElement as HTMLElement;setReq({...o,resolve})});return()=>{openConfirm=null}},[]);
 const close=(v:boolean)=>{if(!req)return;req.resolve(v);setReq(null);setTimeout(()=>returnFocus.current?.focus?.(),0)};
 useEffect(()=>{
  if(!req)return;
  // Destructive: focus the safe choice first. Otherwise focus the action.
  (req.tone==='danger'?cancelBtn:okBtn).current?.focus();
  const onKey=(e:KeyboardEvent)=>{
   if(e.key==='Escape'){e.preventDefault();close(false)}
   if(e.key==='Tab'&&box.current){
    const f=Array.from(box.current.querySelectorAll<HTMLElement>('button'));if(!f.length)return;
    const i=f.indexOf(document.activeElement as HTMLElement);
    if(e.shiftKey&&i<=0){e.preventDefault();f[f.length-1].focus()}else if(!e.shiftKey&&i===f.length-1){e.preventDefault();f[0].focus()}
   }
  };
  document.addEventListener('keydown',onKey);const prev=document.body.style.overflow;document.body.style.overflow='hidden';
  return()=>{document.removeEventListener('keydown',onKey);document.body.style.overflow=prev};
 },[req]);
 if(!req)return null;
 const tone=req.tone||'primary';
 const icon=req.icon||(tone==='danger'?'trash':tone==='warn'?'warn':'alert');
 return <div className="dlg-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)close(false)}}>
  <div ref={box} className={'dlg dlg-'+tone} role="alertdialog" aria-modal="true" aria-labelledby="dlg-title" aria-describedby={req.message?'dlg-msg':undefined}>
   <div className="dlg-head"><span className="dlg-icon"><Icon name={icon} size={22}/></span><h2 id="dlg-title">{req.title}</h2></div>
   {req.message&&<div id="dlg-msg" className="dlg-msg">{req.message}</div>}
   {req.details&&req.details.length>0&&<ul className="dlg-details">{req.details.map((d,i)=><li key={i}>{d}</li>)}</ul>}
   <div className="dlg-actions">
    <button ref={cancelBtn} className="btn btn-outline" onClick={()=>close(false)}>{req.cancelLabel||'Cancel'}</button>
    <button ref={okBtn} className={'btn '+(tone==='danger'?'btn-danger':'btn-primary')} onClick={()=>close(true)}>{req.confirmLabel||'Confirm'}</button>
   </div>
  </div>
 </div>;
}
