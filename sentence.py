import csv
import math
import os
import gzip
import torch

import numpy as np

from datetime import datetime
from pathlib import Path
from torch.utils.data import DataLoader
from sentence_transformers import SentenceTransformer, models, losses, util, InputExample, LoggingHandler
from sentence_transformers.evaluation import EmbeddingSimilarityEvaluator
from tokenizers import ByteLevelBPETokenizer, BertWordPieceTokenizer, SentencePieceBPETokenizer, CharBPETokenizer

from models import GPTQ

embed_dim = 32
vocab_size = 2000
n_heads = 4
dropout_rate = 0.1
n_tlayers = 1
max_seq_len = 512
n_qlayers = 1
q_device: str="lightning.qubit"
lr = 1e-3

model_name = 'gptq'
train_batch_size = 16
num_epochs = 2
model_save_path = 'output/training_stsbenchmark_continue_training-'+model_name+'-'+datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

special_tokens = [
        "<s>",
        "<pad>",
        "</s>",
        "<unk>",
        "<mask>",
    ]

train_samples = []
dev_samples = []
test_samples = []
sts_dataset_path = 'datasets/stsbenchmark.tsv.gz'
with gzip.open(sts_dataset_path, 'rt', encoding='utf8') as fIn:
    reader = csv.DictReader(fIn, delimiter='\t', quoting=csv.QUOTE_NONE)
    for row in reader:
        score = float(row['score']) / 5.0  # Normalize score to range 0 ... 1
        inp_example = InputExample(texts=[row['sentence1'], row['sentence2']], label=score)

        if row['split'] == 'dev':
            dev_samples.append(inp_example)
        elif row['split'] == 'test':
            test_samples.append(inp_example)
        else:
            train_samples.append(inp_example)

tokenizer = CharBPETokenizer()
vocab_size = 16
min_freq = 2
#paths = [str(x) for x in Path("./datasets/").glob("*.txt")]
tokenizer.train(files=["datasets/sentences.txt"], vocab_size=vocab_size, min_frequency=min_freq, special_tokens=special_tokens)
tokenizer.save_model(".", model_name)
print("Saved vocabulary")


gptq = GPTQ(embed_dim=embed_dim,
            src_vocab=vocab_size,
            tgt_vocab=2,
            n_heads=n_heads,
            dropout_rate=dropout_rate,
            n_tlayers=n_tlayers,
            max_seq_len=max_seq_len,
            n_qlayers=n_qlayers,
            q_device=q_device)
pooling_model = models.Pooling(gptq.get_word_embedding_dimension())
dense_model = models.Dense(in_features=pooling_model.get_sentence_embedding_dimension(), out_features=256, activation_function=torch.nn.Tanh())

model = SentenceTransformer(modules=[gptq, pooling_model, dense_model])

train_dataloader = DataLoader(train_samples, shuffle=True, batch_size=train_batch_size)
train_loss = losses.CosineSimilarityLoss(model=model)

evaluator = EmbeddingSimilarityEvaluator.from_input_examples(dev_samples, name='sts-dev')


warmup_steps = math.ceil(len(train_dataloader) * num_epochs * 0.1) #10% of train data for warm-up
model.fit(train_objectives=[(train_dataloader, train_loss)],
          evaluator=evaluator,
          epochs=num_epochs,
          evaluation_steps=1000,
          warmup_steps=warmup_steps,
          output_path=model_save_path)
