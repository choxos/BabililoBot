"""Image generation service."""

import io
import logging
from typing import Optional
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass
class GeneratedImage:
    """Generated image result."""
    image_data: bytes
    prompt: str
    model: str


class ImageGenerationService:
    """Image generation using free services."""

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Get HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    async def close(self):
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def generate(self, prompt: str, style: str = "realistic") -> Optional[GeneratedImage]:
        """Generate image from text prompt.

        Uses Pollinations.ai (free, no API key required).

        Args:
            prompt: Text description of image
            style: Style modifier (realistic, anime, artistic, etc.)

        Returns:
            GeneratedImage with bytes data, or None if failed
        """
        try:
            # Apply style to prompt
            styled_prompt = self._apply_style(prompt, style)

            # Use Pollinations.ai (free image generation)
            # URL encode the prompt
            import urllib.parse
            encoded_prompt = urllib.parse.quote(styled_prompt)

            # Pollinations.ai endpoint
            url = f"https://image.pollinations.ai/prompt/{encoded_prompt}"

            response = await self.client.get(url, follow_redirects=True)

            if response.status_code == 200:
                return GeneratedImage(
                    image_data=response.content,
                    prompt=prompt,
                    model="pollinations",
                )
            else:
                logger.error(f"Image generation failed: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Image generation error: {e}")
            return None

    def _apply_style(self, prompt: str, style: str) -> str:
        """Apply style modifiers to prompt."""
        style_modifiers = {
            "realistic": "photorealistic, highly detailed, 8k, professional photography",
            "anime": "anime style, manga art, vibrant colors, detailed illustration",
            "artistic": "digital art, artistic, creative, masterpiece",
            "3d": "3D render, octane render, highly detailed, realistic lighting",
            "sketch": "pencil sketch, hand drawn, detailed line art",
            "watercolor": "watercolor painting, soft colors, artistic",
            "oil": "oil painting, classical art style, detailed brushwork",
            "cyberpunk": "cyberpunk style, neon lights, futuristic, sci-fi",
            "fantasy": "fantasy art, magical, ethereal, detailed illustration",
        }

        modifier = style_modifiers.get(style.lower(), "")
        if modifier:
            return f"{prompt}, {modifier}"
        return prompt

    def get_available_styles(self) -> list:
        """Get list of available style presets."""
        return [
            ("realistic", "📷 Realistic"),
            ("anime", "🎨 Anime"),
            ("artistic", "🖼️ Artistic"),
            ("3d", "🎮 3D Render"),
            ("sketch", "✏️ Sketch"),
            ("watercolor", "🎨 Watercolor"),
            ("oil", "🖌️ Oil Painting"),
            ("cyberpunk", "🌃 Cyberpunk"),
            ("fantasy", "✨ Fantasy"),
        ]

