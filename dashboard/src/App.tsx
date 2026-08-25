import React, {useEffect, useState} from 'react'

type Status = {
  running: boolean
  last_scan: number | null
  open_trades: any[]
  balance: number
  paper_mode: string
  scan_interval: number
}

export default function App(){
  const [status, setStatus] = useState<Status | null>(null)
  const [logs, setLogs] = useState<string[]>([])
  const [token, setToken] = useState<string | null>(sessionStorage.getItem('DASH_TOKEN'))

  useEffect(()=>{ fetchStatus(); fetchLogs(); const es = new EventSource('/api/events'); es.onmessage = (e)=>{ try{ const d=JSON.parse(e.data); if(d.type==='status') setStatus(d.payload); if(d.type==='log') setLogs(prev=>[d.payload,...prev].slice(0,200)); }catch(e){} }; return ()=>es.close(); },[])

  async function fetchStatus(){ const r = await fetch('/api/status'); if(r.ok) setStatus(await r.json()); }
  async function fetchLogs(){ const r = await fetch('/api/logs?limit=50'); if(r.ok) setLogs((await r.json()).reverse()); }
  async function control(action:string){ const headers:any = {'Content-Type':'application/json'}; if(token) headers['x-dashboard-token']=token; const r = await fetch('/api/control',{method:'POST',headers,body:JSON.stringify({action})}); const j = await r.json(); if(!r.ok) alert(JSON.stringify(j)); else fetchStatus(); }

  function login(){ sessionStorage.setItem('DASH_TOKEN', token||''); location.reload(); }

  return (
    <div className="container">
      <h1>Crypto Paper Bot - Dashboard</h1>
      {!token && <div className="card"><h3>Enter dashboard token</h3><input value={token||''} onChange={e=>setToken(e.target.value)} /><button onClick={login}>Save</button></div>}
      <div className="card">
        <h3>Status</h3>
        {status ? (
          <div>
            <p>Running: {String(status.running)}</p>
            <p>Balance: ${status.balance.toFixed(2)}</p>
            <p>Last scan: {status.last_scan?new Date(status.last_scan*1000).toLocaleString():'-'}</p>
            <p>Open trades: {status.open_trades.length}</p>
            <p>Paper mode: {status.paper_mode}</p>
            <p>Scan interval: {status.scan_interval}s</p>
            <div className="buttons">
              <button onClick={()=>control('resume')}>Resume</button>
              <button onClick={()=>control('pause')}>Pause</button>
              <button onClick={()=>control('force_scan')}>Force Scan</button>
              <button onClick={()=>control('toggle_paper')}>Toggle Paper</button>
            </div>
          </div>
        ) : (<p>loading...</p>)}
      </div>

      <div className="card">
        <h3>Logs (recent)</h3>
        <div className="logs">
          {logs.map((l,i)=>(<div key={i} className="log-line">{l}</div>))}
        </div>
        <button onClick={fetchLogs}>Refresh Logs</button>
      </div>
    </div>
  )
}
