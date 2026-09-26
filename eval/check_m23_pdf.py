"""Explicit development-sample checks; no model calls or held-out materials.

Run from the repository: backend/.venv/Scripts/python.exe eval/check_m23_pdf.py
The optional argument is a data directory, including a read-only container mount.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.parsing import parse_document, ParseLimits


def check(data):
    samples = {
        'terms': data / 'Legal Documents/Allgemeine_Einkaufsbedingungen_Siteco-Gruppe_April_2025.pdf',
        'rondel': data / 'Brochures/Indoor Lightening/SITECO_Rondel_21_Product_Flyer.pdf',
        'highbay': data / 'Brochures/Indoor Lightening/SIT_Highbay_11_Broschuere_V_25-132_Update_06_25_EN_RZ_web.pdf',
    }
    results = {name: parse_document(path, 'application/pdf', ParseLimits()) for name, path in samples.items()}

    def matching(name, page, needle):
        matches = [e for e in results[name].evidence if e.page_number == page and needle in e.retrieval_text]
        assert len(matches) == 1, (name, page, needle, len(matches))
        return matches[0]

    terms = matching('terms', 1, 'Incoterms')
    assert 'Artikel II' in terms.retrieval_text and '2020' in terms.text
    assert 'pdf-Format' in terms.text and 'ausdrücklich schriftlich zugestimmt' in terms.text
    midi = matching('highbay', 18, 'Weight: 3.7 kg')
    maxi = matching('highbay', 18, 'Weight: 7.2 kg')
    shared = matching('highbay', 18, 'Protection class: IP66')
    for item, model, dimension, temp, other in [(midi, 'midi', '474 mm', '+70 °C', 'maxi'), (maxi, 'maxi', '946 mm', '+65 °C', 'midi')]:
        assert model in item.retrieval_text and other not in item.retrieval_text
        assert dimension in item.text and temp in item.text
        assert 'Protection class' not in item.text
    assert '(all sizes)' in shared.retrieval_text and 'IK08' in shared.text
    assert 'Weight: 3.7' not in shared.text and 'Weight: 7.2' not in shared.text
    variants = matching('rondel', 2, '0MD5307L1830')
    assert '3.000 K 1.800 18 ON / OFF 1,6 0MD5307L1830' in variants.text
    assert '4.000 K 900 9 ON / OFF 1,6 0MD5307L0940' in variants.text
    assert 'Weight' in variants.retrieval_text and 'kg' in variants.retrieval_text
    specs = matching('rondel', 2, 'Protection rating')
    assert 'IP 40 / IK 03' in specs.text and 'Rondel 21' in specs.retrieval_text
    assert '0MD5307L1830' not in specs.text and 'Key Specifications' not in variants.retrieval_text
    accessories = matching('rondel', 2, 'HF movement sensor')
    assert '5MD53003S' in accessories.text and 'Rondel 21 accessories' in accessories.retrieval_text
    assert '0MD5307L1830' not in accessories.text
    report = {}
    for name, result in results.items():
        assert result.evidence == parse_document(samples[name], 'application/pdf', ParseLimits()).evidence
        assert all(e.text and len(e.retrieval_text) <= 6000 for e in result.evidence)
        assert all(e.retrieval_text == '\n'.join(s.text for s in e.context + e.source_spans) for e in result.evidence)
        report[name] = {'pages': result.page_count, 'coverage': result.coverage, 'chunks': len(result.evidence),
                        'max_characters': max(len(e.retrieval_text) for e in result.evidence),
                        'warnings': [{'page': w.page_number, 'code': w.code} for w in result.warnings]}
    return report


if __name__ == '__main__':
    data = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / 'data'
    print(json.dumps(check(data), ensure_ascii=True, indent=2))
