"""Source previews through document HTTP, using isolated original files."""
from base64 import b64decode
from io import BytesIO

import pytest
from PIL import Image
from fastapi.testclient import TestClient
from app.main import create_app
from app.processing import DocumentProcessor
from test_app import settings_for
from test_multi_document_tasks import TaskGateway, upload
from test_question_tasks import csv_bytes
from test_csv_parsing import row
from test_parsing import pdf_file


def test_csv_preview_preserves_logical_record_and_raw_fields(tmp_path):
    first = row('001')
    first[2] = 'A; quoted description\ncontinued'
    with TestClient(create_app(settings_for(tmp_path), processor=DocumentProcessor(TaskGateway()))) as client:
        doc = upload(client, 'prices.csv', csv_bytes([first, row('002')]))
        evidence = client.get(f'/api/documents/{doc}/evidence').json()
        response = client.get(f'/api/documents/{doc}/evidence/{evidence[1]["evidence_id"]}/preview')
        assert response.status_code == 200
        preview = response.json()
        assert preview['kind'] == 'csv'
        assert preview['record_number'] == 2
        assert preview['raw_values'] == row('002')
        assert preview['headers'][0] == 'Bestellnummer'
        first_preview = client.get(f'/api/documents/{doc}/evidence/{evidence[0]["evidence_id"]}/preview').json()
        assert first_preview['record_number'] == 1
        assert first_preview['raw_values'][2] == 'A; quoted description\ncontinued'
        assert client.get(f'/api/documents/{doc}/evidence/stale/preview').status_code == 404
        assert client.get('/api/documents/unknown/evidence/stale/preview').status_code == 404


def test_pdf_preview_opens_cited_page_and_regions_cover_original_ink(tmp_path):
    path = pdf_file(tmp_path, ['BT /F1 12 Tf 20 100 Td (Wrong page) Tj ET', 'BT /F1 12 Tf 20 100 Td (Evidence) Tj ET'], commands=True)
    with TestClient(create_app(settings_for(tmp_path), processor=DocumentProcessor(TaskGateway()))) as client:
        doc = upload(client, 'original.pdf', path.read_bytes())
        evidence = client.get(f'/api/documents/{doc}/evidence').json()
        source = next(e for e in evidence if e['locator']['page_number'] == 2)
        response = client.get(f'/api/documents/{doc}/evidence/{source["evidence_id"]}/preview')
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        preview = response.json()
        assert preview['kind'] == 'pdf' and preview['page_number'] == 2
        assert preview['notice'] is None
        image = Image.open(BytesIO(b64decode(preview['image'].split(',')[1]))).convert('RGB')
        assert image.size == (preview['width'], preview['height'])
        assert max(image.size) <= 1600
        regions = preview['regions']
        assert regions and all(r['role'] == 'evidence' for r in regions)
        for region in regions:
            x, y, w, h = region['box']
            assert 0 <= x < x+w <= 1 and 0 <= y < y+h <= 1
            # PDF text was authored at x=20, baseline y=100 on a 200x200 page.
            assert abs(x - .1) < .01 and .43 < y < .5
            crop = image.crop((round(x*image.width), round(y*image.height),
                               round((x+w)*image.width), round((y+h)*image.height)))
            assert min(sum(pixel) for pixel in crop.get_flattened_data()) < 100


def geometry_pdf(media, crop, rotation):
    content = b'BT /F1 12 Tf 40 220 Td (Evidence) Tj ET'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Count 1 /Kids [3 0 R] >>',
        (f'<< /Type /Page /Parent 2 0 R /MediaBox [{media}] /CropBox [{crop}] /Rotate {rotation} '
         '/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> '
         '/Contents 4 0 R >>').encode(),
        b'<< /Length ' + str(len(content)).encode() + b' >>\nstream\n' + content + b'\nendstream']
    data, offsets = bytearray(b'%PDF-1.4\n'), [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f'{index} 0 obj\n'.encode() + obj + b'\nendobj\n')
    start = len(data)
    data.extend(b'xref\n0 5\n0000000000 65535 f \n')
    for offset in offsets[1:]:
        data.extend(f'{offset:010d} 00000 n \n'.encode())
    data.extend(f'trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF'.encode())
    return bytes(data)


