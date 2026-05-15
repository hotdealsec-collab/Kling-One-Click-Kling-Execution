# SocksLover Kling Prompt Assistant v5.0 Lite – Single File

This is a single-file version of the integrated MVP.

It avoids `ModuleNotFoundError: utils...` issues on Streamlit Cloud when the `utils/` folder is not uploaded correctly.

## Features

- Shopify product image extraction
- Manual analysis start index
- GPT Vision image analysis
- Lifestyle First pair recommendation
- Scene Card / Kling prompt generation
- One Click Kling API execution
- Status polling
- Take Log
- Regeneration prompt helper

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

## GitHub upload

Upload these files/folders after unzipping:

- `app.py`
- `requirements.txt`
- `.env.example`
- `.gitignore`
- `README.md`
- `logs/`
- `outputs/`

No `utils/` folder is required in this version.
