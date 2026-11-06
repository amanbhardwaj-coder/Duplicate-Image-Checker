import copy
import csv
import io
import json
import hashlib

import gspread
import pandas as pd
import streamlit as st
from engine import scan, csv_bytes, col_name

st.set_page_config(page_title='Image Studio · Inventory cleanup', page_icon='◈', layout='wide')
st.markdown('''<style>
.block-container{max-width:1320px;padding-top:2rem}h1{letter-spacing:-1.5px;font-weight:750!important}
[data-testid="stMetric"]{background:white;border:1px solid #e4e9ee;border-radius:14px;padding:18px}
[data-testid="stSidebar"]{border-right:1px solid #e4e9ee}.eyebrow{color:#198775;letter-spacing:2px;font-size:12px;font-weight:700}
.hero{padding:28px;background:#172f3d;color:white;border-radius:18px;margin-bottom:24px}.hero h2{color:white;margin:0}.hero p{color:#c1d3dc;margin-bottom:0}
</style>''', unsafe_allow_html=True)
DEFAULT_URL = 'https://docs.google.com/spreadsheets/d/1LfcJLtbO4p9_j4PyrggdPjCz1Crq2vfQ3z7IMI_FNe4/edit?gid=1220686951#gid=1220686951'

def sheet_client():
    if 'gcp_service_account' not in st.secrets:
        raise ValueError('Add gcp_service_account in Streamlit app secrets and share the spreadsheet with its client_email.')
    return gspread.service_account_from_dict(dict(st.secrets['gcp_service_account']))

with st.sidebar:
    st.markdown('## ◈ Image Studio')
    st.caption('INVENTORY TOOLS')
    st.divider()
    st.markdown('### 1 · Choose your source')
    source = st.radio('Data source', ['CSV upload', 'Google Sheets'])
    if source == 'CSV upload':
        upload = st.file_uploader('Inventory CSV', type=['csv'])
        if upload:
            try:
                rows = list(csv.reader(io.StringIO(upload.getvalue().decode('utf-8-sig'))))
                identity = ('csv', hashlib.sha256(upload.getvalue()).hexdigest())
                if st.session_state.get('identity') != identity:
                    st.session_state.update(rows=rows, identity=identity, result=None, worksheet=None)
            except Exception as exc:
                st.error(f'Could not read UTF-8 CSV: {exc}')
    else:
        sheet_url = st.text_input('Spreadsheet URL', DEFAULT_URL)
        worksheet_name = st.text_input('Worksheet', 'Sheet2')
        if st.button('Connect & load', width="stretch"):
            try:
                worksheet = sheet_client().open_by_url(sheet_url).worksheet(worksheet_name)
                rows = worksheet.get_all_values(value_render_option='FORMULA')
                st.session_state.update(rows=rows, identity=('sheet', sheet_url, worksheet_name), result=None, worksheet=worksheet)
                st.success('Worksheet loaded')
            except Exception as exc:
                st.error(str(exc))
    st.divider()
    st.caption('Matches are compared within each stock row. The first matching image is kept. Failed URLs are never removed.')

st.markdown('<div class="eyebrow">VISUAL INVENTORY CARE</div>', unsafe_allow_html=True)
st.title('A cleaner view of your inventory.')
st.markdown('<div class="hero"><h2>Find repeats. Keep the right images.</h2><p>Scan image URLs, review visual matches, and export a cleaner inventory with confidence.</p></div>', unsafe_allow_html=True)
rows = st.session_state.get('rows')
if not rows or st.session_state.get('identity', ('',))[0] != ('csv' if source == 'CSV upload' else 'sheet'):
    st.info('Start by uploading an inventory CSV or connecting a Google Sheet in the sidebar.')
    st.markdown('#### Your workflow')
    a,b,c = st.columns(3)
    a.markdown('**01 · Load inventory**\n\nKeep your existing columns and stock numbers.')
    b.markdown('**02 · Review matches**\n\nCompare duplicate pairs before clearing URLs.')
    c.markdown('**03 · Export or apply**\n\nDownload a cleaned CSV or update selected sheet cells.')
    st.stop()

width = max(map(len, rows))
labels = [f'{col_name(i+1)} · {rows[0][i] if i < len(rows[0]) and rows[0][i] else "Unnamed"}' for i in range(width)]
st.markdown('### Scan settings')
a,b,c,d = st.columns([2,3,1,1])
stock_col = a.selectbox('Stock number column', range(width), format_func=lambda i:labels[i])
image_cols = b.multiselect('Image columns', range(width), default=list(range(1,min(width,9))), format_func=lambda i:labels[i])
start_row = c.number_input('Start row', 1, len(rows), min(2,len(rows)))
threshold = d.number_input('pHash distance', 0, 16, 2, help='0 = identical hashes. Higher values find broader visual similarities. Review jewelry variations carefully.')
workers = st.select_slider('Parallel workers', [4,8,16,32], value=16)
config = (stock_col, tuple(image_cols), start_row, threshold)
with st.expander('Preview source data'):
    st.dataframe(pd.DataFrame([r+['']*(width-len(r)) for r in rows[:11]], columns=labels), width="stretch")
