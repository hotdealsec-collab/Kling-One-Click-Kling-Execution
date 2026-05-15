
import base64
import json
import os
import re
import time
import jwt
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
LOG_FILE = "logs/kling_take_log.csv"

os.makedirs("logs", exist_ok=True)
os.makedirs("outputs/videos", exist_ok=True)
os.makedirs("outputs/images", exist_ok=True)


def safe_filename(name: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9._-]+", "_", (name or "").strip())
    return name[:140] or "item"


def get_nested(data: Dict, path: str, default=None):
    if not path:
        return default
    current = data
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except Exception:
                return default
        else:
            return default
    return current


def replace_placeholders(template: str, values: Dict[str, str]) -> str:
    out = template
    for key, value in values.items():
        out = out.replace("{{" + key + "}}", value or "")
    return out


def normalize_image_url(src: str, base_url: str) -> Optional[str]:
    if not src:
        return None
    src = src.strip()
    if src.startswith("//"):
        src = "https:" + src
    elif src.startswith("/"):
        src = urljoin(base_url, src)
    src = src.replace("&amp;", "&")
    parsed = urlparse(src)
    if parsed.scheme not in ("http", "https"):
        return None
    return src


def extract_product_images(product_url: str, timeout: int = 25) -> Dict:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
        )
    }
    res = requests.get(product_url, headers=headers, timeout=timeout)
    res.raise_for_status()
    html = res.text
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(" ", strip=True)
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)

    candidates: List[Dict] = []

    def add_image(url: str, source: str, alt: str = ""):
        nurl = normalize_image_url(url, product_url)
        if not nurl:
            return
        lower = nurl.lower()
        if any(skip in lower for skip in ["favicon", "sprite"]):
            return
        candidates.append({"url": nurl, "source": source, "alt": alt or ""})

    # JSON-LD product images
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            raw = script.string or script.get_text() or ""
            data = json.loads(raw)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                t = item.get("@type")
                if t == "Product" or (isinstance(t, list) and "Product" in t):
                    imgs = item.get("image")
                    if isinstance(imgs, str):
                        add_image(imgs, "jsonld_product")
                    elif isinstance(imgs, list):
                        for img in imgs:
                            if isinstance(img, str):
                                add_image(img, "jsonld_product")
        except Exception:
            pass

    # Regex fallback for direct image urls in html
    pattern = r'https?:\\?/\\?/[^"\']+\.(?:jpg|jpeg|png|webp)'
    for m in re.finditer(pattern, html, flags=re.I):
        url = m.group(0).replace("\\/", "/")
        add_image(url, "html_regex")

    # All img tags
    for img in soup.find_all("img"):
        srcs = []
        for attr in ["src", "data-src", "data-original", "data-image"]:
            val = img.get(attr)
            if val:
                srcs.append(val)
        srcset = img.get("srcset") or img.get("data-srcset")
        if srcset:
            parts = [p.strip().split(" ")[0] for p in srcset.split(",") if p.strip()]
            srcs.extend(parts)
        alt = img.get("alt", "")
        for src in srcs:
            add_image(src, "img_tag", alt)

    seen = set()
    deduped = []
    for item in candidates:
        key = item["url"].split("?")[0]
        if key in seen:
            continue
        seen.add(key)
        item["id"] = f"use_{len(deduped) + 1}"
        deduped.append(item)

    return {"title": title, "html": html, "images": deduped}


def download_image(url: str, timeout: int = 25) -> Optional[bytes]:
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        if "image" not in ctype and not url.lower().split("?")[0].endswith(IMAGE_EXTS):
            return None
        return r.content
    except Exception:
        return None


def guess_mime(url: str) -> str:
    lower = url.lower().split("?")[0]
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".webp"):
        return "image/webp"
    return "image/jpeg"


def bytes_to_data_url(image_bytes: bytes, mime: str = "image/jpeg") -> str:
    return f"data:{mime};base64," + base64.b64encode(image_bytes).decode("utf-8")


