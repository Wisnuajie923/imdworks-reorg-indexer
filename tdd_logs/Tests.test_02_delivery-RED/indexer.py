"""Canonical decoded-event indexer. No RPC, signing, or network dependencies."""
import json
import sqlite3


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def reduce_logs(logs):
    state = dict(bounties={}, submissions={}, credited={}, withdrawn={}, claimable={})
    def credit(account, amount):
        state['credited'][account] = state['credited'].get(account, 0) + amount
        state['claimable'][account] = state['claimable'].get(account, 0) + amount
    for log in logs:
        name, a = log['event'], log['args']
        key = str(a.get('bountyId'))
        if name == 'BountyCreated':
            state['bounties'][key] = dict(a, status='open')
        elif name == 'WorkSubmitted':
            state['submissions'][key + ':' + a['author']] = a.copy()
        elif name == 'BountyAwarded':
            state['bounties'][key].update(status='awarded', winner=a['winner'])
            credit(a['winner'], a['amount'])
        elif name == 'BountyRefunded':
            state['bounties'][key].update(status='refunded', refundStatus=a['status'])
            credit(a['creator'], a['amount'])
        elif name == 'Withdrawn':
            account, amount = a['account'], a['amount']
            state['claimable'][account] -= amount
            state['withdrawn'][account] = state['withdrawn'].get(account, 0) + amount
    return state


class Indexer:
    def __init__(self, path, genesis):
        self.genesis = genesis
        self.conn = sqlite3.connect(path, isolation_level=None)
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('PRAGMA synchronous=FULL')
        self.conn.executescript('''
            CREATE TABLE IF NOT EXISTS blocks(height INTEGER PRIMARY KEY, hash TEXT UNIQUE, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS logs(height INTEGER, idx INTEGER, body TEXT NOT NULL, PRIMARY KEY(height,idx));
            CREATE TABLE IF NOT EXISTS materialized(id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS checkpoint(id INTEGER PRIMARY KEY CHECK(id=1), height INTEGER, hash TEXT);
        ''')

    def ingest(self, batch, head):
        blocks = batch
        logs = [log for b in blocks for log in b['logs']]
        state = reduce_logs(logs)
        self.conn.execute('BEGIN IMMEDIATE')
        try:
            for table in ('blocks', 'logs', 'materialized', 'checkpoint'):
                self.conn.execute('DELETE FROM ' + table)
            for b in blocks:
                self.conn.execute('INSERT INTO blocks VALUES(?,?,?)', (b['height'], b['hash'], encode(b)))
                for log in b['logs']:
                    self.conn.execute('INSERT INTO logs VALUES(?,?,?)', (b['height'], log['logIndex'], encode(log)))
            self.conn.execute('INSERT INTO materialized VALUES(1,?)', (encode(state),))
            self.conn.execute('INSERT INTO checkpoint VALUES(1,?,?)', (blocks[-1]['height'], head))
            self.conn.execute('COMMIT')
        except BaseException:
            self.conn.execute('ROLLBACK')
            raise

    def snapshot(self):
        self.conn.execute('BEGIN')
        try:
            result = dict(blocks=[list(r) for r in self.conn.execute('SELECT height,hash,body FROM blocks ORDER BY height')],
                          logs=[list(r) for r in self.conn.execute('SELECT height,idx,body FROM logs ORDER BY height,idx')],
                          checkpoint=None, state=None)
            cp = self.conn.execute('SELECT height,hash FROM checkpoint').fetchone()
            row = self.conn.execute('SELECT body FROM materialized').fetchone()
            result['checkpoint'] = list(cp) if cp else None
            result['state'] = json.loads(row[0]) if row else None
            self.conn.execute('COMMIT')
            return result
        except BaseException:
            self.conn.execute('ROLLBACK')
            raise

    def close(self):
        self.conn.close()
