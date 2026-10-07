"""Block T: a 32B teacher writes training data, 4B/8B/14B students learn the pipeline's model roles.

    T1 sample    pick seed chunks from the corpus                          laptop, CPU
    T2 generate  teacher writes a patient-style Vietnamese query per seed   Kaggle T4x2
    T3 mine      current retriever finds hard negatives for each query     laptop, GPU 4GB
    T4 judge     teacher scores every (query, candidate) pair              Kaggle T4x2
    T5 train     QLoRA student: reranker, embedding or translator          Kaggle, one T4 each

The teacher only ever sees corpus chunks and its own synthetic queries, never the 1.200 test
queries, and it never runs at inference. The organisers allow a >15B teacher under that condition
(docs/note/Q&A, tools.txt, question 3); every student stays at or under 15B parameters.
"""
