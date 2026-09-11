"""Network-free image fixtures for scheduling and delivery tests."""
def prepared_assets(items, *args, **kwargs):
    return [{**item, 'news_url': item.get('source_url') or item.get('url') or
             'https://publisher.example/news/' + str(index),
             'image_key': 'img_v3_test_article', 'image_kind': 'source',
             'image_source_url': 'https://publisher.example/photo.jpg'}
            for index, item in enumerate(items)]
