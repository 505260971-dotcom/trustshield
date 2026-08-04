"""Offline regression for the config-file embedding recall adapter."""
import json
import os
import sys
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

runtime = tempfile.mkdtemp(prefix='contractguard-embedding-test-')
os.environ.update({
    'CONTRACTGUARD_DATA_DIR': runtime,
    'AUTH_SECRET': 'embedding-test-auth-secret-long-enough',
    'DATA_ENCRYPTION_KEY': Fernet.generate_key().decode(),
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import embedding
from app.services import rerank


class _Response:
    def __init__(self, body): self.body = body
    def read(self): return json.dumps(self.body).encode('utf-8')
    def __enter__(self): return self
    def __exit__(self, *_): return False


def main():
    old = {name: getattr(embedding, name) for name in (
        'EMBEDDING_ENABLED', 'EMBEDDING_ALLOW_REMOTE_FINANCIAL_DATA',
        'EMBEDDING_BASE_URL', 'EMBEDDING_API_KEY', 'EMBEDDING_MODEL',
        'EMBEDDING_DIMENSIONS', 'configured_embedding', 'urlopen',
    )}
    try:
        embedding.EMBEDDING_ENABLED = True
        embedding.EMBEDDING_ALLOW_REMOTE_FINANCIAL_DATA = True
        embedding.EMBEDDING_BASE_URL = 'https://workspace.cn-beijing.maas.aliyuncs.com/compatible-api/v1'
        embedding.EMBEDDING_API_KEY = 'test-key'
        embedding.EMBEDDING_MODEL = 'text-embedding-test'
        embedding.EMBEDDING_DIMENSIONS = 8
        embedding.configured_embedding = lambda: True
        captured = {}

        def fake_urlopen(request, timeout):
            captured['url'] = request.full_url
            captured['payload'] = json.loads(request.data.decode('utf-8'))
            return _Response({'data': [
                {'index': 0, 'embedding': [1, 0, 0, 0, 0, 0, 0, 0]},
                {'index': 1, 'embedding': [0.9, 0.1, 0, 0, 0, 0, 0, 0]},
                {'index': 2, 'embedding': [0, 1, 0, 0, 0, 0, 0, 0]},
            ]})

        embedding.urlopen = fake_urlopen
        rows = embedding.semantic_recall('偿债能力', [
            {'chunk_id': 'A', 'text': '流动资产和流动负债', 'masked_text': '流动资产和流动负债'},
            {'chunk_id': 'B', 'text': '客户新闻报道', 'masked_text': '客户新闻报道'},
        ])
        assert captured['url'].endswith('/compatible-api/v1/embeddings')
        assert captured['payload']['model'] == 'text-embedding-test'
        assert captured['payload']['dimensions'] == 8
        assert [item['chunk_id'] for item in rows] == ['A', 'B']
        assert rows[0]['embedding_rank'] == 1 and rows[0]['embedding_score'] > rows[1]['embedding_score']

        old_enabled, old_semantic = rerank.EMBEDDING_ENABLED, rerank.semantic_recall
        try:
            rerank.EMBEDDING_ENABLED = True
            rerank.semantic_recall = lambda _query, _items: [
                {'chunk_id': 'B', 'text': 'B', 'embedding_rank': 1},
                {'chunk_id': 'A', 'text': 'A', 'embedding_rank': 2},
            ]
            fused, mode = rerank.hybrid_recall('流动资产', [
                {'chunk_id': 'A', 'text': '流动资产'}, {'chunk_id': 'B', 'text': '无直接词法命中'},
            ])
            assert mode == 'hybrid_lexical_embedding'
            assert {item['chunk_id'] for item in fused} == {'A', 'B'}
            assert all('hybrid_score' in item for item in fused)
        finally:
            rerank.EMBEDDING_ENABLED, rerank.semantic_recall = old_enabled, old_semantic
    finally:
        for name, value in old.items(): setattr(embedding, name, value)
    print('config-file embedding recall and hybrid fusion passed')


if __name__ == '__main__':
    main()
