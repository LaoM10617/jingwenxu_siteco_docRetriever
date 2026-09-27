"""Offline arithmetic and presentation from reviewed M5 judgments; no provider imports."""
import argparse
import csv
from datetime import datetime
from hashlib import sha256
from html import escape
import json
from pathlib import Path
from statistics import mean, median


def read_lines(path):
    return [json.loads(line) for line in path.read_text('utf-8').splitlines() if line.strip()]


def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def main(root):
    spec=json.loads((root/'cases.json').read_text('utf-8')); cases={c['id']:c for c in spec['cases']}
    meta=json.loads((root/'manifest.json').read_text('utf-8')); review=json.loads((root/'review.json').read_text('utf-8'))
    answers={r['case']:r for r in read_lines(root/'answers.jsonl')}
    retrieval=read_lines(root/'retrieval.jsonl'); scored=[]
    for record in retrieval:
        if record['arm'] not in ['fixed','rerank']: continue
        cid=record['case']; case=cases[cid]
        arms=record['arms'] if record['arm']=='fixed' else {'rerank':record}
        for arm,value in arms.items():
            rows=value['records']; contexts=[e['source'] for e in value['context']['evidence']]
            units=[]
            for unit in case['pdf_evidence_units']:
                accepted=review['evidence_mappings'][unit['id']]['accepted_evidence_ids']
                ranks=[i for i,r in enumerate(rows,1) if r['evidence_id'] in accepted]
                units.append({'unit':unit['id'],'hit':bool(ranks),'rank':min(ranks) if ranks else None,
                              'context_hit':any(r['evidence_id'] in accepted for r in contexts)})
            ranks=[u['rank'] for u in units if u['rank']]
            scored.append({'type':'retrieval','case':cid,'split':case['split'],'arm':arm,'units':units,
                           'recall':sum(u['hit'] for u in units)/len(units),'complete':all(u['hit'] for u in units),
                           'mrr':1/min(ranks) if ranks else 0,'context_recall':sum(u['context_hit'] for u in units)/len(units),
                           'context_complete':all(u['context_hit'] for u in units)})
    for row in review['answers']:
        raw=answers[row['case']]; task=raw.get('task',{})
        assert [f['id'] for f in row['facts']]==[f['id'] for f in cases[row['case']]['required_facts']]
        scored.append({'type':'answer',**row,'status':task.get('status',raw.get('status')),'seconds':raw.get('seconds')})
    (root/'scores.jsonl').write_text(''.join(json.dumps(s,ensure_ascii=False)+'\n' for s in scored),encoding='utf-8')
    summary={'run_id':root.name,'product_commit':meta['product_commit'],'evaluation_commit':meta['head'],
             'run_status':meta['status'],'counts':meta['counts'],'total_attempts':sum(meta['counts'].values()),
             'elapsed_seconds':(datetime.fromisoformat(meta['finished_utc'])-datetime.fromisoformat(meta['started_utc'])).total_seconds(),
             'reserved_cost_usd':meta['reserved_cost_usd'],'actual_invoice_usd':None,
             'retrieval':{},'answers':{},'C':'not authorized; no Groq calls','limitations':['small correlated set','assistant source review, not independent human double review','provider aliases/default randomness','backend timing, not browser latency']}
    for group,predicate in [('all',lambda s:True),('development',lambda s:s=='development'),('holdout_document',lambda s:s=='holdout_document'),('holdout_same_file',lambda s:s=='holdout_same_file')]:
        a=[s for s in scored if s['type']=='answer' and predicate(s['split'])]
        facts=[f for s in a for f in s['facts']]
        times=[s['seconds'] for s in a if s['seconds'] is not None]
        summary['answers'][group]={'turns':len(a),'completed':sum(s['status']=='completed' for s in a),'failed':sum(s['status']=='failed' for s in a),
            'dependent_blocked':sum(s['status']=='dependent_blocked' for s in a),'strict_pass':sum(s['strict_pass'] for s in a),
            'facts_correct':sum(f['correct'] for f in facts),'facts_cited':sum(f['correct'] and f['cited'] for f in facts),'facts_required':len(facts),
            'observed_turns':len(times),'median_seconds_including_failures':median(times) if times else None,
            'completed_median_seconds':median([s['seconds'] for s in a if s['status']=='completed']) if any(s['status']=='completed' for s in a) else None}
        summary['retrieval'][group]={}
        for arm in ['lexical','vector','rrf','rerank']:
            r=[s for s in scored if s['type']=='retrieval' and s['arm']==arm and predicate(s['split'])]
            if not r: continue
            units=[u for s in r for u in s['units']]
            summary['retrieval'][group][arm]={'questions':len(r),'units_required':len(units),'units_hit':sum(u['hit'] for u in units),
             'macro_recall':mean(s['recall'] for s in r),'micro_recall':sum(u['hit'] for u in units)/len(units),
             'complete_questions':sum(s['complete'] for s in r),'mrr':mean(s['mrr'] for s in r),
             'context_units_hit':sum(u['context_hit'] for u in units),'context_complete_questions':sum(s['context_complete'] for s in r)}
    positive=[]
    generation=read_lines(root/'generation.jsonl')
    for cid,case in cases.items():
        if not case['csv_expected_records']: continue
        bundles=[r['payload']['bundle'] for r in generation if r['event']=='request' and r['case']==cid and r['payload']['phase']=='answer']
        sources=[e['source'] for bundle in bundles for e in bundle['evidence'] if e['source']['locator']['kind']=='csv']
        observed={(v['document_id'],v['locator']['record_number']) for v in sources}
        expected={(meta['documents']['prices'],r) for r in case['csv_expected_records']}
        hit=len(observed & expected)
        positive.append({'case':cid,'status':'observed_context' if bundles else 'lookup_not_observed',
                         'expected_count':len(expected),'returned_count':len(observed),'hits':hit,
                         'precision':hit/len(observed) if observed else 0,'recall':hit/len(expected)})
    misses=[r for r in review['answers'] if cases[r['case']]['csv_expected_records']==[]]
    returned=sum(r['returned_count'] for r in positive); hits=sum(r['hits'] for r in positive)
    summary['csv']={'positive_cases':positive,'positive_macro_precision':mean(r['precision'] for r in positive),
                    'positive_macro_recall':mean(r['recall'] for r in positive),'positive_micro_precision':hits/returned if returned else None,
                    'positive_micro_recall_numerator':hits,'positive_micro_recall_denominator':sum(r['expected_count'] for r in positive),
                    'micro_precision_note':'No returned records means undefined denominator; failures remain in macro metrics. Positive sets use recorded pre-answer evidence context; report pagination/omission if present.',
                    'exact_miss_correct':sum(bool(r['negative_behavior_pass']) for r in misses),'exact_miss_total':len(misses),
                    'exact_miss_executed':sum(any(t['tool']=='lookup_orders' for t in ((answers[r['case']].get('task',{}).get('answer') or {}).get('tool_results',[]))) for r in misses),
                    'duplicate_source_preservation':None}
    pairs=review['claim_citation_pairs']
    summary['citation_support']={'supported_pairs':sum(x['supported'] for x in pairs),'total_pairs':len(pairs),
                                 'uncited_false_claims':review['uncited_false_claims']}
    summary['followups']={'correct_reference':0,'scope_pass':0,'fixed_denominator':2,'executed':0,'reason':'Dependent on failed E03; not an observed model reference error.'}
    events=[r for r in read_lines(root/'attempts.jsonl') if r['status']!='started']
    assert len(events)==sum(meta['counts'].values())
    usage=[r['usage'] for r in read_lines(root/'generation.jsonl') if r['event']=='response' and r.get('usage')]
    prompt=sum(u.get('promptTokenCount',0) for u in usage)
    output=sum(u.get('candidatesTokenCount',0)+u.get('thoughtsTokenCount',0) for u in usage)
    emb=sum(e.get('usage_tokens') or 0 for e in events if e['kind'] in ['document','query'])
    rer=sum(e.get('usage_tokens') or 0 for e in events if e['kind']=='rerank')
    summary['usage']={'gemini_successful_responses_with_usage':len(usage),'gemini_input_tokens':prompt,'gemini_output_and_thinking_tokens':output,
                      'embedding_tokens':emb,'rerank_tokens':rer,'failed_generation_usage_unknown':sum(e['kind']=='generation' and e['status']=='failed' for e in events),
                      'known_usage_list_price_usd':(prompt*.30+output*2.50+emb*.06+rer*.02)/1e6,
                      'note':'Known successful usage at protocol list prices, excludes unknown failed-call billing; not invoice.'}
    summary['rerank']={'successful':sum(e['kind']=='rerank' and e['status']=='ok' for e in events),'planned':7,
                      'median_provider_seconds':median(e['seconds'] for e in events if e['kind']=='rerank')}
    summary['artifact_hashes']={p.name:sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.suffix in ['.jsonl'] or p.name in ['review.json','cases.json','protocol.md','manifest.json']}
    save(root/'summary.json',summary)
    with (root/'summary.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f); w.writerow(['category','group','arm','metric','numerator_or_value','denominator'])
        for group,arms in summary['retrieval'].items():
            for arm,r in arms.items():
                for metric,num,den in [('evidence_micro_recall',r['units_hit'],r['units_required']),('complete_at_8',r['complete_questions'],r['questions']),('macro_recall',r['macro_recall'],1),('mrr_at_8',r['mrr'],1)]:w.writerow(['retrieval',group,arm,metric,num,den])
        for group,a in summary['answers'].items():
            for metric,num,den in [('strict_pass',a['strict_pass'],a['turns']),('fact_coverage',a['facts_correct'],a['facts_required']),('cited_fact_coverage',a['facts_cited'],a['facts_required'])]:w.writerow(['answer',group,'gemini',metric,num,den])
        w.writerow(['csv','all','exact','positive_micro_recall',hits,summary['csv']['positive_micro_recall_denominator']]);w.writerow(['csv','all','exact','exact_miss_correct',summary['csv']['exact_miss_correct'],summary['csv']['exact_miss_total']])
    render(root,summary,scored,cases,answers)
    print(json.dumps({'strict_pass':summary['answers']['all']['strict_pass'],'facts':summary['answers']['all']['facts_correct'], 'attempts':summary['total_attempts'],'known_usage_usd':summary['usage']['known_usage_list_price_usd']}))


def render(root,s,scored,cases,answers):
    a=s['answers']['all']
    lines=['# M5.0 evaluation: first frozen A+B run','',f"Product `{s['product_commit'][:7]}`; evaluation `{s['evaluation_commit'][:7]}`. Run `{s['run_id']}`.",'',
           f"A+B execution completed in {s['elapsed_seconds']:.1f} seconds using {s['total_attempts']} provider attempts. C was not authorized and did not run.",'',
           f"Strict pass: {a['strict_pass']}/{a['turns']}; required facts and supported cited facts: {a['facts_correct']}/{a['facts_required']}. Completed tasks: {a['completed']}; failed tasks: {a['failed']}; dependent blocked turns: {a['dependent_blocked']}.",'',
           '## Retrieval comparison','']
    for arm,r in s['retrieval']['all'].items():lines.append(f"- {arm}: evidence {r['units_hit']}/{r['units_required']}; macro recall {r['macro_recall']:.4f}; complete {r['complete_questions']}/{r['questions']}; MRR@8 {r['mrr']:.4f}; post-context evidence {r['context_units_hit']}/{r['units_required']}.")
    lines+=['','Vector-only covers all required evidence in this small fixed set. Reranking improves RRF evidence coverage on E02 but still misses its general-applications heading; complete-question count does not improve. This is retrieval evidence, not a reranked-answer experiment. No production setting was changed.','',
            '## First-result failures and scoring','']
    for row in [x for x in scored if x['type']=='answer']:
        lines += [f"- {row['case']}: {row['status']}; facts {sum(f['correct'] for f in row['facts'])}/{len(row['facts'])}; strict {'pass' if row['strict_pass'] else 'fail'}. {row['reason']}"]
    lines+=['','## Interpretation and limits','',
    'E07 and E12 expose a deterministic literal-boundary defect: the correct final order ID is rejected when followed by a sentence-ending period. An isolated real-CSV QuestionTools replay succeeds with a question mark, comma or no punctuation, with zero provider calls. This is a blocker candidate, not a supplier/model failure. Product repair and affected reruns require an explicit freeze exception and a new call budget; first results remain unchanged.',
    '', 'E01 omits required conditions despite correct evidence. E02 combines retrieval omissions with a false attribution/absence statement. E11 answers the direct silver-only question correctly but misses the rubric-required enumeration of all housing colours; report this as rubric completeness, not a wrong yes/no answer.',
    '', 'E03/E06 are timeout-like 60-second provider-unavailable events. The remote cause is unproven. E04/E05 were not executed, so this run provides no direct observation of multi-turn behavior. CSV positive lookups never executed successfully: fixed-denominator recall is 0/5, but this is not evidence that the exact CSV index returned wrong rows. Two of three fixed exact-miss cases pass; the third was dependent-blocked.',
    '',f"Citation-pair support is {s['citation_support']['supported_pairs']}/{s['citation_support']['total_pairs']}. This excludes uncited gaps from its denominator; E02 also contains an explicit false gap statement. Required-fact citation coverage is separately {a['facts_cited']}/{a['facts_required']}.",
    '',f"Observed backend turns: {a['observed_turns']}; median including failed turns {a['median_seconds_including_failures']:.3f}s. Completed-turn median {a['completed_median_seconds']:.3f}s. Two dependent-blocked turns have no latency. Query embeddings were warmed by the fixed retrieval comparison; these are not cold-start browser measurements. No stable P95 or model ranking is claimed.",
    '',f"Known successful token usage at protocol list prices: USD {s['usage']['known_usage_list_price_usd']:.6f}; two failed generation calls have unknown usage/billing. Conservative reserved amount: USD {s['reserved_cost_usd']:.6f}, within USD2. Neither amount is an invoice.",
    '', 'Development, document-holdout and same-file-holdout summaries are separate in summary.json/summary.csv and the HTML report. Two holdout PDF questions share one document; the CSV holdout shares a development file. No independence or unseen-domain claim. Judgments were source-reviewed by the assistant under the approved rubric, not independently double-rated by humans.',
    '', '## Reproduction','', 'Open report.html locally for filtering and per-turn details. JSONL preserves original requests, evidence, responses and attempts; review.json records the source-grounded judgments. Recompute every derived result without a key:', '',
    f'```sh\npython eval/summarize_m50.py eval/results/m50/{root.name}\n```','',
    'For a new live run, follow eval/README.md using the recorded evaluation commit, original files with matching hashes, the pinned tokenizer and your own credentials. New output/runtime directories are mandatory. Provider models/defaults, quota and network behavior may vary. The raw results do not prove the separate M5 Docker/browser clean-install acceptance.']
    (root/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    rows=[]
    for r in [x for x in scored if x['type']=='answer']:
        raw=answers[r['case']]; answer=(raw.get('task',{}).get('answer') or {})
        text='\n'.join(x['text'] for x in answer.get('segments',[]))
        gaps='\n'.join(answer.get('gaps',[]))
        rows.append(f'<tr data-split="{r["split"]}"><td>{r["case"]}</td><td>{r["split"].replace("_"," ")}</td><td>{r["status"].replace("_"," ")}</td><td>{sum(f["correct"] for f in r["facts"])}/{len(r["facts"])}</td><td>{"Pass" if r["strict_pass"] else "Fail"}</td><td>{r["seconds"]:.2f}s</td></tr>' if r['seconds'] is not None else f'<tr data-split="{r["split"]}"><td>{r["case"]}</td><td>{r["split"].replace("_"," ")}</td><td>Dependent blocked</td><td>0/{len(r["facts"])}</td><td>Fail</td><td>Not executed</td></tr>')
        rows.append(f'<tr data-split="{r["split"]}"><td colspan="6"><details><summary>{escape(cases[r["case"]]["question"])}</summary><p>{escape(r["reason"])}</p><h4>Final answer</h4><pre>{escape(text or "No answer published")}</pre>{"<h4>Gaps</h4><pre>"+escape(gaps)+"</pre>" if gaps else ""}</details></td></tr>')
    bars=''.join(f'<div class="barrow"><span>{arm}</span><progress max="12" value="{r["units_hit"]}" aria-label="{arm} evidence units"></progress><b>{r["units_hit"]}/12</b><span>Complete {r["complete_questions"]}/7</span></div>' for arm,r in s['retrieval']['all'].items())
    groups=''.join(f'<li>{group.replace("_"," ")}: strict {r["strict_pass"]}/{r["turns"]}; facts {r["facts_correct"]}/{r["facts_required"]}</li>' for group,r in s['answers'].items() if group!='all')
    html='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SITECO evaluation evidence</title><style>
:root{color-scheme:light;--ink:#18344a;--blue:#246b98;--paper:#fff;--mist:#edf3f7;--line:#c4d3df;--red:#a72f43}*{box-sizing:border-box}body{margin:0;color:var(--ink);background:var(--paper);font:16px/1.6 'Segoe UI',Arial,sans-serif}main{max-width:1120px;margin:auto;padding:36px 26px}h1{font-size:32px;line-height:1.2;max-width:700px}h2{font-size:23px;margin-top:32px}p{max-width:850px}.intro{border-left:6px solid var(--blue);padding-left:22px}.notice{background:var(--mist);padding:18px 22px}.metrics{display:flex;gap:40px;flex-wrap:wrap;margin:24px 0}.metrics strong{display:block;font-size:26px}.barrow{display:grid;grid-template-columns:90px 1fr 64px 130px;align-items:center;gap:16px;margin:12px 0}progress{width:100%;height:22px;accent-color:var(--blue)}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}th{background:var(--mist)}.scroll{overflow:auto}details{max-width:980px}summary{cursor:pointer}pre{white-space:pre-wrap;font:inherit;background:var(--mist);padding:12px}select{font:inherit;padding:6px 12px;margin:10px}a{color:var(--blue)}:focus-visible{outline:3px solid var(--blue);outline-offset:3px}.meta{font-size:14px}footer{margin-top:32px;border-top:1px solid var(--line);padding-top:18px}@media(max-width:600px){main{padding:22px 14px}h1{font-size:26px}.barrow{grid-template-columns:70px 1fr 48px;gap:8px}.barrow span:last-child{grid-column:2/4}.metrics{gap:20px}th,td{padding:8px}}</style></head><body><main>'''
    html+=f'<header class="intro"><h1>Retrieval coverage and answer reliability</h1><p>SITECO frozen evaluation, A+B. Product {s["product_commit"][:7]}; evaluation {s["evaluation_commit"][:7]}. First results, failures retained.</p></header><div class="metrics"><div><strong>{a["strict_pass"]}/12</strong>Strict turn pass</div><div><strong>{a["facts_correct"]}/40</strong>Required facts supported</div><div><strong>{s["total_attempts"]}</strong>Provider attempts / 153 allowed</div><div><strong>{s["elapsed_seconds"]/60:.2f} min</strong>Live A+B execution</div></div>'
    html+='<p class="notice">Evaluation completed; product acceptance is not established. Two timeout-like provider failures, two literal-boundary validation failures and two dependent-blocked turns remain in the fixed denominators. C did not run.</p>'
    html+='<h2>PDF evidence coverage at 8</h2><p>Matched required evidence units, out of 12 across 7 fixed questions. Each arm uses the same corpus and queries. Higher is better.</p>'+bars
    html+='<p class="meta">Source: retrieval.jsonl and source-reviewed evidence mappings. Macro recall, MRR and split-specific denominators are in summary.csv. Rerank recovered one extra E02 unit but did not increase complete questions; this does not measure reranked answer quality.</p><h2>Development and holdout</h2><ul>'+groups+'</ul>'
    html+='<h2>First result by turn</h2><label for="split">Show group</label><select id="split"><option value="all">All 12 turns</option value="development">Development</option><option value="holdout_document">Document holdout</option><option value="holdout_same_file">Same-file holdout</option></select><div class="scroll"><table><thead><tr><th>Case</th><th>Group</th><th>Execution</th><th>Facts</th><th>Strict</th><th>Time</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>'
    html+=f'<h2>Interpretation</h2><p>E07/E12 fail because a sentence-final period is treated as part of an order token. Zero-call replay succeeds with a question mark, comma or no punctuation. E01 omits supplied qualifications; E02 also makes a false onlyfy absence claim. E11 answers silver-only correctly but omits the approved rubric’s full colour enumeration.</p><p>Median observed backend turn, including failures: {a["median_seconds_including_failures"]:.2f}s (n={a["observed_turns"]}). Two blocked turns have no timing. Rerank provider median: {s["rerank"]["median_provider_seconds"]:.3f}s (n=7). Query embeddings were warm; no P95 or browser-latency claim.</p><p>Known successful usage at listed prices: USD {s["usage"]["known_usage_list_price_usd"]:.5f}; failed-call usage is unknown. Reserve: USD {s["reserved_cost_usd"]:.5f} / USD2. These are not billed charges.</p>'
    html+='<footer><p><a href="report.md">Full report</a> · <a href="summary.csv">CSV summary</a> · <a href="summary.json">JSON summary</a> · <a href="review.json">Reviewed judgments</a> · <a href="protocol.md">Protocol</a> · <a href="../../../README.md">Reproduction instructions</a></p><p class="meta">Small correlated sample; assistant source review, not independent human double review. Original materials are not distributed here. Live reproduction requires matching files, your own keys and quota. Offline summary regeneration needs no key.</p></footer></main><script>document.getElementById("split").addEventListener("change",function(){document.querySelectorAll("tr[data-split]").forEach(row=>{row.hidden=this.value!=="all"&&row.dataset.split!==this.value})});</script></body></html>'
    (root/'report.html').write_text(html,encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path)
    main(parser.parse_args().run)
