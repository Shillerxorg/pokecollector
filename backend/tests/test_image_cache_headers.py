import hashlib
import unittest
from unittest.mock import MagicMock, patch

try:
    from fastapi import Request
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from api.images import get_card_image, get_set_image, _card_back_response, _set_fallback_response
    from database import Base
    from models import Card, Set, Setting

    DEPS = True
except ModuleNotFoundError:
    DEPS = False


def _make_request(headers=None):
    scope = {
        "type": "http",
        "method": "GET",
        "headers": [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in (headers or {}).items()],
    }
    return Request(scope)


@unittest.skipUnless(DEPS, "FastAPI/SQLAlchemy not installed in this environment")
class ImageCacheHeadersTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        # Enable English sync language
        self.db.add(Setting(key="tcgdex_sync_languages", value="en"))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)

    @patch("api.images._get_or_fetch", return_value=(b"card-image-bytes", "image/webp"))
    def test_card_image_returns_immutable_cache_control_and_etag(self, mock_fetch):
        card = Card(
            id="sv1-1_en",
            name="Bulbasaur",
            images_small="https://assets.example.test/sv1-1_small.webp",
            images_large="https://assets.example.test/sv1-1_large.webp",
            lang="en",
        )
        self.db.add(card)
        self.db.commit()

        expected_hash = hashlib.sha1(b"https://assets.example.test/sv1-1_small.webp").hexdigest()
        expected_etag = f'"{expected_hash}"'

        response = get_card_image("sv1-1_en", "small", db=self.db)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.body, b"card-image-bytes")
        self.assertEqual(response.headers["cache-control"], "public, max-age=2592000, immutable")
        self.assertEqual(response.headers["etag"], expected_etag)

    @patch("api.images._get_or_fetch")
    def test_card_image_returns_304_when_if_none_match_matches(self, mock_fetch):
        card = Card(
            id="sv1-1_en",
            name="Bulbasaur",
            images_small="https://assets.example.test/sv1-1_small.webp",
            images_large="https://assets.example.test/sv1-1_large.webp",
            lang="en",
        )
        self.db.add(card)
        self.db.commit()

        expected_hash = hashlib.sha1(b"https://assets.example.test/sv1-1_small.webp").hexdigest()
        expected_etag = f'"{expected_hash}"'
        request = _make_request({"if-none-match": expected_etag})

        response = get_card_image("sv1-1_en", "small", request=request, db=self.db)

        self.assertEqual(response.status_code, 304)
        self.assertEqual(response.body, b"")
        self.assertEqual(response.headers["etag"], expected_etag)
        self.assertEqual(response.headers["cache-control"], "public, max-age=2592000, immutable")
        # Should not fetch blob when ETag matches
        mock_fetch.assert_not_called()

    @patch("api.images._get_or_fetch")
    def test_card_image_accepts_weak_etag_and_comma_separated_if_none_match(self, mock_fetch):
        card = Card(
            id="sv1-1_en",
            name="Bulbasaur",
            images_small="https://assets.example.test/sv1-1_small.webp",
            images_large="https://assets.example.test/sv1-1_large.webp",
            lang="en",
        )
        self.db.add(card)
        self.db.commit()

        expected_hash = hashlib.sha1(b"https://assets.example.test/sv1-1_small.webp").hexdigest()
        expected_etag = f'"{expected_hash}"'
        weak_header = f'W/"other-etag", W/{expected_etag}'
        request = _make_request({"if-none-match": weak_header})

        response = get_card_image("sv1-1_en", "small", request=request, db=self.db)

        self.assertEqual(response.status_code, 304)
        self.assertEqual(response.headers["etag"], expected_etag)
        mock_fetch.assert_not_called()

    @patch("api.images._get_or_fetch_custom_image", return_value=(b"custom-card-bytes", "image/png"))
    def test_custom_card_image_returns_revalidation_cache_control(self, mock_custom_fetch):
        card = Card(
            id="custom-1_en",
            name="Custom Card",
            is_custom=True,
            images_small="https://assets.example.test/custom_small.png",
            images_large="https://assets.example.test/custom_large.png",
            lang="en",
        )
        self.db.add(card)
        self.db.commit()

        expected_hash = hashlib.sha1(b"https://assets.example.test/custom_small.png").hexdigest()
        expected_etag = f'"{expected_hash}"'

        response = get_card_image("custom-1_en", "small", db=self.db)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.body, b"custom-card-bytes")
        self.assertEqual(response.headers["cache-control"], "public, max-age=3600, must-revalidate")
        self.assertEqual(response.headers["etag"], expected_etag)

    @patch("api.images._get_or_fetch", return_value=(b"set-logo-bytes", "image/png"))
    def test_set_image_returns_immutable_cache_control_and_etag(self, mock_fetch):
        s = Set(
            id="sv1_en",
            tcg_set_id="sv1",
            name="Scarlet & Violet",
            images_logo="https://assets.example.test/sv1_logo.png",
            lang="en",
        )
        self.db.add(s)
        self.db.commit()

        expected_hash = hashlib.sha1(b"https://assets.example.test/sv1_logo.png").hexdigest()
        expected_etag = f'"{expected_hash}"'

        response = get_set_image("sv1_en", "logo", db=self.db)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.body, b"set-logo-bytes")
        self.assertEqual(response.headers["cache-control"], "public, max-age=2592000, immutable")
        self.assertEqual(response.headers["etag"], expected_etag)

    @patch("api.images._get_or_fetch")
    def test_set_image_returns_304_when_if_none_match_matches(self, mock_fetch):
        s = Set(
            id="sv1_en",
            tcg_set_id="sv1",
            name="Scarlet & Violet",
            images_logo="https://assets.example.test/sv1_logo.png",
            lang="en",
        )
        self.db.add(s)
        self.db.commit()

        expected_hash = hashlib.sha1(b"https://assets.example.test/sv1_logo.png").hexdigest()
        expected_etag = f'"{expected_hash}"'
        request = _make_request({"if-none-match": expected_etag})

        response = get_set_image("sv1_en", "logo", request=request, db=self.db)

        self.assertEqual(response.status_code, 304)
        self.assertEqual(response.body, b"")
        self.assertEqual(response.headers["etag"], expected_etag)
        self.assertEqual(response.headers["cache-control"], "public, max-age=2592000, immutable")
        mock_fetch.assert_not_called()

    def test_card_back_fallback_redirect_has_cache_control(self):
        resp = _card_back_response()
        self.assertEqual(resp.status_code, 307)
        self.assertEqual(resp.headers["cache-control"], "public, max-age=86400")
        self.assertEqual(resp.headers["location"], "/cardback.jpg")

    def test_set_fallback_response_has_immutable_cache_control(self):
        resp = _set_fallback_response()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["cache-control"], "public, max-age=2592000, immutable")


if __name__ == "__main__":
    unittest.main()