def encode_image_to_base64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")


def generate_kling_jwt(access_key: str, secret_key: str, ttl_seconds: int = 1800) -> str:
    """Generate Kling API JWT from Access Key and Secret Key.

    Kling official API authentication commonly uses:
    payload = {"iss": access_key, "exp": now + ttl, "nbf": now - 5}
    signed with HS256 using secret_key.
    """
    now = int(time.time())
    headers = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": access_key,
        "exp": now + int(ttl_seconds),
        "nbf": now - 5,
    }
    token = jwt.encode(payload, secret_key, algorithm="HS256", headers=headers)
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token


def save_video_from_url(url: str, output_dir: str, filename_hint: str, session=None) -> Optional[str]:
    try:
        sess = session or requests.Session()
        r = sess.get(url, timeout=180)
        r.raise_for_status()
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, safe_filename(filename_hint) + ".mp4")
        with open(path, "wb") as f:
            f.write(r.content)
        return path
    except Exception:
        return None


def parse_json_from_text(text: str) -> Dict:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise ValueError(f"Could not parse JSON from model output: {text[:500]}")


SCHEMA_NOTE = """
Return strict JSON only. Do not wrap in markdown.
Schema:
{
  "overall_notes": "short Korean explanation",
  "images": [
    {
      "id": "use_22",
      "image_type": "model_shot | lifestyle | single_product | multi_product | collage | detail_shot | unclear",
      "relevance_score": 0,
      "lifestyle_score": 0,
      "product_visibility_score": 0,
      "risk_score": 0,
      "recommended_role": "start | end | either | reference_only | not_recommended",
      "reason": "Korean short reason",
      "cautions": "Korean short caution"
    }
  ],
  "pairs": [
    {
      "rank": 1,
      "start_image_id": "use_22",
      "end_image_id": "use_27",
      "pair_score": 0,
      "strategy": "Lifestyle First | Balanced | Product Focus",
      "reason": "Korean reason",
      "cautions": "Korean caution"
    }
  ]
}
Rules:
- Never recommend the same image as both start and end.
- Prefer model_shot / lifestyle images when strategy is Lifestyle First and product is visible.
- Avoid unrelated/default/common images if detected.
- Avoid pair_score below 60 unless no better option exists.
"""


def analyze_images_and_pairs(openai_api_key: str, model: str, product_title: str, product_url: str, strategy: str, images: List[Dict]) -> Dict:
    client = OpenAI(api_key=openai_api_key)
    content = [{
        "type": "text",
        "text": f"""
You are an ecommerce creative director for SocksLover.
Analyze product page images and recommend the best 2-image start/end frame pair for Kling video generation.

Product title: {product_title}
Product URL: {product_url}
Strategy: {strategy}

Important context:
- This video will be used as Shopify product page support media, not as the main product image.
- Lifestyle First means model wearing/holding/using product is preferred if the product remains visible.
- Default/common/unrelated images should be penalized or excluded.
- Reply in Korean for reasons/cautions.

{SCHEMA_NOTE}
"""
    }]

    for img in images:
        b = img.get("bytes") or download_image(img["url"])
        img["bytes"] = b
        if not b:
            continue
        content.append({"type": "text", "text": f"Image ID: {img['id']} / source: {img.get('source','')} / alt: {img.get('alt','')}"})
        content.append({"type": "image_url", "image_url": {"url": bytes_to_data_url(b, guess_mime(img["url"]))}})

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        temperature=0.2,
        max_tokens=2600,
    )
    return parse_json_from_text(resp.choices[0].message.content)


