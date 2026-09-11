"""Network-free image fixtures for scheduling and delivery tests."""
def prepared_assets(items, *args, **kwargs):
    from cmhk.services.news_image_quality import policy_key
    return [{**item, 'news_url': item.get('source_url') or item.get('url') or
             'https://publisher.example/news/' + str(index),
             'image_key': 'img_v3_test_article', 'image_kind': 'source',
             'image_source_url': 'https://publisher.example/photo.jpg',
             'image_page_url': 'https://publisher.example/article', 'image_sha256': 'a' * 64,
             'image_policy_key': policy_key(), 'image_review_status': 'accepted'}
            for index, item in enumerate(items)]
