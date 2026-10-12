"""Small real-provider HTTP probe on a verified copy of the existing runtime."""
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / 'data/docker-e2e'
    target = ROOT / 'data/stage-c' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    runtime = target / 'runtime'
    runtime.mkdir(parents=True)
    with closing(sqlite3.connect(source.joinpath('app.sqlite3').as_uri()+'?mode=ro', uri=True)) as db:
        with closing(sqlite3.connect(runtime / 'app.sqlite3')) as dest:
            db.backup(dest)
            originals = dest.execute('SELECT stored_name,content_hash FROM documents').fetchall()
    for directory in ('uploads', 'tokenizers'):
        if (source / directory).exists():
            shutil.copytree(source / directory, runtime / directory)
    # Artifact directories are immutable inputs of the existing retrieval modules.
    for directory in source.iterdir():
        if directory.is_dir() and directory.name not in ('uploads','tokenizers'):
            shutil.copytree(directory, runtime / directory.name)
    for name, expected in originals:
        assert (runtime / 'uploads' / name).resolve().parent == (runtime / 'uploads').resolve()
        assert sha256((runtime / 'uploads' / name).read_bytes()).hexdigest() == expected
    receipt = {'runtime':str(runtime),'originals_verified':len(originals),'checks':[]}
    env = os.environ.copy()
    env['DATA_DIR'] = str(runtime)
    env['PYTHONPATH'] = str(ROOT / 'backend')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port = sock.getsockname()[1]
    log = (target / 'server.log').open('w',encoding='utf-8')
    process = subprocess.Popen([sys.executable,'-m','uvicorn','app.main:create_app','--factory',
        '--host','127.0.0.1','--port',str(port)],cwd=ROOT,env=env,stdout=log,stderr=log,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=20) as client:
            for _ in range(100):
                try:
                    if client.get('/api/health').status_code == 200: break
                except httpx.TransportError: pass
                if process.poll() is not None: raise RuntimeError('Probe server exited; inspect local log')
                time.sleep(.2)
            def call(method,path,**kwargs):
                r=client.request(method,path,**kwargs);r.raise_for_status();return r.json()
            settings = call('GET','/api/settings')
            receipt['provider']=settings['generation']['provider']
            receipt['model']=settings['generation']['profiles'][receipt['provider']]['model']
            receipt['embedding']=settings['embedding']['model']
            sid=call('POST','/api/sessions')['session_id']; base=f'/api/sessions/{sid}'
            docs=call('GET','/api/documents')
            pdf=next(d for d in docs if d['status']=='ready' and d['original_filename'].endswith('.pdf'))
            version=call('GET','/api/document-versions/'+pdf['document_id'])
            source_ref={k:version[k] for k in ('document_id','version_id')}
            state=call('POST',base+'/sources',json={'source':source_ref,'expected_data_version':0})
            body={'request_id':'real-pdf-1','question':'What ingress protection rating is stated for the SITECO trunking system? Cite the PDF page and identify the product.',
                  'expected_data_version':state['data_version'],'expected_rule_version':state['rule_version']}
            run=call('POST',base+'/runs',json=body)
            assert call('POST',base+'/runs',json=body)['run_id']==run['run_id']
            for _ in range(300):
                run=call('GET',base+'/runs/'+run['run_id'])
                if run['status'] not in ('queued','running'): break
                time.sleep(1)
            receipt['run']=run
            assert run['status']=='completed', {'status':run['status'],'error':run.get('error')}
            answer=run['answer'];assert answer['citations'] and answer['segments']
            for citation in answer['citations']:
                assert citation['document_id']==pdf['document_id']
                assert citation['locator']['page_number']>=1
            receipt['checks'].append('real HTTP -> main graph -> PDF graph -> model/Voyage -> cited answer')
            public=call('GET',base+'/runs/'+run['run_id']+'/events')
            assert all(e['channel']=='user' for e in public)
            dev=call('GET',f'/api/developer/sessions/{sid}/runs/{run["run_id"]}/events')
            assert all(e['channel']=='developer' for e in dev)
            receipt['checks'].append('idempotent submission and separate user/developer event channels')
            receipt['session_id']=sid
            (target/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'receipt':str(target/'receipt.json'),'provider':receipt['provider'],
                              'checks':receipt['checks'],'citations':len(answer['citations'])}))
    finally:
        process.terminate()
        try: process.wait(10)
        except subprocess.TimeoutExpired: process.kill();process.wait()
        log.close()
        for name, expected in originals:
            assert sha256((source/'uploads'/name).read_bytes()).hexdigest()==expected
        (target/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__': main()