def generate_kling_prompt(openai_api_key: str, model: str, product_title: str, strategy: str, video_type: str,
                          start_id: str, end_id: str, pair_reason: str, color_lock: str, motion_strength: str) -> Dict:
    client = OpenAI(api_key=openai_api_key)
    user_prompt = f"""
Create a Kling image-to-video prompt for a Shopify product support video.

Product: {product_title}
Strategy: {strategy}
Video type: {video_type}
Start image ID: {start_id}
End image ID: {end_id}
Pair reason: {pair_reason}
Color Lock Level: {color_lock}
Motion Strength: {motion_strength}

Requirements:
- No text, no captions, no logos, no letters in the video.
- This is a support media asset for a Shopify product page.
- The product should remain the hero.
- Include Product Lock and Model Lock.
- If Color Lock is Strong or Very Strong, strongly prevent color shift.
- Reply in JSON only:
{{
  "scene_card": {{
    "goal": "...",
    "camera_motion": "...",
    "lighting": "...",
    "background": "...",
    "product_lock": "...",
    "model_lock": "...",
    "cautions": "..."
  }},
  "main_prompt": "...",
  "negative_prompt": "..."
}}
"""
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": user_prompt}],
        temperature=0.25,
        max_tokens=1800,
    )
    return parse_json_from_text(resp.choices[0].message.content)


class KlingGenericClient:
    def __init__(
        self,
        create_url: str,
        status_url_template: str,
        auth_mode: str = "kling_jwt",
        access_key: str = "",
        secret_key: str = "",
        api_key: str = "",
        custom_header_name: str = "Authorization",
        extra_headers_json: str = "{}",
        jwt_ttl_seconds: int = 1800,
    ):
        self.access_key = (access_key or "").strip()
        self.secret_key = (secret_key or "").strip()
        self.api_key = (api_key or "").strip()
        self.create_url = (create_url or "").strip()
        self.status_url_template = (status_url_template or "").strip()
        self.auth_mode = auth_mode
        self.custom_header_name = custom_header_name or "Authorization"
        self.jwt_ttl_seconds = int(jwt_ttl_seconds)
        self.session = requests.Session()
        self.session.headers.update(self._headers(extra_headers_json))

    def _headers(self, extra_headers_json: str) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}

        if self.auth_mode == "kling_jwt":
            if not self.access_key or not self.secret_key:
                raise ValueError("Kling JWT 인증에는 Access Key와 Secret Key가 모두 필요합니다.")
            token = generate_kling_jwt(self.access_key, self.secret_key, self.jwt_ttl_seconds)
            headers["Authorization"] = f"Bearer {token}"
        elif self.api_key:
            if self.auth_mode == "bearer":
                headers["Authorization"] = f"Bearer {self.api_key}"
            elif self.auth_mode == "x-api-key":
                headers["x-api-key"] = self.api_key
            elif self.auth_mode == "custom":
                headers[self.custom_header_name] = self.api_key

        try:
            extra = json.loads(extra_headers_json or "{}")
            if isinstance(extra, dict):
                headers.update({str(k): str(v) for k, v in extra.items()})
        except Exception:
            pass
        return headers

    def build_payload(self, template: str, values: Dict[str, str]) -> Dict:
        rendered = replace_placeholders(template, values)
        return json.loads(rendered)

    def submit(self, payload: Dict) -> Dict:
        r = self.session.post(self.create_url, json=payload, timeout=180)
        if not r.ok:
            raise RuntimeError(
                f"HTTP {r.status_code} Error from Kling create endpoint. "
                f"Response body: {r.text[:2000]}"
            )
        try:
            return r.json()
        except Exception:
            raise RuntimeError(f"Kling create endpoint returned non-JSON response: {r.text[:1000]}")

    def poll_until_done(self, task_id: str, status_path: str, result_url_path: str,
                        poll_seconds: int = 10, max_polls: int = 60) -> Tuple[str, Optional[str], Dict]:
        final_json = {}
        result_url = None
        status = "unknown"
        for _ in range(max_polls):
            url = self.status_url_template.replace("{{TASK_ID}}", str(task_id))
            r = self.session.get(url, timeout=120)
            if not r.ok:
                raise RuntimeError(
                    f"HTTP {r.status_code} Error from Kling status endpoint. "
                    f"Response body: {r.text[:2000]}"
                )
            try:
                final_json = r.json()
            except Exception:
                raise RuntimeError(f"Kling status endpoint returned non-JSON response: {r.text[:1000]}")
            status = str(get_nested(final_json, status_path, "") or "").lower()
            result_url = get_nested(final_json, result_url_path)
            if status in {"completed", "succeed", "success", "done", "finished"}:
                return status, result_url, final_json
            if status in {"failed", "error", "cancelled", "canceled"}:
                return status, result_url, final_json
            time.sleep(poll_seconds)
        return status or "timeout", result_url, final_json


