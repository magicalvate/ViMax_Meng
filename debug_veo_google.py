"""
Quick debug script to test VideoGeneratorVeoGoogleAPI with Google API.
Usage: uv run python debug_veo_google.py
"""

import asyncio
import logging
import os
import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def load_api_key(platform: str) -> str:
    key_file = os.path.join(os.path.dirname(__file__), "configs/api_keys.yaml")
    with open(key_file) as f:
        keys = yaml.safe_load(f)
    return keys[platform]["api_key"]


GOOGLE_API_KEY = load_api_key("google")


async def test_t2v():
    """Test text-to-video generation."""
    from tools import VideoGeneratorVeoGoogleAPI

    generator = VideoGeneratorVeoGoogleAPI(api_key=GOOGLE_API_KEY)
    print(f"Using t2v model: {generator.t2v_model}")

    result = await generator.generate_single_video(
        prompt="A red apple slowly rotating on a white table, cinematic lighting.",
        reference_image_paths=[],
        aspect_ratio="16:9",
        duration=8,
    )
    print(f"Success! fmt={result.fmt}, ext={result.ext}, size={len(result.data)} bytes")
    result.save("/tmp/test_veo_output.mp4")
    print("Saved to /tmp/test_veo_output.mp4")


if __name__ == "__main__":
    asyncio.run(test_t2v())
