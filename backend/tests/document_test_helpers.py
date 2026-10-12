import csv
import time
from io import StringIO
from test_csv_parsing import HEADERS, row

def csv_bytes(rows):
    out = StringIO()
    csv.writer(out, delimiter=';').writerows([HEADERS, *rows])
    return out.getvalue().encode()


def ready(client):
    response = client.post('/api/documents', files={'file': ('prices.csv', csv_bytes([row('001', '12,50')]), 'text/csv')})
    identity = response.json()['document_id']
    for _ in range(100):
        if client.get('/api/documents/' + identity).json()['status'] == 'ready':
            return identity
        time.sleep(.02)
    raise AssertionError('Not ready')