DEFAULT_KLING_PAYLOAD = json.dumps({
    "model_name": "{{MODEL}}",
    "mode": "pro",
    "duration": "{{DURATION}}",
    "image": "{{START_IMAGE_BASE64}}",
    "image_tail": "{{END_IMAGE_BASE64}}",
    "prompt": "{{PROMPT}}"
}, ensure_ascii=False, indent=2)

# Alternative template for providers that use "model" instead of "model_name".
ALT_KLING_PAYLOAD_MODEL_FIELD = json.dumps({
    "model": "{{MODEL}}",
    "mode": "pro",
    "duration": "{{DURATION}}",
    "image": "{{START_IMAGE_BASE64}}",
    "image_tail": "{{END_IMAGE_BASE64}}",
    "prompt": "{{PROMPT}}"
}, ensure_ascii=False, indent=2)


st.set_page_config(page_title="SocksLover Kling Prompt Assistant v5.0 Lite", layout="wide")
st.title("SocksLover Kling Prompt Assistant v5.2 – Kling Payload Fix")
st.caption("Kling JWT 인증 + image/image_tail 기본 payload를 적용한 단일 파일 버전입니다.")

for key, value in {
    "extracted": None,
    "analysis": None,
    "analysis_candidates": None,
    "selected_pair": None,
    "prompt_bundle": None,
    "last_result": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = value

with st.sidebar:
    st.header("OpenAI Settings")
    openai_api_key = st.text_input("OpenAI API Key", value=os.getenv("OPENAI_API_KEY", ""), type="password")
    openai_model = st.text_input("OpenAI Model", value=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))

    st.header("Kling API Settings")
    auth_mode = st.selectbox("Auth Mode", ["kling_jwt", "bearer", "x-api-key", "custom"], index=0)

    kling_access_key = ""
    kling_secret_key = ""
    kling_api_key = ""

    if auth_mode == "kling_jwt":
        kling_access_key = st.text_input("Kling Access Key", value=os.getenv("KLING_ACCESS_KEY", ""), type="password")
        kling_secret_key = st.text_input("Kling Secret Key", value=os.getenv("KLING_SECRET_KEY", ""), type="password")
        jwt_ttl_seconds = st.number_input("JWT TTL seconds", min_value=300, max_value=7200, value=1800, step=300)
    else:
        kling_api_key = st.text_input("Kling API Key", value=os.getenv("KLING_API_KEY", ""), type="password")
        jwt_ttl_seconds = 1800

    create_url = st.text_input("Create Endpoint URL", value=os.getenv("KLING_CREATE_URL", ""))
    status_url_template = st.text_input("Status Endpoint URL Template", value=os.getenv("KLING_STATUS_URL_TEMPLATE", ""))
    custom_header_name = st.text_input("Custom Header Name", value="Authorization")
    extra_headers_json = st.text_area("Extra Headers JSON", value="{}", height=80)

    st.subheader("JSON Response Paths")
    task_id_path = st.text_input("Task ID Path", value=os.getenv("KLING_TASK_ID_PATH", "data.task_id"))
    status_path = st.text_input("Status Path", value=os.getenv("KLING_STATUS_PATH", "data.status"))
    result_url_path = st.text_input("Result Video URL Path", value=os.getenv("KLING_RESULT_URL_PATH", "data.video_url"))

    st.subheader("Polling")
    poll_seconds = st.number_input("Poll interval (seconds)", min_value=3, max_value=60, value=10)
    max_polls = st.number_input("Max polls", min_value=1, max_value=200, value=60)

