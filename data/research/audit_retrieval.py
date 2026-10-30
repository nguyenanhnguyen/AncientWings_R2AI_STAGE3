"""Audit corpus composition and saved retrieval outputs without inference or labels."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',default='nguyen/pipeline_runs/balanced_60k/contextual')
    p.add_argument('--out',default='data/research/eda/balanced60k_retrieval_audit')
    a=p.parse_args();run=ROOT/a.run;out=ROOT/a.out;out.mkdir(parents=True,exist_ok=True)
    docs=pq.read_table(run/'corpus/corpus.parquet',columns=['id','lang','domain','title','text']).to_pylist()
    metadata={r['id']:r for r in docs}
    bylang=defaultdict(Counter)
    lengths=defaultdict(list)
    for d in docs:
        bylang[d['lang']][d['domain']]+=1
        lengths[d['lang']].append(len(d['text']))
    records=[json.loads(line) for line in (run/'retrieval/candidates.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    candidate_lang=Counter();top1=Counter();absence=Counter();scores=defaultdict(list);domain=Counter()
    channels=defaultdict(Counter);perquery=[];unique_docs=set()
    for q in records:
        candidates=q['candidates'];present=set()
        for c in candidates:
            d=metadata[c['doc_id']];lang=d['lang'];present.add(lang)
            candidate_lang[lang]+=1;domain[d['domain']]+=1;unique_docs.add(c['doc_id'])
            scores[lang].append(c['ce_score'])
            for channel in c.get('channels',[]):channels[lang][str(channel)]+=1
        if candidates:top1[metadata[candidates[0]['doc_id']]['lang']]+=1
        for lang in bylang:
            if lang not in present:absence[lang]+=1
        perquery.append(dict(query_id=q['query_id'],query=q['query'],candidate_languages=dict(Counter(metadata[c['doc_id']]['lang'] for c in candidates)),
                             top_score=candidates[0]['ce_score'] if candidates else None))
    result=dict(documents=len(docs),queries=len(records),corpus_languages={k:sum(v.values()) for k,v in bylang.items()},
                corpus_domains_by_language={k:dict(v.most_common()) for k,v in bylang.items()},
                dominant_domain_share={k:max(v.values())/sum(v.values()) for k,v in bylang.items()},
                median_document_chars={k:statistics.median(v) for k,v in lengths.items()},
                saved_candidate_languages=dict(candidate_lang),top1_language=dict(top1),
                queries_without_saved_candidate_language=dict(absence),
                median_reranker_score_by_language={k:statistics.median(v) for k,v in scores.items()},
                candidate_domains=dict(domain.most_common()),retrieval_channels_by_language={k:dict(v) for k,v in channels.items()},
                distinct_retrieved_documents=len(unique_docs),
                caveats=['No relevance labels: these are exposure and composition statistics, not recall or bias proof.',
                         'Only saved top-25 candidates are observable; missing-language absence can arise before or after reranking.',
                         'Reranker scores are uncalibrated and not directly comparable probabilities across languages.',
                         'A source domain imbalance is not itself proof of irrelevant documents.'])
    (out/'audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    with (out/'query_audit.jsonl').open('w',encoding='utf-8') as f:
        for row in perquery:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('retrieval_channels_by_language','candidate_domains')},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
