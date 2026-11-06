import csv
import io
import html
import logging
import time

import gspread
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


def preview_table(headers, records):
    """Small HTML preview avoids native Arrow serialization of uploaded data."""
    headers = list(headers)[:15]
    def cell(value):
        return html.escape(str(value)[:240])
    head = ''.join(f'<th>{cell(h)}</th>' for h in headers)
    body = ''.join('<tr>' + ''.join(f'<td>{cell(row[i]) if i < len(row) else ""}</td>' for i in range(len(headers))) + '</tr>' for row in list(records)[:10])
    st.markdown('<div style="overflow:auto;max-height:360px"><table><thead><tr>' + head + '</tr></thead><tbody>' + body + '</tbody></table></div>', unsafe_allow_html=True)
    st.caption('Preview: first 10 rows and 15 columns. Full data is retained for scanning and export.')

def record_csv(records, fields):
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(records)
    return output.getvalue().encode('utf-8-sig')

def read_upload(upload):
    if upload.size > 50 * 1024 * 1024:
        raise ValueError('This hosted app accepts CSV files up to 50 MB. Split the inventory into smaller files.')
    upload.seek(0)
    text = io.TextIOWrapper(upload, encoding='utf-8-sig', newline='')
    parsed, cells = [], 0
    try:
        for row in csv.reader(text):
            cells += len(row)
            if cells > 2_000_000:
                raise ValueError('This file exceeds 2 million cells. Split the inventory into smaller files.')
            parsed.append(row)
    finally:
        text.detach()
    if not parsed or not any(parsed[0]):
        raise ValueError('CSV is empty or its first row has no column headers.')
    return parsed

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
                identity = ('csv', upload.file_id)
                if st.session_state.get('identity') != identity:
                    with st.spinner('Reading inventory…'):
                        rows = read_upload(upload)
                    st.session_state.update(rows=rows, identity=identity, result=None, worksheet=None)
            except Exception as exc:
                logging.exception('Inventory CSV load failed')
                st.error(f'Could not load CSV: {exc}')
                st.stop()
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

st.caption(f'Loaded {len(rows):,} rows · upload-safe build 3')
width = max(map(len, rows))
labels = [f'{col_name(i+1)} · {rows[0][i] if i < len(rows[0]) and rows[0][i] else "Unnamed"}' for i in range(width)]
st.markdown('### Scan settings')
a,b,c,d = st.columns([2,3,1,1])
stock_col = a.selectbox('Stock number column', range(width), format_func=lambda i:labels[i])
image_cols = b.multiselect('Image columns', range(width), default=list(range(1,min(width,9))), format_func=lambda i:labels[i])
start_row = c.number_input('Start row', 1, len(rows), min(2,len(rows)))
threshold = d.number_input('pHash distance', 0, 16, 2, help='0 = identical hashes. Higher values find broader visual similarities. Review jewelry variations carefully.')
workers = st.select_slider('Parallel workers', [2,4,8,16], value=4)
config = (stock_col, tuple(image_cols), start_row, threshold)
with st.expander('Preview source data'):
    preview_table(labels, rows[1:11])
if st.button('Scan for duplicates →', type='primary', disabled=len(image_cols)<2):
    if stock_col in image_cols:
        st.error('The stock number column cannot also be an image column.')
    else:
        bar = st.progress(0, text='Preparing image scan…')
        last_progress = [0.0]
        def update_progress(done, total):
            now = time.monotonic()
            if done == total or now-last_progress[0] >= .3:
                bar.progress(done/total, text=f'Scanning row {done:,} of {total:,}')
                last_progress[0] = now
        try:
            matches, errors = scan(rows, start_row-1, stock_col, sorted(image_cols), threshold, workers,
                                   update_progress)
            st.session_state.result = dict(matches=matches, errors=errors, config=config, baseline=rows)
            st.session_state['excluded_matches'] = set()
            st.session_state['review_version'] = st.session_state.get('review_version', 0) + 1
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
        excluded = st.session_state.setdefault('excluded_matches', set())
        version = st.session_state.get('review_version', 0)
        page = st.number_input('Review page', 1, max(1, (len(matches)+19)//20), 1)
        for i in range((page-1)*20, min(page*20, len(matches))):
            m = matches[i]
            clear = st.checkbox(f"Row {m['row']+1} · {m['stock']} · Clear {col_name(m['col']+1)}, keep {col_name(m['original_col']+1)} · distance {m['distance']}", value=i not in excluded, key=f'clear_{version}_{i}')
            if clear:
                excluded.discard(i)
            else:
                excluded.add(i)
        selected = [m for i,m in enumerate(matches) if i not in excluded]
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
        error_records = [{**e, 'row':e['row']+1} for e in errors]
        preview_table(['Row','Stock','Column','URL','Error'], [[e['row'],e['stock'],e['column'],e['url'],e['error']] for e in error_records[:10]])
        st.download_button('Download error report', record_csv(error_records, ['row','stock','column','url','error']), 'image_errors.csv')
    else:
        st.success('No image download or decoding errors.')

changes = {}
for m in selected:
    changes.setdefault(m['row'], set()).add(m['col'])
cleaned = ([('' if col in changes.get(index, set()) else value) for col,value in enumerate(row)] for index,row in enumerate(result['baseline']))
st.divider()
st.markdown('### Export & apply')
a,b=st.columns(2)
a.download_button(f'Download cleaned CSV · {len(selected):,} URLs cleared', csv_bytes(cleaned), 'inventory_cleaned.csv', mime='text/csv', width="stretch")
selected_cells = {(m['row'], m['col']) for m in selected}
report = [{**m,'row':m['row']+1,'selected':(m['row'],m['col']) in selected_cells} for m in matches]
b.download_button('Download duplicate audit', record_csv(report, ['row','stock','col','original_col','url','original_url','distance','selected']), 'duplicate_audit.csv', width="stretch")
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
