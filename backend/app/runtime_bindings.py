"""Bind immutable runtime configuration to accepted work; admission state stays shared."""
from types import SimpleNamespace
from app.answers import AnswerService
from app.questions import QuestionTools
from app.processing import DocumentProcessor
from app.retrieval.pdf import PdfRetriever
from app.voyage import configured_gateway
from app.reranking import Reranker, configured_reranker
from app.embeddings import BudgetScheduler
from app.generation import StructuredModel


class RuntimeBindings:
    def __init__(self, memory, documents, *, processor=None, model=None):
        self.memory,self.documents=memory,documents
        self.processor_override,self.model_override=processor,model
        defaults=memory.defaults
        self.scheduler=BudgetScheduler(documents.database, rpm=defaults.embedding_rpm,
            tpm=defaults.embedding_tpm,min_interval=defaults.embedding_min_interval)
        self.reranker=Reranker(None,min_interval=defaults.rerank_min_interval)

    def gateway(self, config):
        if self.processor_override is not None:
            return getattr(self.processor_override,'gateway',None)
        return configured_gateway(config,scheduler=self.scheduler)

    def answers(self):
        snapshot=self.memory.snapshot()
        config,top_k,_,_=snapshot
        ranker=configured_reranker(config)
        if ranker is not None:
            provider=ranker.provider
            shared=self.reranker
            class Bound:
                def rank(self, question, records, stop=None):
                    return shared.rank(question,records,stop=stop,provider=provider)
            ranker=Bound()
        retriever=PdfRetriever(self.documents,self.documents.lexical,self.gateway(config),
                               reranker=ranker,default_top_k=top_k)
        answer=AnswerService(QuestionTools(self.documents,retriever),
                            self.model_override if self.model_override is not None else StructuredModel(config))
        public=self.memory.public(snapshot)
        answer.config_snapshot={k:public[k] for k in ('revision','generation','retrieval','embedding')}
        # Public snapshots describe behavior, not credential identity or status.
        answer.config_snapshot['generation']={'provider':config.generation_provider,
            'model':getattr(config,config.generation_provider+'_generation_model')}
        answer.config_snapshot['embedding']={'provider':'voyage','model':config.embedding_model}
        return answer

    def processor(self):
        if self.processor_override is not None: return self.processor_override
        return DocumentProcessor(self.gateway(self.memory.snapshot()[0]))
