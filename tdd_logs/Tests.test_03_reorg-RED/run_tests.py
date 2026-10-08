"""Offline executable tests and evidence recorder (stdlib only)."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'artifacts'
OUT.mkdir(exist_ok=True)
TRACE = OUT / 'trace.jsonl'

def emit(kind, **data):
    with TRACE.open('a') as f:
        f.write(json.dumps(dict(kind=kind, **data), sort_keys=True) + '\n')

def h(label):
    return '0x' + hashlib.sha256(label.encode()).hexdigest()

def address(n):
    return '0x' + format(n, '040x')

A, B, C = address(1), address(2), address(3)

def event(name, **args):
    return dict(event=name, args=args)

def fixtures(seed=7):
    prefix = str(seed)
    common = [
        [event('BountyCreated', bountyId=1, creator=A, reward=100, deadline=1000, briefHash=h('brief1'), briefURI='local:1'),
         event('BountyCreated', bountyId=2, creator=A, reward=60, deadline=1000, briefHash=h('brief2'), briefURI='local:2')],
        [event('WorkSubmitted', bountyId=1, author=B, operator=B, proofHash=h('proof1'), proofURI='local:proof1')]]
    left = [[event('WorkSubmitted', bountyId=1, author=C, operator=C, proofHash=h('orphan'), proofURI='local:orphan')],
            [event('BountyAwarded', bountyId=1, winner=C, amount=100)],
            [event('Withdrawn', account=C, recipient=C, amount=100)],
            [event('BountyRefunded', bountyId=2, creator=A, amount=60, status=3)],
            [event('Withdrawn', account=A, recipient=A, amount=60)]]
    right = [[event('WorkSubmitted', bountyId=1, author=B, operator=B, proofHash=h('updated'), proofURI='local:updated')],
             [event('BountyAwarded', bountyId=1, winner=B, amount=100)],
             [event('BountyRefunded', bountyId=2, creator=A, amount=60, status=3)],
             [event('Withdrawn', account=B, recipient=C, amount=100)],
             [event('Withdrawn', account=A, recipient=A, amount=60)]]
    def chain(branch, suffix):
        parent = h('genesis:' + prefix)
        blocks = []
        for height, entries in enumerate(common + suffix, 1):
            bh = h(prefix + (':common:' if height <= 2 else ':' + branch + ':') + str(height))
            logs = [dict(e, logIndex=i, transactionIndex=i, transactionHash=h(bh + ':tx:' + str(i))) for i, e in enumerate(entries)]
            blocks.append(dict(height=height, hash=bh, parent=parent, logs=logs))
            parent = bh
        return blocks
    return dict(seed=seed, genesis=h('genesis:' + prefix), left=chain('left', left), right=chain('right', right))

F = fixtures()
(OUT / 'fixtures.json').write_text(json.dumps(F, indent=2, sort_keys=True) + '\n')

def indexer():
    assert (ROOT / 'indexer.py').exists(), 'missing canonical indexer implementation'
    import indexer as module
    return module.Indexer

def db(name):
    path = OUT / (name + '.sqlite')
    for suffix in ('', '-wal', '-shm'):
        p = Path(str(path) + suffix)
        if p.exists():
            p.unlink()
    return path

class Tests(unittest.TestCase):
    def test_03_reorg(self):
        x = indexer()(db('reorg'), F['genesis'])
        x.ingest(F['left'], F['left'][-1]['hash'])
        before = x.snapshot()
        x.ingest(list(reversed(F['right'][2:])), F['right'][-1]['hash'])
        fresh = indexer()(db('reorg_fresh'), F['genesis'])
        fresh.ingest(F['right'], F['right'][-1]['hash'])
        after = x.snapshot()
        self.assertEqual(after, fresh.snapshot())
        removed = set(r[1] for r in before['blocks']) - set(r[1] for r in after['blocks'])
        self.assertEqual(len(removed), 5)
        self.assertNotIn('1:' + C, after['state']['submissions'])
        self.assertNotIn(C, after['state']['withdrawn'])
        (OUT / 'recovered_snapshot.json').write_text(json.dumps(after, indent=2, sort_keys=True) + '\n')
        (OUT / 'fresh_snapshot.json').write_text(json.dumps(fresh.snapshot(), indent=2, sort_keys=True) + '\n')
        x.close()
        fresh.close()
        emit('five_block_reorg', removed_hashes=sorted(removed), replay_equal=True)

    def test_02_delivery(self):
        x = indexer()(db('delivery'), F['genesis'])
        batch = copy.deepcopy(F['right'])
        batch[0]['logs'].reverse()
        batch[0]['logs'].append(copy.deepcopy(batch[0]['logs'][0]))
        batch = list(reversed(batch)) + [copy.deepcopy(batch[3])]
        x.ingest(batch, F['right'][-1]['hash'])
        first = x.snapshot()
        x.close()
        x = indexer()(OUT / 'delivery.sqlite', F['genesis'])
        x.ingest(batch, F['right'][-1]['hash'])
        self.assertEqual(x.snapshot(), first)
        fresh = indexer()(db('delivery_fresh'), F['genesis'])
        fresh.ingest(F['right'], F['right'][-1]['hash'])
        self.assertEqual(x.snapshot(), fresh.snapshot())
        fresh.close()
        x.close()
        emit('duplicate_out_of_order', delivered_blocks=len(batch), unique_blocks=7, delivered_logs=sum(len(b['logs']) for b in batch), canonical_logs=8, replay_equal=True)

    def test_01_canonical(self):
        x = indexer()(db('canonical'), F['genesis'])
        x.ingest(F['right'], F['right'][-1]['hash'])
        s = x.snapshot()
        self.assertEqual(len(s['blocks']), 7)
        self.assertEqual(len(s['logs']), 8)
        self.assertEqual(s['checkpoint'], [7, F['right'][-1]['hash']])
        self.assertEqual(len(s['state']['submissions']), 1)
        self.assertEqual(s['state']['submissions']['1:' + B]['proofHash'], h('updated'))
        self.assertEqual(s['state']['credited'], {A: 60, B: 100})
        self.assertEqual(s['state']['withdrawn'], {A: 60, B: 100})
        self.assertEqual(s['state']['claimable'], {A: 0, B: 0})
        x.close()
        emit('canonical', blocks=7, logs=8, submissions=1)

if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--record':
        phase, name = sys.argv[2:]
        command = [sys.executable, str(ROOT / 'run_tests.py'), name]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        evidence = ROOT / 'tdd_logs' / (name + '-' + phase)
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / 'stdout.txt').write_text(result.stdout)
        (evidence / 'stderr.txt').write_text(result.stderr)
        digests = {}
        for filename in ('run_tests.py', 'indexer.py'):
            p = ROOT / filename
            if p.exists():
                content = p.read_bytes()
                (evidence / filename).write_bytes(content)
                digests[filename] = hashlib.sha256(content).hexdigest()
        record = dict(phase=phase, test=name, exit=result.returncode, command=command, source_sha256=digests)
        (evidence / 'metadata.json').write_text(json.dumps(record, indent=2) + '\n')
        with (ROOT / 'tdd_logs' / 'cycles.jsonl').open('a') as f:
            f.write(json.dumps(record, sort_keys=True) + '\n')
        print(result.stdout + result.stderr)
        print(json.dumps(record, sort_keys=True))
        sys.exit(result.returncode)
    unittest.main()
