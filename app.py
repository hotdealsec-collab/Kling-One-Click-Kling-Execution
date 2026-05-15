import json
import os
from datetime import datetime

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from utils.helpers import (
    download_image,
    encode_image_to_base64,
    extract_product_images,
    get_nested,
    save_video_from_url,
    safe_filename,
)
from utils.kling_client import KlingGenericClient
from utils.vision import analyze_images_and_pairs, generate_kling_prompt

load_dotenv()

st.set_page_config(page_title='SocksLover Kling Prompt Assistant v5.0 Lite', layout='wide')
st.title('SocksLover Kling Prompt Assistant v5.0 Lite – One Click Kling Execution')
st.caption('Image extraction → GPT Vision analysis → Lifestyle First pair recommendation → Scene Card / Prompt generation → Kling API execution')

LOG_FILE = 'logs/kling_take_log.csv'
os.makedirs('logs', exist_ok=True)
os.makedirs('outputs/videos', exist_ok=True)

DEFAULT_KLING_PAYLOAD = json.dumps({
    'model': '{{MODEL}}',
    'mode': 'start_end_frame',
    'prompt': '{{PROMPT}}',
    'negative_prompt': '{{NEGATIVE_PROMPT}}',
    'duration': '{{DURATION}}',
    'aspect_ratio': '{{ASPECT_RATIO}}',
    'input': {
        'start_image_base64': '{{START_IMAGE_BASE64}}',
        'end_image_base64': '{{END_IMAGE_BASE64}}'
    }
}, ensure_ascii=False, indent=2)