st.subheader("1) Product URL → Image Extraction")
c1, c2 = st.columns([4, 1])
with c1:
    product_url = st.text_input("Shopify Product URL", placeholder="https://sockslover.net/products/...")
with c2:
    fetch_clicked = st.button("Fetch Images", type="primary", use_container_width=True)

if fetch_clicked:
    if not product_url:
        st.error("상품 URL을 입력해주세요.")
    else:
        try:
            extracted = extract_product_images(product_url)
            st.session_state["extracted"] = extracted
            st.session_state["analysis"] = None
            st.session_state["selected_pair"] = None
            st.session_state["prompt_bundle"] = None
            st.success(f"이미지 {len(extracted['images'])}장을 추출했습니다.")
        except Exception as e:
            st.error(f"이미지 추출 실패: {e}")

extracted = st.session_state["extracted"]

if extracted:
    st.info(f"상품명: {extracted['title'] or '(제목 없음)'} / 전체 추출 이미지 수: {len(extracted['images'])}")
    default_start_idx = 22 if len(extracted["images"]) >= 22 else 1
    a1, a2, a3 = st.columns(3)
    with a1:
        analysis_start_index = st.number_input("분석 시작 이미지 번호", min_value=1, max_value=max(1, len(extracted["images"])), value=default_start_idx)
    with a2:
        max_analysis_images = st.number_input("Vision 분석 최대 이미지 수", min_value=2, max_value=20, value=12)
    with a3:
        strategy = st.selectbox("추천 전략", ["Lifestyle First", "Balanced", "Product Focus"])

    start_idx_zero = max(0, int(analysis_start_index) - 1)
    analysis_candidates = extracted["images"][start_idx_zero:start_idx_zero + int(max_analysis_images)]
    st.session_state["analysis_candidates"] = analysis_candidates

    if analysis_candidates:
        st.caption(f"Vision 분석 대상: {analysis_candidates[0]['id']} ~ {analysis_candidates[-1]['id']} / 총 {len(analysis_candidates)}장")

    with st.expander("전체 추출 이미지 보기"):
        cols = st.columns(4)
        for idx, img in enumerate(extracted["images"]):
            b = img.get("bytes") or download_image(img["url"])
            extracted["images"][idx]["bytes"] = b
            with cols[idx % 4]:
                if b:
                    st.image(b, caption=f"{img['id']}\n{img['source']}", use_container_width=True)
                else:
                    st.write(f"{img['id']} - 이미지 로드 실패")

    if st.button("2) GPT Vision 분석 & Pair 추천", use_container_width=True):
        if not openai_api_key:
            st.error("OpenAI API Key를 입력해주세요.")
        else:
            try:
                with st.spinner("GPT Vision 분석 중..."):
                    for img in analysis_candidates:
                        if not img.get("bytes"):
                            img["bytes"] = download_image(img["url"])
                    analysis = analyze_images_and_pairs(
                        openai_api_key=openai_api_key,
                        model=openai_model,
                        product_title=extracted["title"],
                        product_url=product_url,
                        strategy=strategy,
                        images=analysis_candidates,
                    )
                    st.session_state["analysis"] = analysis
                st.success("Vision 분석이 완료되었습니다.")
            except Exception as e:
                st.error(f"Vision 분석 실패: {e}")

analysis = st.session_state["analysis"]

