import playwright_scrape as ps


def test_to_int_count():
    assert ps._to_int_count("") == 0
    assert ps._to_int_count("12") == 12
    assert ps._to_int_count("1,234") == 1234
    assert ps._to_int_count("1.2K") == 1200
    assert ps._to_int_count("2M") == 2_000_000
    assert ps._to_int_count("3B") == 3_000_000_000


def test_extract_tweet_id_from_href():
    assert ps._extract_tweet_id_from_href("/user/status/123") == "123"
    assert ps._extract_tweet_id_from_href("https://x.com/user/status/456") == "456"
    assert ps._extract_tweet_id_from_href("") is None


def test_extract_username_from_href():
    assert ps._extract_username_from_href("/user/status/123") == "user"
    assert ps._extract_username_from_href("https://x.com/user/status/456") == "user"
    assert ps._extract_username_from_href("") is None