# Session defaults
for key, value in {
    'extracted': None,
    'analysis': None,
    'analysis_candidates': None,
    'selected_pair': None,
    'prompt_bundle': None,
    'last_result': None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = value

with st.sidebar:
    st.header('OpenAI Settings')
    openai_api_key = st.text_input('OpenAI API Key', value=os.getenv('OPENAI_API_KEY', ''), type='password')
    openai_model = st.text_input('OpenAI Model', value=os.getenv('OPENAI_MODEL', 'gpt-4.1-mini'))

    st.header('Kling API Settings')
    kling_api_key = st.text_input('Kling API Key', value=os.getenv('KLING_API_KEY', ''), type='password')
    create_url = st.text_input('Create Endpoint URL', value=os.getenv('KLING_CREATE_URL', ''))
    status_url_template = st.text_input('Status Endpoint URL Template', value=os.getenv('KLING_STATUS_URL_TEMPLATE', ''))
    auth_mode = st.selectbox('Auth Mode', ['bearer', 'x-api-key', 'custom'])
    custom_header_name = st.text_input('Custom Header Name (if custom)', value='Authorization')
    extra_headers_json = st.text_area('Extra Headers JSON', value='{}', height=80)

    st.subheader('JSON Response Paths')
    task_id_path = st.text_input('Task ID Path', value=os.getenv('KLING_TASK_ID_PATH', 'data.task_id'))
    status_path = st.text_input('Status Path', value=os.getenv('KLING_STATUS_PATH', 'data.status'))
    result_url_path = st.text_input('Result Video URL Path', value=os.getenv('KLING_RESULT_URL_PATH', 'data.video_url'))

    st.subheader('Polling')
    poll_seconds = st.number_input('Poll interval (seconds)', min_value=3, max_value=60, value=10)
    max_polls = st.number_input('Max polls', min_value=1, max_value=200, value=60)

st.subheader('1) Product URL → Image Extraction')
url_col1, url_col2 = st.columns([4,1])
with url_col1:
    product_url = st.text_input('Shopify Product URL', placeholder='https://sockslover.net/products/...')
with url_col2:
    fetch_clicked = st.button('Fetch Images', type='primary', use_container_width=True)

if fetch_clicked:
    if not product_url:
        st.error('상품 URL을 입력해주세요.')
    else:
        try:
            extracted = extract_product_images(product_url)
            st.session_state['extracted'] = extracted
            st.session_state['analysis'] = None
            st.session_state['selected_pair'] = None
            st.session_state['prompt_bundle'] = None
            st.success(f"이미지 {len(extracted['images'])}장을 추출했습니다.")
        except Exception as e:
            st.error(f'이미지 추출 실패: {e}')

extracted = st.session_state['extracted']
if extracted:
    st.info(f"상품명: {extracted['title'] or '(제목 없음)'} / 전체 추출 이미지 수: {len(extracted['images'])}")
    default_start_idx = 22 if len(extracted['images']) >= 22 else 1
    s1, s2, s3 = st.columns(3)
    with s1:
        analysis_start_index = st.number_input('분석 시작 이미지 번호', min_value=1, max_value=max(1, len(extracted['images'])), value=default_start_idx)
    with s2:
        max_analysis_images = st.number_input('Vision 분석 최대 이미지 수', min_value=2, max_value=20, value=12)
    with s3:
        strategy = st.selectbox('추천 전략', ['Lifestyle First', 'Balanced', 'Product Focus'])

    start_idx_zero = max(0, int(analysis_start_index) - 1)
    analysis_candidates = extracted['images'][start_idx_zero:start_idx_zero + int(max_analysis_images)]
    st.session_state['analysis_candidates'] = analysis_candidates
    if analysis_candidates:
        first_id = analysis_candidates[0]['id']
        last_id = analysis_candidates[-1]['id']
        st.caption(f'Vision 분석 대상: {first_id} ~ {last_id} / 총 {len(analysis_candidates)}장')

    with st.expander('전체 추출 이미지 보기'):
        cols = st.columns(4)
        for idx, img in enumerate(extracted['images']):
            b = img.get('bytes') or download_image(img['url'])
            extracted['images'][idx]['bytes'] = b
            with cols[idx % 4]:
                if b:
                    st.image(b, caption=f"{img['id']}\n{img['source']}", use_container_width=True)
                else:
                    st.write(f"{img['id']} - 이미지 로드 실패")

    if st.button('2) GPT Vision 분석 & Pair 추천', use_container_width=True):
        if not openai_api_key:
            st.error('OpenAI API Key를 입력해주세요.')
        else:
            try:
                with st.spinner('GPT Vision 분석 중...'):
                    for img in analysis_candidates:
                        if not img.get('bytes'):
                            img['bytes'] = download_image(img['url'])
                    analysis = analyze_images_and_pairs(
                        openai_api_key=openai_api_key,
                        model=openai_model,
                        product_title=extracted['title'],
                        product_url=product_url,
                        strategy=strategy,
                        images=analysis_candidates,
                    )
                    st.session_state['analysis'] = analysis
                st.success('Vision 분석이 완료되었습니다.')
            except Exception as e:
                st.error(f'Vision 분석 실패: {e}')

analysis = st.session_state['analysis']
if analysis and extracted:
    st.subheader('3) Vision 분석 결과')
    if analysis.get('overall_notes'):
        st.info(analysis['overall_notes'])

    analysis_map = {item['id']: item for item in analysis.get('images', [])}
    candidates = st.session_state['analysis_candidates'] or []
    cols = st.columns(4)
    for idx, img in enumerate(candidates):
        a = analysis_map.get(img['id'], {})
        with cols[idx % 4]:
            if img.get('bytes'):
                st.image(img['bytes'], caption=img['id'], use_container_width=True)
            st.caption(f"type: {a.get('image_type','-')}")
            st.caption(f"relevance: {a.get('relevance_score','-')} / lifestyle: {a.get('lifestyle_score','-')} / visibility: {a.get('product_visibility_score','-')}")
            st.caption(f"role: {a.get('recommended_role','-')}")
            if a.get('reason'):
                st.write(f"**사유**: {a.get('reason')}")
            if a.get('cautions'):
                st.write(f"**주의**: {a.get('cautions')}")

    st.subheader('4) Pair TOP 3')
    pairs = analysis.get('pairs', [])
    if not pairs:
        st.warning('추천 pair가 없습니다.')
    else:
        pair_labels = []
        for p in pairs:
            pair_labels.append(f"TOP {p.get('rank')} | {p.get('start_image_id')} → {p.get('end_image_id')} | score {p.get('pair_score')}")
        chosen_label = st.radio('추천 pair 선택', pair_labels, horizontal=False)
        chosen_pair = pairs[pair_labels.index(chosen_label)]
        st.session_state['selected_pair'] = chosen_pair

        st.write(f"**선택된 Pair**: {chosen_pair['start_image_id']} → {chosen_pair['end_image_id']}")
        st.write(f"**전략**: {chosen_pair.get('strategy','-')}")
        st.write(f"**추천 사유**: {chosen_pair.get('reason','-')}")
        st.write(f"**주의사항**: {chosen_pair.get('cautions','-')}")

selected_pair = st.session_state['selected_pair']
if selected_pair and extracted:
    st.subheader('5) Scene Card / Prompt 생성')
    g1, g2, g3, g4 = st.columns(4)
    with g1:
        video_type = st.selectbox('Video Type', ['Shopify Product Video', 'SNS Short Video', 'Ad Creative Test', 'Brand Mood Clip'])
    with g2:
        color_lock = st.selectbox('Color Lock', ['Normal', 'Strong', 'Very Strong'])
    with g3:
        motion_strength = st.selectbox('Motion Strength', ['Gentle', 'Balanced', 'Visible'])
    with g4:
        usage_label = st.selectbox('Usage Label', ['Shopify support media', 'SNS', 'Ad test', 'Review only'])

    if st.button('Generate Kling Prompt', use_container_width=True):
        if not openai_api_key:
            st.error('OpenAI API Key를 입력해주세요.')
        else:
            try:
                with st.spinner('프롬프트 생성 중...'):
                    pb = generate_kling_prompt(
                        openai_api_key=openai_api_key,
                        model=openai_model,
                        product_title=extracted['title'],
                        strategy=selected_pair.get('strategy', 'Lifestyle First'),
                        video_type=video_type,
                        start_id=selected_pair['start_image_id'],
                        end_id=selected_pair['end_image_id'],
                        pair_reason=selected_pair.get('reason', ''),
                        color_lock=color_lock,
                        motion_strength=motion_strength,
                    )
                    st.session_state['prompt_bundle'] = {
                        'scene_card': pb.get('scene_card', {}),
                        'main_prompt': pb.get('main_prompt', ''),
                        'negative_prompt': pb.get('negative_prompt', ''),
                        'video_type': video_type,
                        'color_lock': color_lock,
                        'motion_strength': motion_strength,
                        'usage_label': usage_label,
                    }
                st.success('Kling 프롬프트 생성 완료.')
            except Exception as e:
                st.error(f'프롬프트 생성 실패: {e}')

prompt_bundle = st.session_state['prompt_bundle']
if prompt_bundle and extracted and selected_pair:
    st.subheader('6) Scene Card')
    st.json(prompt_bundle['scene_card'])
    p1, p2 = st.columns(2)
    with p1:
        main_prompt = st.text_area('Main Prompt', value=prompt_bundle['main_prompt'], height=260)
    with p2:
        negative_prompt = st.text_area('Negative Prompt', value=prompt_bundle['negative_prompt'], height=260)
    prompt_bundle['main_prompt'] = main_prompt
    prompt_bundle['negative_prompt'] = negative_prompt

    st.subheader('7) One Click Kling Execution')
    k1, k2, k3 = st.columns(3)
    with k1:
        kling_model = st.text_input('Kling Model', value='Kling-V3')
    with k2:
        kling_duration = st.selectbox('Duration', ['5', '10', '15'], index=0)
    with k3:
        aspect_ratio = st.selectbox('Aspect Ratio', ['1:1', '4:5', '9:16', '16:9'], index=0)

    payload_template = st.text_area('Kling Request JSON Template', value=DEFAULT_KLING_PAYLOAD, height=220)
    with st.expander('Payload placeholders'):
        st.code('{{MODEL}}, {{PROMPT}}, {{NEGATIVE_PROMPT}}, {{DURATION}}, {{ASPECT_RATIO}}, {{START_IMAGE_BASE64}}, {{END_IMAGE_BASE64}}')

    candidate_map = {img['id']: img for img in (st.session_state['analysis_candidates'] or [])}
    start_img = candidate_map.get(selected_pair['start_image_id'])
    end_img = candidate_map.get(selected_pair['end_image_id'])

    if start_img and end_img:
        c1, c2 = st.columns(2)
        with c1:
            if start_img.get('bytes'):
                st.image(start_img['bytes'], caption=f"Start: {start_img['id']}", use_container_width=True)
        with c2:
            if end_img.get('bytes'):
                st.image(end_img['bytes'], caption=f"End: {end_img['id']}", use_container_width=True)

        if st.button('Generate in Kling', type='primary', use_container_width=True):
            if not kling_api_key or not create_url or not status_url_template:
                st.error('Kling API Key / Create Endpoint URL / Status Endpoint URL Template를 입력해주세요.')
            else:
                try:
                    client = KlingGenericClient(
                        api_key=kling_api_key,
                        create_url=create_url,
                        status_url_template=status_url_template,
                        auth_mode=auth_mode,
                        custom_header_name=custom_header_name,
                        extra_headers_json=extra_headers_json,
                    )
                    values = {
                        'MODEL': kling_model,
                        'PROMPT': prompt_bundle['main_prompt'],
                        'NEGATIVE_PROMPT': prompt_bundle['negative_prompt'],
                        'DURATION': str(kling_duration),
                        'ASPECT_RATIO': aspect_ratio,
                        'START_IMAGE_BASE64': encode_image_to_base64(start_img['bytes']),
                        'END_IMAGE_BASE64': encode_image_to_base64(end_img['bytes']),
                    }
                    payload = client.build_payload(payload_template, values)
                    with st.status('Submitting to Kling API...', expanded=True) as status_box:
                        submit_json = client.submit(payload)
                        st.json(submit_json)
                        task_id = get_nested(submit_json, task_id_path)
                        if not task_id:
                            raise ValueError(f'task_id path에서 task id를 읽지 못했습니다: {task_id_path}')
                        status_box.write(f'Task submitted: {task_id}')
                        final_status, result_url, final_json = client.poll_until_done(
                            task_id=task_id,
                            status_path=status_path,
                            result_url_path=result_url_path,
                            poll_seconds=int(poll_seconds),
                            max_polls=int(max_polls),
                        )
                        status_box.write(f'Final status: {final_status}')
                        st.json(final_json)
                        if result_url:
                            status_box.update(label='Completed', state='complete')
                        else:
                            status_box.update(label='Completed without result URL', state='complete')

                    downloaded_path = None
                    if result_url:
                        filename_hint = safe_filename(f"{extracted['title']}_{selected_pair['start_image_id']}_{selected_pair['end_image_id']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
                        downloaded_path = save_video_from_url(result_url, 'outputs/videos', filename_hint, client.session)
                        st.success('Kling 영상 생성 완료')
                        st.video(result_url)
                        if downloaded_path:
                            st.info(f'로컬 저장: {downloaded_path}')

                    row = {
                        'created_at': datetime.now().isoformat(timespec='seconds'),
                        'product_title': extracted['title'],
                        'product_url': product_url,
                        'pair_start': selected_pair['start_image_id'],
                        'pair_end': selected_pair['end_image_id'],
                        'strategy': selected_pair.get('strategy', ''),
                        'pair_score': selected_pair.get('pair_score', ''),
                        'usage_label': prompt_bundle.get('usage_label', ''),
                        'video_type': prompt_bundle.get('video_type', ''),
                        'color_lock': prompt_bundle.get('color_lock', ''),
                        'motion_strength': prompt_bundle.get('motion_strength', ''),
                        'kling_model': kling_model,
                        'duration': kling_duration,
                        'aspect_ratio': aspect_ratio,
                        'task_id': task_id,
                        'status': final_status,
                        'result_url': result_url or '',
                        'downloaded_path': downloaded_path or '',
                    }
                    df_new = pd.DataFrame([row])
                    if os.path.exists(LOG_FILE):
                        df_old = pd.read_csv(LOG_FILE)
                        df = pd.concat([df_old, df_new], ignore_index=True)
                    else:
                        df = df_new
                    df.to_csv(LOG_FILE, index=False)
                    st.success('Take Log 저장 완료')
                    st.session_state['last_result'] = row
                except Exception as e:
                    st.error(f'Kling 실행 실패: {e}')

    st.subheader('8) Take Log / 재생성 프롬프트')
    issue_type = st.selectbox('문제 유형', ['없음', '색상 변형', '스트랩 변형', '형태 변형', '움직임 부족', '움직임 과함', '모델/손 왜곡'])
    if issue_type != '없음':
        fix_prompt_map = {
            '색상 변형': 'Regenerate with stronger color consistency. The bag color must remain exactly the same as the reference images. Do not shift the product color, saturation, or brightness.',
            '스트랩 변형': 'Preserve the exact strap shape, strap color, and strap position. Do not add extra straps or remove existing straps.',
            '형태 변형': 'Keep the product silhouette, flap shape, and structure consistent. Avoid any deformation or shape change.',
            '움직임 부족': 'Add smooth but visible motion such as a slow dolly-in and slight parallax. Avoid a static image feel.',
            '움직임 과함': 'Reduce movement intensity. Keep motion subtle, stable, and elegant with minimal body drift.',
            '모델/손 왜곡': 'Keep the model pose and hands natural and realistic. Avoid distorted fingers, arms, and body shape.',
        }
        st.text_area('재생성용 수정 프롬프트', value=fix_prompt_map.get(issue_type, ''), height=120)

st.divider()
st.subheader('Take Log Table')
if os.path.exists(LOG_FILE):
    df = pd.read_csv(LOG_FILE)
    st.dataframe(df.sort_values('created_at', ascending=False), use_container_width=True)
else:
    st.caption('아직 take log가 없습니다.')