@pytest.mark.parametrize('media,crop,rotation', [
    ('0 0 200 300', '0 0 200 300', 0),
    ('0 0 200 300', '20 30 180 280', 0),
    ('10 20 210 320', '10 20 210 320', 0),
    ('0 0 200 300', '0 0 200 300', 90),
    ('0 0 200 300', '0 0 200 300', 180),
    ('0 0 200 300', '0 0 200 300', 270),
    ('10 20 210 320', '20 30 180 280', 90),
    ('10 20 210 320', '20 30 180 280', 180),
    ('10 20 210 320', '20 30 180 280', 270),
])
def test_geometry_highlight_covers_rendered_text_not_an_empty_area(tmp_path, media, crop, rotation):
    with TestClient(create_app(settings_for(tmp_path), processor=DocumentProcessor(TaskGateway()))) as client:
        doc = upload(client, 'geometry.pdf', geometry_pdf(media, crop, rotation))
        source = client.get(f'/api/documents/{doc}/evidence').json()[0]
        response = client.get(f'/api/documents/{doc}/evidence/{source["evidence_id"]}/preview')
        assert response.status_code == 200
        preview = response.json()
        assert preview['notice'] is None
        image = Image.open(BytesIO(b64decode(preview['image'].split(',')[1]))).convert('RGB')
        boxes = preview['regions']
        assert boxes and all(max(r['box'][2:]) < .6 for r in boxes)
        dark = [(x, y) for y in range(image.height) for x in range(image.width)
                if max(image.getpixel((x, y))) < 100]
        assert len(dark) > 30
        # Independent oracle: actual glyph pixels must lie inside a small source region.
        assert all(any(r['box'][0]*image.width-2 <= x <= sum(r['box'][::2])*image.width+2
                       and r['box'][1]*image.height-2 <= y <= sum(r['box'][1::2])*image.height+2
                       for r in boxes) for x, y in dark)


def test_context_regions_and_missing_original_keep_text_available(tmp_path):
    commands = ['BT /F1 8 Tf 10 180 Td (Model A) Tj ET',
                'BT /F1 6 Tf 10 160 Td (Power 9 W) Tj ET',
                'BT /F1 6 Tf 10 150 Td (Only at 25 C) Tj ET',
                '10 170 m 90 170 l S', '10 155 m 90 155 l S', '10 145 m 90 145 l S']
    path = pdf_file(tmp_path, ['\n'.join(commands)], commands=True)
    settings = settings_for(tmp_path)
    with TestClient(create_app(settings, processor=DocumentProcessor(TaskGateway()))) as client:
        doc = upload(client, 'table.pdf', path.read_bytes())
        source = client.get(f'/api/documents/{doc}/evidence').json()[0]
        url = f'/api/documents/{doc}/evidence/{source["evidence_id"]}/preview'
        preview = client.get(url).json()
        assert {r['role'] for r in preview['regions']} == {'evidence', 'context'}
        assert len(preview['regions']) >= 3
        original = settings.data_dir / 'uploads' / doc
        original.write_bytes(b'%PDF-original changed')
        assert client.get(url).status_code == 409
        original.unlink()
        assert client.get(url).status_code == 404
        assert client.get(f'/api/documents/{doc}/evidence').json()[0]['text'] == source['text']


def test_nonready_preview_uses_same_gate_as_evidence(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        doc = client.post('/api/documents', files={'file': ('bad.csv', b'id\n1')}).json()['document_id']
        response = client.get(f'/api/documents/{doc}/evidence/unknown/preview')
        assert response.status_code == 409
        assert response.json()['error']['code'] == 'document_not_ready'


@pytest.mark.parametrize('mode', ['missing', 'outside', 'invalid_page'])
def test_unreliable_or_old_source_location_never_draws_a_guessed_box(tmp_path, mode):
    class OldSourceProcessor(DocumentProcessor):
        def prepare(self, *args, **kwargs):
            prepared = super().prepare(*args, **kwargs)
            for source in prepared.evidence:
                if mode == 'missing':
                    source.pop('source_spans', None)
                elif mode == 'outside':
                    source['source_spans'][0]['bbox'] = [-10, 10, 50, 20]
                else:
                    source['locator']['page_number'] = 99
            return prepared
    path = pdf_file(tmp_path, ['Evidence'])
    with TestClient(create_app(settings_for(tmp_path), processor=OldSourceProcessor(TaskGateway()))) as client:
        doc = upload(client, 'old.pdf', path.read_bytes())
        source = client.get(f'/api/documents/{doc}/evidence').json()[0]
        response = client.get(f'/api/documents/{doc}/evidence/{source["evidence_id"]}/preview')
        if mode == 'invalid_page':
            assert response.status_code == 503
            assert response.json()['error']['code'] == 'preview_unavailable'
        else:
            assert response.status_code == 200
            assert response.json()['regions'] == []
            assert 'page only' in response.json()['notice']
            assert response.json()['image'].startswith('data:image/png;base64,')


def test_large_page_render_is_bounded(tmp_path):
    with TestClient(create_app(settings_for(tmp_path), processor=DocumentProcessor(TaskGateway()))) as client:
        doc = upload(client, 'large.pdf', geometry_pdf('0 0 2000 3000', '0 0 2000 3000', 0))
        source = client.get(f'/api/documents/{doc}/evidence').json()[0]
        preview = client.get(f'/api/documents/{doc}/evidence/{source["evidence_id"]}/preview').json()
        assert preview['height'] == 1600 and preview['width'] <= 1600