if analysis and extracted:
    st.subheader("3) Vision 분석 결과")
    if analysis.get("overall_notes"):
        st.info(analysis["overall_notes"])

    analysis_map = {item["id"]: item for item in analysis.get("images", [])}
    candidates = st.session_state["analysis_candidates"] or []
    cols = st.columns(4)
    for idx, img in enumerate(candidates):
        a = analysis_map.get(img["id"], {})
        with cols[idx % 4]:
            if img.get("bytes"):
                st.image(img["bytes"], caption=img["id"], use_container_width=True)
            st.caption(f"type: {a.get('image_type','-')}")
            st.caption(f"relevance: {a.get('relevance_score','-')} / lifestyle: {a.get('lifestyle_score','-')} / visibility: {a.get('product_visibility_score','-')}")
            st.caption(f"role: {a.get('recommended_role','-')}")
            if a.get("reason"):
                st.write(f"**사유**: {a.get('reason')}")
            if a.get("cautions"):
                st.write(f"**주의**: {a.get('cautions')}")

    st.subheader("4) Pair TOP 3")
    pairs = analysis.get("pairs", [])
    if not pairs:
        st.warning("추천 pair가 없습니다.")
    else:
        pair_labels = [
            f"TOP {p.get('rank')} | {p.get('start_image_id')} → {p.get('end_image_id')} | score {p.get('pair_score')}"
            for p in pairs
        ]
        chosen_label = st.radio("추천 pair 선택", pair_labels)
        chosen_pair = pairs[pair_labels.index(chosen_label)]
        st.session_state["selected_pair"] = chosen_pair
        st.write(f"**선택된 Pair**: {chosen_pair['start_image_id']} → {chosen_pair['end_image_id']}")
        st.write(f"**추천 사유**: {chosen_pair.get('reason','-')}")
        st.write(f"**주의사항**: {chosen_pair.get('cautions','-')}")

selected_pair = st.session_state["selected_pair"]

if selected_pair and extracted:
    st.subheader("5) Scene Card / Prompt 생성")
    p1, p2, p3, p4 = st.columns(4)
    with p1:
        video_type = st.selectbox("Video Type", ["Shopify Product Video", "SNS Short Video", "Ad Creative Test", "Brand Mood Clip"])
    with p2:
        color_lock = st.selectbox("Color Lock", ["Normal", "Strong", "Very Strong"])
    with p3:
        motion_strength = st.selectbox("Motion Strength", ["Gentle", "Balanced", "Visible"])
    with p4:
        usage_label = st.selectbox("Usage Label", ["Shopify support media", "SNS", "Ad test", "Review only"])

    if st.button("Generate Kling Prompt", use_container_width=True):
        if not openai_api_key:
            st.error("OpenAI API Key를 입력해주세요.")
        else:
            try:
                with st.spinner("프롬프트 생성 중..."):
                    pb = generate_kling_prompt(
                        openai_api_key=openai_api_key,
                        model=openai_model,
                        product_title=extracted["title"],
                        strategy=selected_pair.get("strategy", "Lifestyle First"),
                        video_type=video_type,
                        start_id=selected_pair["start_image_id"],
                        end_id=selected_pair["end_image_id"],
                        pair_reason=selected_pair.get("reason", ""),
                        color_lock=color_lock,
                        motion_strength=motion_strength,
                    )
                    st.session_state["prompt_bundle"] = {
                        "scene_card": pb.get("scene_card", {}),
                        "main_prompt": pb.get("main_prompt", ""),
                        "negative_prompt": pb.get("negative_prompt", ""),
                        "video_type": video_type,
                        "color_lock": color_lock,
                        "motion_strength": motion_strength,
                        "usage_label": usage_label,
                    }
                st.success("Kling 프롬프트 생성 완료.")
            except Exception as e:
                st.error(f"프롬프트 생성 실패: {e}")

prompt_bundle = st.session_state["prompt_bundle"]