if st.button('Scan for duplicates →', type='primary', disabled=len(image_cols)<2):
    if stock_col in image_cols:
        st.error('The stock number column cannot also be an image column.')
    else:
        bar = st.progress(0, text='Preparing image scan…')
        try:
            matches, errors = scan(rows, start_row-1, stock_col, sorted(image_cols), threshold, workers,
                                   lambda done,total:bar.progress(done/total, text=f'Scanning row {done:,} of {total:,}'))
            st.session_state.result = dict(matches=matches, errors=errors, config=config, baseline=copy.deepcopy(rows))
            st.session_state.pop('review_table', None)
            bar.empty()
        except Exception as exc:
            st.error(f'Scan failed: {exc}')
result = st.session_state.get('result')
if not result:
    st.stop()
if result['config'] != config:
    st.warning('Settings changed. Run a new scan to use these settings.')
    st.stop()
matches, errors = result['matches'], result['errors']
a,b,c,d=st.columns(4)
a.metric('Rows scanned', f'{len(rows)-start_row+1:,}')
b.metric('Duplicate candidates', f'{len(matches):,}')
c.metric('Affected stock rows', f'{len(set(m["row"] for m in matches)):,}')
d.metric('Image errors', f'{len(errors):,}')
st.markdown('### Review your results')
review_tab, error_tab = st.tabs(['Duplicate matches', f'URL errors · {len(errors)}'])
selected=[]
with review_tab:
    if not matches:
        st.success('No duplicate candidates found at this threshold.')
    else:
        st.caption('Select which image URLs to clear. No changes have been made to your source.')
        table = pd.DataFrame([{'Clear':True,'Row':m['row']+1,'Stock number':m['stock'], 'Keep':col_name(m['original_col']+1),'Clear column':col_name(m['col']+1),'Distance':m['distance']} for m in matches])
        edited = st.data_editor(table, hide_index=True, disabled=list(table.columns[1:]), key='review_table', width="stretch")
        selected = [m for m, clear in zip(matches,edited['Clear']) if clear]
        pick = st.selectbox('Inspect a match', range(len(matches)), format_func=lambda i:f'Row {matches[i]["row"]+1} · {matches[i]["stock"]} · {col_name(matches[i]["col"]+1)}')
        match = matches[pick]
        left,right=st.columns(2)
        for container,url,caption in [(left,match['original_url'],'KEEP · First matching image'),(right,match['url'],f'DUPLICATE CANDIDATE · Distance {match["distance"]}')]:
            with container:
                st.caption(caption)
                st.image(url, width=260)
                st.text(url)
with error_tab:
    if errors:
        st.dataframe(pd.DataFrame(errors).assign(row=lambda x:x.row+1), hide_index=True, width="stretch")
        st.download_button('Download error report', pd.DataFrame(errors).assign(row=lambda x:x.row+1).to_csv(index=False).encode(), 'image_errors.csv')
    else:
        st.success('No image download or decoding errors.')

cleaned=copy.deepcopy(result['baseline'])
for m in selected:
    cleaned[m['row']][m['col']]=''
st.divider()
st.markdown('### Export & apply')
a,b=st.columns(2)
a.download_button(f'Download cleaned CSV · {len(selected):,} URLs cleared', csv_bytes(cleaned), 'inventory_cleaned.csv', mime='text/csv', width="stretch")
report = pd.DataFrame([{**m,'row':m['row']+1,'selected':m in selected} for m in matches])
b.download_button('Download duplicate audit', report.to_csv(index=False).encode('utf-8-sig'), 'duplicate_audit.csv', width="stretch")
worksheet=st.session_state.get('worksheet')
if source=='Google Sheets' and worksheet:
    st.caption('Only selected duplicate URL cells are cleared. Other columns and formulas are preserved. Updates use batches of 500 cells.')
    confirm=st.checkbox('I reviewed the selected matches and want to clear these URLs in Google Sheets.')
    if st.button('Apply selected changes to Google Sheets', disabled=not confirm or not selected):
        try:
            current = worksheet.get_all_values(value_render_option='FORMULA')
            # Verify the entire relevant row to catch row movement and changed kept images.
            touched = {m['row'] for m in selected}
            if any(i>=len(current) or current[i] != result['baseline'][i] for i in touched):
                st.error('Source rows changed since the scan. Reload the sheet and scan again before applying.')
            else:
                updates=[{'range':f'{col_name(m["col"]+1)}{m["row"]+1}', 'values':[['']]} for m in selected]
                applied=0
                try:
                    for offset in range(0,len(updates),500):
                        batch=updates[offset:offset+500]
                        worksheet.batch_update(batch, value_input_option='RAW')
                        applied+=len(batch)
                    st.success(f'Cleared {applied:,} duplicate URL cells. Reload the sheet before scanning again.')
                    st.session_state.result=None
                except Exception as exc:
                    st.error(f'Update stopped after {applied} confirmed cells. Reload and rescan before retrying. {exc}')
        except Exception as exc:
            st.error(str(exc))
