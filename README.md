# SocksLover Kling Prompt Assistant v5.1 – Kling JWT

This is a **single-file Streamlit app** for:

- Shopify product image extraction
- GPT Vision image analysis
- Lifestyle First pair recommendation
- Scene Card / Kling prompt generation
- One Click Kling execution
- Take Log

## v5.1 update

Kling API authentication now supports:

```text
Kling Access Key
Kling Secret Key
```

The app automatically generates a JWT token and sends:

```text
Authorization: Bearer <generated_jwt>
```

`PyJWT` is included in `requirements.txt`.

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

## GitHub / Streamlit Cloud upload

Upload the contents of this folder:

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

## Security

Do not commit Access Key or Secret Key to GitHub.
Enter them in the Streamlit UI sidebar, or use Streamlit Secrets / environment variables.

## Environment variables

Optional:

```text
OPENAI_API_KEY
OPENAI_MODEL
KLING_ACCESS_KEY
KLING_SECRET_KEY
KLING_CREATE_URL
KLING_STATUS_URL_TEMPLATE
KLING_TASK_ID_PATH
KLING_STATUS_PATH
KLING_RESULT_URL_PATH
```
