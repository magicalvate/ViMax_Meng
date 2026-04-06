"""Unit tests for utils/ helpers."""
import asyncio
import base64
import os
import time
import pytest
from io import BytesIO
from unittest.mock import MagicMock, patch
from PIL import Image
from utils.rate_limiter import RateLimiter
from utils.image import image_path_to_b64, pil_to_b64, save_base64_image


class TestRateLimiter:
    async def test_no_limits_returns_immediately(self):
        rl = RateLimiter()
        # Should complete instantly without any sleeping
        await rl.acquire()
        assert len(rl.request_times) == 0  # disabled path skips recording

    async def test_records_request_times(self):
        rl = RateLimiter(max_requests_per_minute=100)
        await rl.acquire()
        assert len(rl.request_times) == 1

    async def test_multiple_acquires_within_limit(self):
        # 10 requests within a 60-per-minute limit → should not block
        rl = RateLimiter(max_requests_per_minute=60)
        for _ in range(5):
            await rl.acquire()
        assert len(rl.request_times) == 5

    async def test_min_delay_enforced(self):
        """With max_requests_per_minute=2, min_delay=30s. We mock asyncio.sleep to verify it's called."""
        rl = RateLimiter(max_requests_per_minute=2)
        assert rl.min_delay == 30.0

        sleep_calls = []

        async def fake_sleep(seconds):
            sleep_calls.append(seconds)

        with patch("utils.rate_limiter.asyncio.sleep", side_effect=fake_sleep):
            # Simulate two requests very close together
            rl.request_times = [time.time()]  # Fake one previous request just now
            await rl.acquire()

        # sleep should have been called to enforce the 30s min delay
        assert len(sleep_calls) >= 1

    async def test_daily_limit_triggers_sleep(self):
        """When daily limit is reached, acquire() should sleep."""
        rl = RateLimiter(max_requests_per_day=2)
        sleep_calls = []

        async def fake_sleep(seconds):
            sleep_calls.append(seconds)
            # Manually expire the old requests so the limiter unblocks
            rl.request_times.clear()

        now = time.time()
        rl.request_times = [now, now]  # 2 requests already used up the daily limit

        with patch("utils.rate_limiter.asyncio.sleep", side_effect=fake_sleep):
            await rl.acquire()

        assert len(sleep_calls) >= 1


class TestImagePathToB64:
    def test_returns_data_uri_with_mime(self, tmp_path):
        img = Image.new("RGB", (4, 4), color=(10, 20, 30))
        img_path = str(tmp_path / "test.png")
        img.save(img_path)

        result = image_path_to_b64(img_path, mime=True)
        assert result.startswith("data:image/png;base64,")

    def test_returns_raw_base64_without_mime(self, tmp_path):
        img = Image.new("RGB", (4, 4), color=(10, 20, 30))
        img_path = str(tmp_path / "test.png")
        img.save(img_path)

        result = image_path_to_b64(img_path, mime=False)
        # Should be decodable base64 without the data URI prefix
        assert not result.startswith("data:")
        decoded = base64.b64decode(result)
        assert len(decoded) > 0

    def test_decoded_content_matches_file(self, tmp_path):
        img = Image.new("RGB", (8, 8), color=(255, 128, 0))
        img_path = str(tmp_path / "test.png")
        img.save(img_path)

        b64 = image_path_to_b64(img_path, mime=False)
        decoded = base64.b64decode(b64)
        with open(img_path, "rb") as f:
            raw = f.read()
        assert decoded == raw


class TestPilToB64:
    def test_returns_data_uri_with_mime(self):
        img = Image.new("RGB", (4, 4), color=(0, 0, 255))
        result = pil_to_b64(img, mime=True)
        assert result.startswith("data:image/png;base64,")

    def test_returns_raw_base64_without_mime(self):
        img = Image.new("RGB", (4, 4), color=(0, 0, 255))
        result = pil_to_b64(img, mime=False)
        assert not result.startswith("data:")
        decoded = base64.b64decode(result)
        # Should decode to a valid PNG
        Image.open(BytesIO(decoded))

    def test_b64_encodes_actual_image_data(self):
        img = Image.new("RGB", (6, 6), color=(128, 64, 32))
        b64 = pil_to_b64(img, mime=False)
        buf = BytesIO(base64.b64decode(b64))
        loaded = Image.open(buf)
        assert loaded.size == (6, 6)


class TestSaveBase64Image:
    def test_saves_file_with_prefix(self, tmp_path):
        img = Image.new("RGB", (4, 4), color=(0, 255, 0))
        buf = BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        b64_with_prefix = f"data:image/png;base64,{b64}"

        dest = str(tmp_path / "out.png")
        save_base64_image(b64_with_prefix, dest)
        assert os.path.isfile(dest)
        loaded = Image.open(dest)
        assert loaded.size == (4, 4)

    def test_saves_file_without_prefix(self, tmp_path):
        img = Image.new("RGB", (4, 4), color=(255, 0, 0))
        buf = BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        dest = str(tmp_path / "out2.png")
        save_base64_image(b64, dest)
        assert os.path.isfile(dest)


class TestDownloadImage:
    def test_saves_content_to_file(self, tmp_path):
        from utils.image import download_image

        fake_content = b"\x89PNG\r\nfake_image_bytes"
        mock_response = MagicMock()
        mock_response.iter_content.return_value = [fake_content]
        mock_response.raise_for_status = MagicMock()

        dest = str(tmp_path / "downloaded.png")
        with patch("utils.image.requests.get", return_value=mock_response):
            download_image("http://example.com/image.png", dest)

        assert os.path.isfile(dest)
        assert open(dest, "rb").read() == fake_content