if prompt_bundle and extracted and selected_pair:
    st.subheader("6) Scene Card")
    st.json(prompt_bundle["scene_card"])

    q1, q2 = st.columns(2)
    with q1:
        main_prompt = st.text_area("Main Prompt", value=prompt_bundle["main_prompt"], height=260)
    with q2:
        negative_prompt = st.text_area("Negative Prompt", value=prompt_bundle["negative_prompt"], height=260)

    prompt_bundle["main_prompt"] = main_prompt
    prompt_bundle["negative_prompt"] = negative_prompt

    st.subheader("7) One Click Kling Execution")
    k1, k2, k3 = st.columns(3)
    with k1:
        kling_model = st.text_input("Kling Model", value="kling-v3-0")
    with k2:
        kling_duration = st.selectbox("Duration", ["5", "10", "15"], index=0)
    with k3:
        aspect_ratio = st.selectbox("Aspect Ratio", ["1:1", "4:5", "9:16", "16:9"], index=0)

    payload_template = st.text_area("Kling Request JSON Template", value=DEFAULT_KLING_PAYLOAD, height=220)
    with st.expander("Kling payload template help"):
        st.markdown("""
**권장 기본값**

Start/End frame 방식은 일반적으로 `image`와 `image_tail`을 사용합니다.  
이전 버전의 `mode: start_end_frame`, `input.start_image_base64`, `input.end_image_base64` 구조는 400 Bad Request가 날 가능성이 높습니다.

기본 템플릿:

```json
{
  "model_name": "{{MODEL}}",
  "mode": "pro",
  "duration": "{{DURATION}}",
  "image": "{{START_IMAGE_BASE64}}",
  "image_tail": "{{END_IMAGE_BASE64}}",
  "prompt": "{{PROMPT}}"
}
```

응답 body에 `unknown field model_name` 같은 메시지가 나오면 `model_name`을 `model`로 바꿔보세요.
""")
        st.code(ALT_KLING_PAYLOAD_MODEL_FIELD, language="json")

    candidate_map = {img["id"]: img for img in (st.session_state["analysis_candidates"] or [])}
    start_img = candidate_map.get(selected_pair["start_image_id"])
    end_img = candidate_map.get(selected_pair["end_image_id"])

    if start_img and end_img:
        z1, z2 = st.columns(2)
        with z1:
            if start_img.get("bytes"):
                st.image(start_img["bytes"], caption=f"Start: {start_img['id']}", use_container_width=True)
        with z2:
            if end_img.get("bytes"):
                st.image(end_img["bytes"], caption=f"End: {end_img['id']}", use_container_width=True)

        if st.button("Generate in Kling", type="primary", use_container_width=True):
            missing_auth = False
            if auth_mode == "kling_jwt":
                missing_auth = (not kling_access_key or not kling_secret_key)
            else:
                missing_auth = (not kling_api_key)

            if missing_auth or not create_url or not status_url_template:
                st.error("Kling 인증 정보 / Create Endpoint URL / Status Endpoint URL Template를 입력해주세요.")
            else:
                try:
                    client = KlingGenericClient(
                        create_url=create_url,
                        status_url_template=status_url_template,
                        auth_mode=auth_mode,
                        access_key=kling_access_key,
                        secret_key=kling_secret_key,
                        api_key=kling_api_key,
                        custom_header_name=custom_header_name,
                        extra_headers_json=extra_headers_json,
                        jwt_ttl_seconds=int(jwt_ttl_seconds),
                    )
                    values = {
                        "MODEL": kling_model,
                        "PROMPT": prompt_bundle["main_prompt"],
                        "NEGATIVE_PROMPT": prompt_bundle["negative_prompt"],
                        "DURATION": str(kling_duration),
                        "ASPECT_RATIO": aspect_ratio,
                        "START_IMAGE_BASE64": encode_image_to_base64(start_img["bytes"]),
                        "END_IMAGE_BASE64": encode_image_to_base64(end_img["bytes"]),
                    }
                    payload = client.build_payload(payload_template, values)
                    with st.status("Submitting to Kling API...", expanded=True) as status_box:
                        submit_json = client.submit(payload)
                        st.json(submit_json)
                        task_id = get_nested(submit_json, task_id_path)
                        if not task_id:
                            raise ValueError(f"task_id path에서 task id를 읽지 못했습니다: {task_id_path}")
                        status_box.write(f"Task submitted: {task_id}")
                        final_status, result_url, final_json = client.poll_until_done(
                            task_id=task_id,
                            status_path=status_path,
                            result_url_path=result_url_path,
                            poll_seconds=int(poll_seconds),
                            max_polls=int(max_polls),
                        )
                        status_box.write(f"Final status: {final_status}")
                        st.json(final_json)
                        status_box.update(label="Completed", state="complete")

                    downloaded_path = None
                    if result_url:
                        filename_hint = safe_filename(f"{extracted['title']}_{selected_pair['start_image_id']}_{selected_pair['end_image_id']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
                        downloaded_path = save_video_from_url(result_url, "outputs/videos", filename_hint, client.session)
                        st.success("Kling 영상 생성 완료")
                        st.video(result_url)
                        if downloaded_path:
                            st.info(f"로컬 저장: {downloaded_path}")

                    row = {
                        "created_at": datetime.now().isoformat(timespec="seconds"),
                        "product_title": extracted["title"],
                        "product_url": product_url,
                        "pair_start": selected_pair["start_image_id"],
                        "pair_end": selected_pair["end_image_id"],
                        "strategy": selected_pair.get("strategy", ""),
                        "pair_score": selected_pair.get("pair_score", ""),
                        "usage_label": prompt_bundle.get("usage_label", ""),
                        "video_type": prompt_bundle.get("video_type", ""),
                        "color_lock": prompt_bundle.get("color_lock", ""),
                        "motion_strength": prompt_bundle.get("motion_strength", ""),
                        "kling_model": kling_model,
                        "duration": kling_duration,
                        "aspect_ratio": aspect_ratio,
                        "task_id": task_id,
                        "status": final_status,
                        "result_url": result_url or "",
                        "downloaded_path": downloaded_path or "",
                    }
                    df_new = pd.DataFrame([row])
                    if os.path.exists(LOG_FILE):
                        df_old = pd.read_csv(LOG_FILE)
                        df = pd.concat([df_old, df_new], ignore_index=True)
                    else:
                        df = df_new
                    df.to_csv(LOG_FILE, index=False)
                    st.success("Take Log 저장 완료")
                except Exception as e:
                    st.error(f"Kling 실행 실패: {e}")

    st.subheader("8) 재생성 프롬프트")
    issue_type = st.selectbox("문제 유형", ["없음", "색상 변형", "스트랩 변형", "형태 변형", "움직임 부족", "움직임 과함", "모델/손 왜곡"])
    fix_prompt_map = {
        "색상 변형": "Regenerate with stronger color consistency. The product color must remain exactly the same as the reference images. Do not shift the product color, saturation, or brightness.",
        "스트랩 변형": "Preserve the exact strap shape, strap color, and strap position. Do not add extra straps or remove existing straps.",
        "형태 변형": "Keep the product silhouette, flap shape, and structure consistent. Avoid any deformation or shape change.",
        "움직임 부족": "Add smooth but visible motion such as a slow dolly-in and slight parallax. Avoid a static image feel.",
        "움직임 과함": "Reduce movement intensity. Keep motion subtle, stable, and elegant with minimal body drift.",
        "모델/손 왜곡": "Keep the model pose and hands natural and realistic. Avoid distorted fingers, arms, and body shape.",
    }
    if issue_type != "없음":
        st.text_area("재생성용 수정 프롬프트", value=fix_prompt_map.get(issue_type, ""), height=120)

st.divider()
st.subheader("Take Log Table")
if os.path.exists(LOG_FILE):
    df = pd.read_csv(LOG_FILE)
    st.dataframe(df.sort_values("created_at", ascending=False), use_container_width=True)
else:
    st.caption("아직 take log가 없습니다.")
