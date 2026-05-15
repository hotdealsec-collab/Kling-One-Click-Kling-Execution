# SocksLover Kling Prompt Assistant v5.0 Lite – One Click Kling Execution

This package is an **integrated Streamlit app**.
You do **not** need to run a separate helper app.

It includes the core MVP flow in one app:

- image extraction from Shopify product URL
- image card display
- GPT Vision image analysis
- Lifestyle First pair recommendation
- manual analysis start image index
- Scene Card generation
- Product Lock / Model Lock prompt generation
- Kling prompt generation
- **One Click Kling API execution**
- Take Log / regenerate prompt

---

## Main flow

```text
Product URL
→ Image extraction
→ Set analysis start index
→ GPT Vision analysis
→ Pair TOP 3 recommendation
→ Scene Card / Kling prompt generation
→ Generate in Kling
→ Status polling
→ Result preview
→ Take Log save
```

---

## Project structure

```text
sockslover-kling-prompt-assistant-v5-lite/
├── app.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── utils/
│   ├── __init__.py
│   ├── helpers.py
│   ├── vision.py
│   └── kling_client.py
├── logs/
└── outputs/
    ├── images/
    └── videos/
```

---

## Installation

```bash
pip install -r requirements.txt
streamlit run app.py
```

---

## Required inputs

### OpenAI
Used for:
- image type / suitability analysis
- pair recommendation
- Kling prompt generation

Sidebar:
- OpenAI API Key
- OpenAI model

### Kling API
Used for:
- create generation task
- poll generation status
- preview and save result

Sidebar:
- Kling API Key
- Create Endpoint URL
- Status Endpoint URL Template
- Task ID Path
- Status Path
- Result Video URL Path

Because Kling API schemas can evolve, the app uses:
- editable request JSON template
- configurable JSON response paths

This makes the app easier to adapt to your current Kling API docs.

---

## Default behavior

If the number of extracted images is 22 or more, the app suggests analysis start image number **22** by default.
This is based on the SocksLover pattern where early images may be default/common images.

You can manually change:
- analysis start image number
- max Vision analysis image count

---

## Important note about the Kling payload

The app includes a default payload template, but you may need to adjust it to match your current Kling API documentation.

Editable placeholders:
- `{{MODEL}}`
- `{{PROMPT}}`
- `{{NEGATIVE_PROMPT}}`
- `{{DURATION}}`
- `{{ASPECT_RATIO}}`
- `{{START_IMAGE_BASE64}}`
- `{{END_IMAGE_BASE64}}`

---

## GitHub upload

If uploading in the browser:
- create a new repository
- do **not** upload the ZIP itself
- upload the **contents** of the folder after unzipping

Files to upload:
- `app.py`
- `requirements.txt`
- `.env.example`
- `.gitignore`
- `README.md`
- `utils/`
- `logs/`
- `outputs/`

---

## Suggested first test

1. Enter OpenAI API key and Kling API settings
2. Paste one SocksLover product URL
3. Fetch images
4. Keep analysis start index at 22 if appropriate
5. Run GPT Vision analysis
6. Select Pair TOP 1
7. Generate Kling prompt
8. Click **Generate in Kling**
9. Review result
10. Save/use as Shopify support media
