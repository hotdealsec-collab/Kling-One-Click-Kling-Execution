# SocksLover Kling Prompt Assistant v5.2 – Kling Payload Fix

This is a single-file Streamlit app with:

- Kling Access Key / Secret Key JWT authentication
- Shopify product image extraction
- GPT Vision pair recommendation
- Kling prompt generation
- One Click Kling execution
- Better HTTP error response display
- Updated default Kling request payload for Start/End Frame usage

## v5.2 changes

The previous default payload used this structure:

```json
{
  "model": "{{MODEL}}",
  "mode": "start_end_frame",
  "input": {
    "start_image_base64": "...",
    "end_image_base64": "..."
  }
}
```

That structure can cause `400 Bad Request`.

v5.2 uses this default:

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

If Kling returns an error like `unknown field model_name`, change `model_name` to `model` in the app's editable JSON template.

## Suggested sidebar settings

```text
Auth Mode:
kling_jwt

Create Endpoint URL:
https://api.klingai.com/v1/videos/image2video

Status Endpoint URL Template:
https://api.klingai.com/v1/videos/{{TASK_ID}}

Task ID Path:
data.task_id

Status Path:
data.task_status

Result Video URL Path:
data.task_result.videos.0.url
```

If the JSON response is different, adjust the paths in the sidebar.

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

## GitHub / Streamlit Cloud upload

Upload:

```text
app.py
requirements.txt
.env.example
.gitignore
README.md
logs/
outputs/
```

No `utils/` folder is required.
