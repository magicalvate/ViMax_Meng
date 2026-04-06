"""
Quick debug script to test ImageGeneratorNanobananaGoogleAPI with Google API.
Usage: uv run python debug_nanobanana_google.py
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


async def test_list_models():
    """List available image generation models to verify API connectivity."""
    from google import genai

    client = genai.Client(api_key=GOOGLE_API_KEY)
    print("\n=== Available models (image generation related) ===")
    models = client.models.list()
    for m in models:
        if "image" in m.name.lower() or "imagen" in m.name.lower() or "flash" in m.name.lower():
            print(f"  {m.name}")
    print()


async def test_generate_image():
    """Try to generate a simple image with the nanobanana Google API tool."""
    from tools import ImageGeneratorNanobananaGoogleAPI

    generator = ImageGeneratorNanobananaGoogleAPI(api_key=GOOGLE_API_KEY)
    print(f"Using model: {generator.model}")

    result = await generator.generate_single_image(
        prompt="A simple red apple on a white background.",
        reference_image_paths=[],
        aspect_ratio="1:1",
    )
    print(f"Success! Image format={result.fmt}, ext={result.ext}, size={result.data.size}")
    result.save("/tmp/test_nanobanana_output.png")
    print("Saved to /tmp/test_nanobanana_output.png")


if __name__ == "__main__":
    if GOOGLE_API_KEY == "YOUR_GOOGLE_API_KEY_HERE":
        print("ERROR: Fill in your Google API key in configs/api_keys.yaml")
        exit(1)

    asyncio.run(test_list_models())
    asyncio.run(test_generate_image())
