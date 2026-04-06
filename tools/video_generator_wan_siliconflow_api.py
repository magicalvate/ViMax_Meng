import logging
import asyncio
import base64
import mimetypes
from typing import List, Literal
import aiohttp
from interfaces.video_output import VideoOutput


class VideoGeneratorWanSiliconflowAPI:
    def __init__(
        self,
        api_key: str,
        i2v_model: str = "Wan-AI/Wan2.2-I2V-A14B",
        t2v_model: str = "Wan-AI/Wan2.2-T2V-A14B",
        rate_limiter=None,
    ):
        self.api_key = api_key
        self.i2v_model = i2v_model
        self.t2v_model = t2v_model
        self.base_url = "https://api.siliconflow.cn/v1/video"

    def _image_to_b64(self, image_path: str) -> str:
        with open(image_path, "rb") as f:
            raw = f.read()
        # Detect actual format from file header, not extension
        if raw[:3] == b"\xff\xd8\xff":
            mime = "image/jpeg"
        elif raw[:8] == b"\x89PNG\r\n\x1a\n":
            mime = "image/png"
        else:
            mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
        return f"data:{mime};base64,{base64.b64encode(raw).decode()}"

    async def _submit(self, prompt: str, image_path: str = None) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.i2v_model if image_path else self.t2v_model,
            "prompt": prompt,
        }
        if image_path:
            payload["image"] = self._image_to_b64(image_path)

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/submit", headers=headers, json=payload
            ) as response:
                resp = await response.json()
                if "requestId" not in resp:
                    raise RuntimeError(f"Unexpected submit response: {resp}")
                return resp["requestId"]

    async def _poll(self, request_id: str) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        while True:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/status",
                    headers=headers,
                    json={"requestId": request_id},
                ) as response:
                    resp = await response.json()

            status = resp.get("status", "")
            if status == "Succeed":
                videos = resp.get("results", {}).get("videos", [])
                if not videos:
                    raise RuntimeError(f"No videos in response: {resp}")
                return videos[0]["url"]
            elif status == "Failed":
                raise RuntimeError(f"Video generation failed: {resp.get('reason', resp)}")
            else:
                logging.info(f"Video generation status: {status}, position: {resp.get('position', '?')}")
                await asyncio.sleep(5)

    async def generate_single_video(
        self,
        prompt: str,
        reference_image_paths: List[str],
        **kwargs,
    ) -> VideoOutput:
        image_path = reference_image_paths[0] if reference_image_paths else None
        logging.info(f"Submitting video generation task (model={'i2v' if image_path else 't2v'})...")
        request_id = await self._submit(prompt, image_path)
        logging.info(f"Task submitted, requestId={request_id}. Polling for result...")
        video_url = await self._poll(request_id)
        logging.info(f"Video generation complete: {video_url}")
        return VideoOutput(fmt="url", ext="mp4", data=video_url)
