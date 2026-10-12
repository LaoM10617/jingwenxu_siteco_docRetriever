from pydantic import BaseModel

from app.generation import wire_schema


def test_schema_keyword_named_fields_survive_provider_conversion():
    class Chart(BaseModel):
        title: str
        default: str
    class Plan(BaseModel):
        chart: Chart | None
    schema = wire_schema(Plan.model_json_schema())
    chart = schema['properties']['chart']['anyOf'][0]
    assert chart['required'] == ['title', 'default']
    assert chart['properties'] == {'title': {'type': 'string'}, 'default': {'type': 'string'}}
    assert 'title' not in chart
