import sys,json,time
from pathlib import Path
from io import BytesIO
sys.path.insert(0,str(Path('backend').resolve()))
from app.documents import DocumentService,DocumentError
from app.processing import DocumentProcessor
from app.questions import QuestionTools
import argparse
parser=argparse.ArgumentParser(description='Offline reproduction of M5 sentence-final order validation; zero provider calls')
parser.add_argument('--runtime',type=Path,required=True)
args=parser.parse_args()
root=args.runtime; root.mkdir(parents=True,exist_ok=False)
s=DocumentService(root); s.start(DocumentProcessor()); results=[]
try:
 p=Path('data/Price Lists/leuchten_siteco_LPR_2026_06.csv'); d=s.submit(p.name,BytesIO(p.read_bytes()))
 while d['status'] not in ('ready','failed'):
  time.sleep(.1); d=s.get(d['document_id'])
 assert d['status']=='ready'
 tools=QuestionTools(s,None)
 ids=['51DB11EC11B1D','51DB11EC11D1D']
 plan={'tools':[{'tool':'lookup_orders','document_ids':[d['document_id']],'order_ids':ids}]}
 base='Vergleiche Preis und EAN von 51DB11EC11B1D und 51DB11EC11D1D'
 for ending in ['.','?','',',']:
  try:
   r=tools.prepare({'conversation_id':'offline-repro','document_ids':[d['document_id']],'question':base+ending},planner=lambda *a:plan)
   results.append({'ending':ending,'status':'ok','total':r['tools'][0]['result']['total']})
  except DocumentError as exc: results.append({'ending':ending,'status':'failed','code':exc.code})
finally:s.stop()
print(json.dumps(results,ensure_ascii=False,indent=2))
assert results[0]['status']=='failed' and all(x['total']==2 for x in results[1:])
