from core.search_engine import es_client
res = es_client.get(index="mathstudio_terms", id="10926")
print(type(res['_source']['used_terms']))
print(res['_source']['used_terms'])
