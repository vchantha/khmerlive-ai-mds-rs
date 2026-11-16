import React from 'react';
import {Status,statusLabel,isFailed} from './api';

const paths:Record<string,React.ReactNode>={
 home:<><path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/></>,
 plus:<><circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/></>,
 jobs:<><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8 9h8M8 13h8M8 17h5"/></>,
 library:<><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M10 9l5 3-5 3z"/></>,
 models:<><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/></>,
 datasets:<><ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/></>,
 users:<><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.8-3.5 3.4-5.5 6.5-5.5s5.7 2 6.5 5.5"/><circle cx="17" cy="9" r="2.5"/><path d="M17 14.5c2.3 0 4 1.5 4.5 4"/></>,
 health:<><path d="M3 12h4l2-5 4 10 2-5h6"/></>,
 settings:<><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.6 1.6 0 00-2.7 1.1V21a2 2 0 11-4 0v-.1A1.6 1.6 0 006.6 19.4l-.1.1a2 2 0 11-2.8-2.8l.1-.1A1.6 1.6 0 002.6 14H2.5a2 2 0 110-4h.1A1.6 1.6 0 004.6 6.6l-.1-.1a2 2 0 112.8-2.8l.1.1A1.6 1.6 0 0010 2.6V2.5a2 2 0 114 0v.1a1.6 1.6 0 002.7 1.1l.1-.1a2 2 0 112.8 2.8l-.1.1a1.6 1.6 0 001.1 2.7h.1a2 2 0 110 4h-.1a1.6 1.6 0 00-1.2.8z"/></>,
 bell:<><path d="M18 16V11a6 6 0 10-12 0v5l-2 2h16z"/><path d="M10 20a2 2 0 004 0"/></>,
 help:<><circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 014.6 1.3c0 1.7-2.1 2-2.1 3.7M12 17.5v.01"/></>,
 calendar:<><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></>,
 upload:<><path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v4h16v-4"/></>,
 cloud:<><path d="M7 18a5 5 0 01-.6-10A6 6 0 0118 9a4.5 4.5 0 01-.5 9z"/><path d="M12 11v7M9 14l3-3 3 3"/></>,
 link:<><path d="M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1"/></>,
 check:<path d="M5 12l4 4 10-10"/>,
 x:<path d="M6 6l12 12M18 6L6 18"/>,
 arrowR:<path d="M5 12h14M13 6l6 6-6 6"/>,
 arrowL:<path d="M19 12H5M11 6l-6 6 6 6"/>,
 swap:<path d="M7 7h12l-3-3M17 17H5l3 3"/>,
 play:<path d="M8 5l11 7-11 7z" fill="currentColor"/>,
 download:<><path d="M12 4v11M7 10l5 5 5-5"/><path d="M4 19h16"/></>,
 share:<><circle cx="18" cy="5" r="2.5"/><circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="19" r="2.5"/><path d="M8.2 10.8l7.6-4.5M8.2 13.2l7.6 4.5"/></>,
 file:<><path d="M14 3H6v18h12V7z"/><path d="M14 3v4h4M9 13h6M9 17h6"/></>,
 search:<><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></>,
 filter:<path d="M4 5h16l-6 8v6l-4-2v-4z"/>,
 grid:<><rect x="4" y="4" width="7" height="7" rx="1"/><rect x="13" y="4" width="7" height="7" rx="1"/><rect x="4" y="13" width="7" height="7" rx="1"/><rect x="13" y="13" width="7" height="7" rx="1"/></>,
 list:<path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"/>,
 eye:<><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></>,
 layers:<><path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/></>,
 logout:<><path d="M15 4h4v16h-4M10 8l-4 4 4 4M6 12h11"/></>,
 key:<><circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M17 6l3 3"/></>,
 menu:<path d="M4 6h16M4 12h16M4 18h16"/>,
 refresh:<><path d="M20 11a8 8 0 10-2.3 5.7"/><path d="M20 4v7h-7"/></>,
 dots:<path d="M12 5h.01M12 12h.01M12 19h.01" strokeWidth="3"/>,
 server:<><rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01"/></>,
 mic:<><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0014 0M12 18v3"/></>,
 translate:<><path d="M3 5h10M8 3v2M5 5c1 4 4 7 7 8M11 5c-1 4-4 7-7 8"/><path d="M13 21l4-9 4 9M14.5 18h5"/></>,
 voice:<><path d="M4 10v4M8 7v10M12 4v16M16 8v8M20 11v2"/></>,
 sun:<><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></>,
 moon:<path d="M20 14.5A8 8 0 019.5 4 8 8 0 1020 14.5z"/>,
};
export function Icon({name,size=18,className}:{name:string;size?:number;className?:string}){
 return <svg className={'icon '+(className||'')} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

export function Logo({size=34}:{size?:number}){
 return <span className="logo" style={{width:size,height:size}} aria-hidden="true"><svg viewBox="0 0 32 32" width={size*0.62} height={size*0.62} fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M5 9l7 7-7 7M27 9l-7 7 7 7M12 16h8"/></svg></span>;
}

export function Badge({status}:{status:Status}){
 const kind=status==='completed'?'ok':isFailed(status)?'bad':status==='cancelled'?'muted':status==='queued'?'wait':'run';
 return <span className={'badge badge-'+kind}>{statusLabel(status)}</span>;
}

export function Toggle({checked,disabled,onChange,label}:{checked:boolean;disabled?:boolean;onChange?:(v:boolean)=>void;label:string}){
 return <button type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled} className={'toggle'+(checked?' on':'')} onClick={()=>onChange?.(!checked)}><i/></button>;
}

export function Progress({value,kind}:{value:number;kind?:string}){
 return <div className="bar"><i className={kind||''} style={{width:Math.max(0,Math.min(100,value))+'%'}}/></div>;
}

export function Avatar({name,src,size=34}:{name:string;src?:string|null;size?:number}){
 const initials=name.split(/\s+/).map(s=>s[0]).join('').slice(0,2).toUpperCase()||'U';
 return src?<img className="avatar" src={src} alt="" width={size} height={size} referrerPolicy="no-referrer"/>:<span className="avatar" style={{width:size,height:size,fontSize:size*0.38}} aria-hidden="true">{initials}</span>;
}

export function Tabs<T extends string>({items,value,onChange,variant='pill'}:{items:[T,string][];value:T;onChange:(v:T)=>void;variant?:'pill'|'line'}){
 return <div className={'tabs tabs-'+variant} role="tablist">{items.map(([id,l])=><button key={id} role="tab" aria-selected={value===id} className={value===id?'active':''} onClick={()=>onChange(id)}>{l}</button>)}</div>;
}

export function Sparkline({points,color='currentColor'}:{points:number[];color?:string}){
 if(points.length<2)return <svg className="spark" viewBox="0 0 100 30"/>;
 const max=Math.max(...points,1);
 const d=points.map((v,i)=>(i?'L':'M')+(i*100/(points.length-1)).toFixed(1)+','+(28-v*26/max).toFixed(1)).join(' ');
 return <svg className="spark" viewBox="0 0 100 30" preserveAspectRatio="none"><path d={d} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke"/></svg>;
}
