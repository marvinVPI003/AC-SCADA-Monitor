import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go
from io import BytesIO

# ============================================================================
# CONFIGURATION
# ============================================================================

EQUIPMENT_MAP = {
    'GS': 'Global Start', 'B9B_ML': 'Bin 9B (Mill Line)', 'B4B_ML': 'Bin 4B (Mill Line)',
    'B6A_ML': 'Bin 6A (Mill Line)', 'BA1_ML': 'Batching/Weighing', 'HM14_ML': 'Hammermill 14',
    'MIX07_ML': 'Mixer 07', 'MH11_ML': 'Mixing Hopper 11', 'HP1': 'Hopper 1',
    'PEL11_PL': 'Pelletmill 11', 'COOLER14_PL': 'Cooler 14', 'SIF21': 'Sifter 21',
    'TRF_PL': 'Transfer (Pellet Line)', 'P2A_PL': 'Position 2A (Pellet Line)',
    'P3A_PL': 'Position 3A (Pellet Line)', 'P5B_PL': 'Position 5B (Pellet Line)',
    'P6B_PL': 'Position 6B (Pellet Line)',
}

EQUIPMENT_DESC = {
    'MS-01.1-D2': {'name': 'Mixer 01, Dosing Line 2', 'type': 'Mixer/Dosing', 'critical': True,
        'desc': 'Controls the dosing (ingredient dispensing) into Mixer 01 on Line 2. Repeated alarms may indicate dosing calibration issues, sensor faults, or ingredient supply problems.'},
    'MS-01.1-D1': {'name': 'Mixer 01, Dosing Line 1', 'type': 'Mixer/Dosing', 'critical': True,
        'desc': 'Controls dosing into Mixer 01 on Line 1. Issues here directly affect batch accuracy and formula compliance.'},
    'MS-1.1-PL': {'name': 'Mixer 1.1, Pellet Line', 'type': 'Mixer/Dosing', 'critical': True,
        'desc': 'Mixer on the pellet production line. Alarms may indicate mixing faults or material flow issues before pelleting.'},
    'HL-02.1-D1': {'name': 'Hopper Level Sensor, Dosing 1', 'type': 'Hopper Level', 'critical': True,
        'desc': 'Monitors material level in the hopper feeding Dosing Line 1. Frequent alarms suggest the hopper runs empty often (supply issue from warehouse) or the level sensor is faulty/miscalibrated.'},
    'HL-02.1-HB': {'name': 'Hopper Level 02.1 (Hammermill/Bin)', 'type': 'Hopper Level', 'critical': False,
        'desc': 'Hopper level sensor near the hammermill/bin area. Monitors material availability before grinding.'},
    'HL-3A.1-PL': {'name': 'Hopper Level 3A, Pellet Line', 'type': 'Hopper Level', 'critical': True,
        'desc': 'Monitors material level in hopper feeding the pellet line. If this runs empty, the pelletmill stops causing downtime.'},
    'VM-06-HB': {'name': 'Valve/Motor 06 (Hammermill/Bin)', 'type': 'Valve/Motor', 'critical': False,
        'desc': 'Controls a valve or motor in the hammermill/bin area. Alarms may indicate mechanical jam, electrical fault, or overload.'},
}

FLOW_ORDER = {'GS':1,'B9B_ML':2,'B4B_ML':2,'B6A_ML':2,'BA1_ML':3,'HM14_ML':4,'MIX07_ML':5,
    'MH11_ML':6,'HP1':7,'PEL11_PL':8,'COOLER14_PL':9,'SIF21':10,'TRF_PL':11,'P2A_PL':12,'P3A_PL':12,'P5B_PL':12,'P6B_PL':12}

BATCH_STATE_MAP = {0:'Empty',1:'No Destination',2:'Idle',3:'Conflict',4:'Circuit Error',
    5:'Transferring',6:'Confirm Transfer',7:'Filling',8:'Mixing',9:'Waiting',10:'Waiting'}

INTAKE_STATE_MAP = {0:'Started',2:'In Progress',4:'Completed'}

# ============================================================================
# SMART ANALYSIS
# ============================================================================

def get_concern_level(count):
    if count >= 10: return 'HIGH','#D62828'
    elif count >= 5: return 'MEDIUM','#F77F00'
    else: return 'LOW','#2D6A4F'

def analyze_alarms(al_df):
    if al_df.empty or 'name' not in al_df.columns: return []
    analysis = []
    for equip_name, count in al_df['name'].value_counts().items():
        level, color = get_concern_level(count)
        info = EQUIPMENT_DESC.get(equip_name, {'name':equip_name,'type':'Unknown','critical':False,'desc':'Equipment not yet mapped. Check SCADA tag configuration.'})
        
        if level == 'HIGH':
            if 'Hopper' in info.get('type',''):
                rec = 'Inspect the hopper level sensor for calibration. Check if RM supply from warehouse is consistent. Verify sensor wiring and connections.'
            elif 'Mixer' in info.get('type',''):
                rec = 'Check dosing calibration and ingredient flow. Inspect mixer motor amps for overload. Verify sensors on the dosing scale.'
            else:
                rec = 'Investigate root cause immediately. Check maintenance logs for recurring issues. Schedule inspection.'
        elif level == 'MEDIUM':
            rec = 'Monitor closely over the next shift. If alarms increase, schedule preventive maintenance. Check sensor calibration.'
        else:
            rec = 'Normal operating condition. Continue monitoring.'
        
        pattern = ''
        if 'dateApp' in al_df.columns:
            ea = al_df[al_df['name']==equip_name]
            ts = (ea['dateApp'].max()-ea['dateApp'].min())
            if pd.notna(ts) and ts.total_seconds()>0 and count>2:
                avg = (ts.total_seconds()/(count-1))/60
                if avg < 5: pattern = f'Alarms every {avg:.0f} min — RAPID repeat. Likely sensor issue or persistent fault.'
                elif avg < 30: pattern = f'Alarms every ~{avg:.0f} min — intermittent issue during production.'
                else: pattern = f'Alarms spread out (~{avg:.0f} min apart) — may be triggered by specific conditions.'
        
        analysis.append({'equipment':equip_name,'name':info['name'],'type':info.get('type','Unknown'),
            'desc':info['desc'],'count':count,'level':level,'color':color,
            'critical':info.get('critical',False),'rec':rec,'pattern':pattern})
    return sorted(analysis, key=lambda x: x['count'], reverse=True)

def analyze_batch_flow(fb_df):
    if fb_df.empty: return []
    insights = []
    if 'IdBatch' in fb_df.columns:
        for bid in fb_df[fb_df['IdBatch']>0]['IdBatch'].unique():
            bd = fb_df[fb_df['IdBatch']==bid]
            if 'State' in bd.columns:
                errors = bd[bd['State']==4]
                if len(errors)>0:
                    insights.append({'severity':'HIGH','batch':bid,
                        'msg':f'Batch {bid} has CIRCUIT ERROR on: {", ".join(errors["Equipment"].tolist())}',
                        'detail':'Circuit error means the equipment path is blocked or faulted. Check PLC for fault codes.'})
            if 'Duration_min' in bd.columns:
                for _, step in bd[bd['Duration_min']>60].iterrows():
                    insights.append({'severity':'MEDIUM','batch':bid,
                        'msg':f'Batch {bid}: {step["Equipment"]} took {step["Duration_min"]:.0f} minutes',
                        'detail':'Processing time exceeds 60 minutes. Could indicate slowdown, waiting for materials, or equipment issue.'})
    return insights

def analyze_intake(intake_df):
    if intake_df.empty: return []
    insights = []
    if 'StateDesc' in intake_df.columns:
        total = len(intake_df)
        completed = len(intake_df[intake_df['StateDesc']=='Completed'])
        in_prog = len(intake_df[intake_df['StateDesc']=='In Progress'])
        if in_prog > completed and total > 5:
            insights.append({'severity':'MEDIUM','msg':f'More intakes "In Progress" ({in_prog}) than "Completed" ({completed})',
                'detail':'RM receiving may be slow or intake events not being closed properly in SCADA.'})
    if 'DateOperate' in intake_df.columns and len(intake_df)>2:
        tr = intake_df['DateOperate'].max()-intake_df['DateOperate'].min()
        if pd.notna(tr):
            hrs = tr.total_seconds()/3600
            rate = len(intake_df)/hrs if hrs>0 else 0
            insights.append({'severity':'INFO','msg':f'RM intake rate: {rate:.1f} events/hour over {hrs:.1f} hours',
                'detail':'Average rate of raw material intake activity during this period.'})
    return insights

# ============================================================================
# CSV READING & PROCESSING
# ============================================================================

def read_csv_smart(uploaded_file):
    raw = uploaded_file.read(); uploaded_file.seek(0)
    for enc in ['utf-8-sig','utf-8','cp1252','latin-1','utf-16']:
        try:
            text = raw.decode(enc)
            if 'IdRow' in text or 'TABLE_NAME' in text:
                df = pd.read_csv(uploaded_file, encoding=enc); uploaded_file.seek(0); return df
        except: uploaded_file.seek(0); continue
    return pd.read_csv(uploaded_file, encoding='latin-1')

def process_flowbatch(df):
    if df.empty: return df
    df['Equipment'] = df['FBName'].map(EQUIPMENT_MAP).fillna(df['FBName'])
    df['FlowOrder'] = df['FBName'].map(FLOW_ORDER).fillna(99)
    for col in ['DateStart','DateFinish']:
        if col in df.columns: df[col] = pd.to_datetime(df[col], errors='coerce')
    if 'DateStart' in df.columns and 'DateFinish' in df.columns:
        df['Duration_min'] = (df['DateFinish']-df['DateStart']).dt.total_seconds().abs()/60
        df['Duration_min'] = df['Duration_min'].round(1)
    if 'State' in df.columns: df['StateDesc'] = df['State'].map(BATCH_STATE_MAP).fillna('Unknown')
    if 'BatchState' in df.columns: df['BatchStateDesc'] = df['BatchState'].map(BATCH_STATE_MAP).fillna('Unknown')
    return df

def process_alarms(df):
    if df.empty: return df
    for col in ['dateApp','DateDis']:
        if col in df.columns: df[col] = pd.to_datetime(df[col], errors='coerce')
    if 'dateApp' in df.columns and 'DateDis' in df.columns:
        df['AlarmDuration_sec'] = (df['DateDis']-df['dateApp']).dt.total_seconds().abs()
        df['AlarmDuration_min'] = (df['AlarmDuration_sec']/60).round(1)
    if 'name' in df.columns:
        df['EquipType'] = df['name'].apply(lambda x: x.split('-')[0] if isinstance(x,str) else 'Unknown')
        df['EquipTypeDesc'] = df['EquipType'].map({'MS':'Mixer/Dosing','HL':'Hopper Level','VM':'Valve/Motor','PL':'Pellet Line'}).fillna(df['EquipType'])
    return df

def process_intake(df):
    if df.empty: return df
    if 'DateOperate' in df.columns: df['DateOperate'] = pd.to_datetime(df['DateOperate'], errors='coerce')
    if 'State' in df.columns: df['StateDesc'] = df['State'].map(INTAKE_STATE_MAP).fillna('Unknown')
    return df

# ============================================================================
# PAGE SETUP
# ============================================================================

st.set_page_config(page_title="AC Plant SCADA Monitor", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&display=swap');
    .stApp { font-family: 'DM Sans', sans-serif; }
    div[data-testid="stMetricValue"] { font-size: 28px; font-weight: 700; color: #1B4332; }
    div[data-testid="stMetricLabel"] { font-size: 13px; font-weight: 500; color: #6C757D; }
    h1 { color: #1B4332; } h2 { color: #2D6A4F; } h3 { color: #40916C; }
    .alert-high { background:#FFEAEA; border-left:5px solid #D62828; padding:15px 20px; border-radius:4px; margin-bottom:12px; }
    .alert-medium { background:#FFF4E5; border-left:5px solid #F77F00; padding:15px 20px; border-radius:4px; margin-bottom:12px; }
    .alert-low { background:#E8F5E9; border-left:5px solid #2D6A4F; padding:15px 20px; border-radius:4px; margin-bottom:12px; }
    .alert-info { background:#E3F2FD; border-left:5px solid #1565C0; padding:15px 20px; border-radius:4px; margin-bottom:12px; }
</style>
""", unsafe_allow_html=True)

for key in ['flowbatch_df','alarm_df','intake_df']:
    if key not in st.session_state: st.session_state[key] = pd.DataFrame()
if 'data_loaded' not in st.session_state: st.session_state.data_loaded = False
if 'last_update' not in st.session_state: st.session_state.last_update = None

# ============================================================================
# SIDEBAR
# ============================================================================

with st.sidebar:
    st.markdown("## AC Plant Monitor")
    st.caption("Vienovo Philippines, Inc.")
    st.markdown("---")
    page = st.radio("Navigation", ["Dashboard","Alarm Analysis","Batch Tracking","RM Intake","Upload New Data","Data Explorer"])
    st.markdown("---")
    if st.session_state.data_loaded:
        st.success("Data loaded")
        if st.session_state.last_update: st.caption(f"Updated: {st.session_state.last_update}")
        st.caption(f"FlowBatch: {len(st.session_state.flowbatch_df)} rows")
        st.caption(f"Alarms: {len(st.session_state.alarm_df)} rows")
        st.caption(f"RM Intake: {len(st.session_state.intake_df)} rows")
    else:
        st.warning("No data loaded")
        st.caption("Go to 'Upload New Data'")
    st.markdown("---")
    st.caption("Read-only | CSV-based | No SCADA connection")

# ============================================================================
# UPLOAD PAGE
# ============================================================================

if page == "Upload New Data":
    st.title("Upload SCADA CSV Exports")
    st.markdown("Upload CSV files exported from SCADA. The dashboard updates automatically after upload.")
    st.markdown("---")
    col1,col2,col3 = st.columns(3)
    with col1:
        st.subheader("FlowBatch.csv")
        st.caption("Batch production flow — tracks each batch through every equipment step")
        fb_file = st.file_uploader("Upload FlowBatch", type=['csv'], key='fb')
        if fb_file:
            st.session_state.flowbatch_df = process_flowbatch(read_csv_smart(fb_file))
            st.success(f"Loaded {len(st.session_state.flowbatch_df)} rows")
    with col2:
        st.subheader("AlarmHistory.csv")
        st.caption("Equipment alarms & faults — shows which equipment triggers warnings")
        al_file = st.file_uploader("Upload AlarmHistory", type=['csv'], key='al')
        if al_file:
            st.session_state.alarm_df = process_alarms(read_csv_smart(al_file))
            st.success(f"Loaded {len(st.session_state.alarm_df)} rows")
    with col3:
        st.subheader("RPIntakeEvents.csv")
        st.caption("Raw material intake — tracks when RM is received and processed")
        in_file = st.file_uploader("Upload RPIntakeEvents", type=['csv'], key='in')
        if in_file:
            st.session_state.intake_df = process_intake(read_csv_smart(in_file))
            st.success(f"Loaded {len(st.session_state.intake_df)} rows")
    if not st.session_state.flowbatch_df.empty or not st.session_state.alarm_df.empty or not st.session_state.intake_df.empty:
        st.session_state.data_loaded = True
        st.session_state.last_update = datetime.now().strftime('%Y-%m-%d %H:%M')

# ============================================================================
# DASHBOARD
# ============================================================================

elif page == "Dashboard":
    st.title("AC Plant SCADA Dashboard")
    if not st.session_state.data_loaded:
        st.info("No data loaded. Go to **Upload New Data** to load CSV files.")
        st.stop()

    fb = st.session_state.flowbatch_df
    al = st.session_state.alarm_df
    intake = st.session_state.intake_df
    alarm_analysis = analyze_alarms(al)
    batch_insights = analyze_batch_flow(fb)

    # ---- ALERTS ----
    st.subheader("Alerts & Issues Detected")
    st.caption("Automated analysis of your SCADA data. RED = needs immediate attention. ORANGE = monitor closely. GREEN = all clear.")
    has_alerts = False

    for item in alarm_analysis:
        if item['level'] in ['HIGH','MEDIUM']:
            has_alerts = True
            cls = 'alert-high' if item['level']=='HIGH' else 'alert-medium'
            crit = ' — CRITICAL EQUIPMENT' if item['critical'] else ''
            st.markdown(f"""<div class="{cls}">
                <table style="width:100%;border-collapse:collapse;"><tr>
                <td style="width:18%;vertical-align:top;padding-right:15px;">
                    <strong style="font-size:16px;">{item['equipment']}</strong><br>
                    <span style="font-size:28px;font-weight:bold;">{item['count']}</span> alarms<br>
                    <span style="font-weight:bold;color:{item['color']};">{item['level']} CONCERN{crit}</span>
                </td>
                <td style="width:40%;vertical-align:top;padding-right:15px;">
                    <strong>What it is:</strong> {item['name']}<br>
                    <strong>Type:</strong> {item['type']}<br><br>
                    {item['desc']}
                </td>
                <td style="width:42%;vertical-align:top;">
                    <strong>What to do:</strong><br>{item['rec']}
                    {f"<br><br><strong>Pattern:</strong> {item['pattern']}" if item['pattern'] else ""}
                </td></tr></table></div>""", unsafe_allow_html=True)

    for ins in batch_insights:
        has_alerts = True
        cls = 'alert-high' if ins['severity']=='HIGH' else 'alert-medium'
        st.markdown(f"""<div class="{cls}"><strong>{ins['msg']}</strong><br><em>{ins['detail']}</em></div>""", unsafe_allow_html=True)

    if not has_alerts:
        st.markdown("""<div class="alert-low"><strong>ALL CLEAR</strong> — No high-concern issues detected.</div>""", unsafe_allow_html=True)

    st.markdown("---")

    # ---- KPIs ----
    col1,col2,col3,col4,col5 = st.columns(5)
    ub = fb[fb['IdBatch']>0]['IdBatch'].nunique() if not fb.empty and 'IdBatch' in fb.columns else 0
    ac = len(fb[fb['State']==2]) if not fb.empty and 'State' in fb.columns else 0
    ta = len(al) if not al.empty else 0
    hc = len([a for a in alarm_analysis if a['level']=='HIGH'])
    ic = len(intake) if not intake.empty else 0
    col1.metric("Batches Tracked",ub)
    col2.metric("Active Steps",ac)
    col3.metric("Total Alarms",ta)
    col4.metric("High Concern Equip.",hc)
    col5.metric("RM Intake Events",ic)

    st.markdown("---")

    # ---- CHARTS ----
    col1,col2 = st.columns(2)
    with col1:
        st.subheader("Batch Flow — Equipment Status")
        st.caption("Current state of each equipment. 'Transferring' = actively moving material. 'Filling/Mixing' = processing. 'Empty/Idle' = waiting.")
        if not fb.empty and 'Equipment' in fb.columns:
            sd = fb[fb['IdBatch']>0].groupby(['Equipment','StateDesc']).size().reset_index(name='Count')
            if not sd.empty:
                fig = px.bar(sd,x='Equipment',y='Count',color='StateDesc',
                    color_discrete_sequence=['#1B4332','#40916C','#95D5B2','#F77F00','#D62828'],barmode='stack')
                fig.update_layout(margin=dict(t=10,b=10,l=10,r=10),legend=dict(orientation='h',y=-0.3),xaxis_tickangle=-45,height=380)
                st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("Alarm Count by Equipment")
        st.caption("Which equipment triggers the most alarms. Longer bar = more alarms = needs attention. Color shifts from green (OK) to red (concern).")
        if not al.empty and 'name' in al.columns:
            ac2 = al['name'].value_counts().head(10).reset_index(); ac2.columns = ['Equipment','Count']
            fig = px.bar(ac2,x='Count',y='Equipment',orientation='h',color='Count',
                color_continuous_scale=['#95D5B2','#F77F00','#D62828'])
            fig.update_layout(margin=dict(t=10,b=10,l=10,r=10),yaxis={'categoryorder':'total ascending'},showlegend=False,height=380)
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    col1,col2 = st.columns(2)
    with col1:
        st.subheader("Processing Time per Equipment")
        st.caption("Average time (minutes) each equipment takes per batch step. Unusually long = possible slowdown or waiting for material.")
        if not fb.empty and 'Duration_min' in fb.columns:
            dd = fb[(fb['Duration_min']>0)&(fb['Duration_min']<1440)].groupby('Equipment')['Duration_min'].mean().sort_values(ascending=True).reset_index()
            if not dd.empty:
                fig = px.bar(dd,x='Duration_min',y='Equipment',orientation='h',color_discrete_sequence=['#2D6A4F'])
                fig.update_layout(margin=dict(t=10,b=10,l=10,r=10),xaxis_title='Minutes',height=380)
                st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("Alarm Timeline")
        st.caption("When alarms happen over time. Spikes = burst of alarms. Helps identify if problems happen during specific shifts or times of day.")
        if not al.empty and 'dateApp' in al.columns:
            at2 = al.copy(); at2['Hour'] = at2['dateApp'].dt.floor('h')
            hr = at2.groupby('Hour').size().reset_index(name='Alarms')
            if not hr.empty:
                fig = px.area(hr,x='Hour',y='Alarms',color_discrete_sequence=['#D62828'])
                fig.update_layout(margin=dict(t=10,b=10,l=10,r=10),height=380)
                st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    # ---- EQUIPMENT SUMMARY TABLE ----
    st.subheader("Complete Equipment Alarm Summary")
    st.caption("Every equipment that triggered alarms — with concern level, what it is, what's likely happening, and what to do about it.")
    for item in alarm_analysis:
        cls = 'alert-high' if item['level']=='HIGH' else ('alert-medium' if item['level']=='MEDIUM' else 'alert-low')
        crit = ' (CRITICAL)' if item['critical'] else ''
        st.markdown(f"""<div class="{cls}">
            <table style="width:100%;border-collapse:collapse;"><tr>
            <td style="width:18%;vertical-align:top;padding-right:15px;">
                <strong>{item['equipment']}</strong><br>
                <span style="font-size:24px;font-weight:bold;">{item['count']}</span> alarms<br>
                <strong style="color:{item['color']};">{item['level']}{crit}</strong>
            </td>
            <td style="width:40%;vertical-align:top;padding-right:15px;">
                <strong>What it is:</strong> {item['name']}<br>
                <strong>Type:</strong> {item['type']}<br><br>{item['desc']}
            </td>
            <td style="width:42%;vertical-align:top;">
                <strong>What to do:</strong><br>{item['rec']}
                {f"<br><br><strong>Pattern:</strong> {item['pattern']}" if item['pattern'] else ""}
            </td></tr></table></div>""", unsafe_allow_html=True)

# ============================================================================
# ALARM ANALYSIS PAGE
# ============================================================================

elif page == "Alarm Analysis":
    st.title("Equipment Alarm Analysis")
    if st.session_state.alarm_df.empty:
        st.info("No AlarmHistory data. Go to **Upload New Data**.")
        st.stop()
    al = st.session_state.alarm_df
    aa = analyze_alarms(al)

    st.subheader("Smart Analysis")
    st.caption("Each equipment below is analyzed: alarm count, concern level, what it is, what's likely wrong, and what to do.")
    st.markdown("---")
    for item in aa:
        cls = 'alert-high' if item['level']=='HIGH' else ('alert-medium' if item['level']=='MEDIUM' else 'alert-low')
        st.markdown(f"""<div class="{cls}">
            <table style="width:100%;border-collapse:collapse;"><tr>
            <td style="width:18%;vertical-align:top;">
                <strong style="font-size:16px;">{item['equipment']}</strong><br>
                <span style="font-size:28px;font-weight:bold;">{item['count']}</span> alarms<br>
                <strong style="color:{item['color']};">{item['level']} CONCERN</strong>
            </td>
            <td style="width:40%;vertical-align:top;padding:0 15px;">
                <strong>What it is:</strong> {item['name']}<br><strong>Type:</strong> {item['type']}<br><br>{item['desc']}
            </td>
            <td style="width:42%;vertical-align:top;">
                <strong>What to do:</strong><br>{item['rec']}
                {f"<br><br><strong>Pattern:</strong> {item['pattern']}" if item['pattern'] else ""}
            </td></tr></table></div>""", unsafe_allow_html=True)

    st.markdown("---")
    col1,col2,col3,col4 = st.columns(4)
    col1.metric("Total Alarms",len(al))
    col2.metric("Unique Equipment",al['name'].nunique() if 'name' in al.columns else 0)
    if 'AlarmDuration_min' in al.columns:
        col3.metric("Avg Duration",f"{al['AlarmDuration_min'].mean():.1f} min")
        col4.metric("Max Duration",f"{al['AlarmDuration_min'].max():.1f} min")

    st.markdown("---")
    col1,col2 = st.columns(2)
    with col1:
        st.subheader("Alarms by Equipment")
        st.caption("Bar length = alarm count. Color = severity (green=OK, red=concern).")
        if 'name' in al.columns:
            ea = al['name'].value_counts().reset_index(); ea.columns=['Equipment','Count']
            fig = px.bar(ea,x='Count',y='Equipment',orientation='h',color='Count',color_continuous_scale=['#95D5B2','#F77F00','#D62828'])
            fig.update_layout(margin=dict(t=10,b=10,l=10,r=10),yaxis={'categoryorder':'total ascending'},showlegend=False,height=400)
            st.plotly_chart(fig, use_container_width=True)
    with col2:
        st.subheader("Alarms by Type")
        st.caption("Groups by category: Mixer/Dosing, Hopper Level, Valve/Motor. Shows if the problem is system-wide or isolated.")
        if 'EquipTypeDesc' in al.columns:
            ta2 = al['EquipTypeDesc'].value_counts().reset_index(); ta2.columns=['Type','Count']
            fig = px.pie(ta2,values='Count',names='Type',color_discrete_sequence=['#1B4332','#2D6A4F','#40916C','#95D5B2','#D62828'])
            fig.update_layout(margin=dict(t=10,b=10,l=10,r=10),height=400)
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    st.subheader("Alarm Timeline")
    st.caption("Hourly alarm frequency. Spikes = burst of issues. Look for patterns: shift changes, specific production runs, time of day.")
    if 'dateApp' in al.columns:
        ac3 = al.copy(); ac3['Hour'] = ac3['dateApp'].dt.floor('h')
        hr2 = ac3.groupby('Hour').size().reset_index(name='Count')
        fig = px.area(hr2,x='Hour',y='Count',color_discrete_sequence=['#D62828'])
        fig.update_layout(margin=dict(t=10,b=10,l=10,r=10),height=300)
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    st.subheader("Repeat Alarm Equipment")
    st.caption("Sorted by count. If First and Last alarm are close = burst. If spread apart = ongoing issue that keeps recurring.")
    if 'name' in al.columns:
        rp = al.groupby('name').agg(Alarms=('IdRow','count'),First=('dateApp','min'),Last=('dateApp','max')).sort_values('Alarms',ascending=False).reset_index()
        st.dataframe(rp, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("Full Alarm Log")
    st.caption("Every alarm event. 'dateApp' = when triggered. 'DateDis' = when cleared. Duration = how long the alarm lasted.")
    dc = [c for c in ['name','dateApp','DateDis','AlarmDuration_min','EquipTypeDesc'] if c in al.columns]
    st.dataframe(al[dc], use_container_width=True, hide_index=True)
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w: al.to_excel(w, sheet_name='Alarms', index=False)
    out.seek(0)
    st.download_button("Download Alarm Report Excel",data=out,file_name=f"AC_Alarms_{datetime.now().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ============================================================================
# BATCH TRACKING
# ============================================================================

elif page == "Batch Tracking":
    st.title("Batch Production Tracking")
    st.caption("Track each batch through the production flow: Bins > Hammermill > Mixer > Pelletmill > Cooler > Sifter > Bagging")
    if st.session_state.flowbatch_df.empty:
        st.info("No FlowBatch data. Go to **Upload New Data**.")
        st.stop()
    fb = st.session_state.flowbatch_df
    bi = analyze_batch_flow(fb)
    if bi:
        st.subheader("Batch Alerts")
        for ins in bi:
            cls = 'alert-high' if ins['severity']=='HIGH' else 'alert-medium'
            st.markdown(f"""<div class="{cls}"><strong>{ins['msg']}</strong><br><em>{ins['detail']}</em></div>""", unsafe_allow_html=True)
    st.markdown("---")
    if 'IdBatch' in fb.columns:
        bids = sorted(fb[fb['IdBatch']>0]['IdBatch'].unique(), reverse=True)
        if bids:
            sb = st.selectbox("Select Batch ID",bids,format_func=lambda x: f"Batch {x}")
            bd = fb[fb['IdBatch']==sb].copy()
            if 'IdBatchPre' in fb.columns:
                bd = pd.concat([bd,fb[fb['IdBatchPre']==sb]]).drop_duplicates(subset=['IdRow']).sort_values('FlowOrder')
            if not bd.empty:
                st.markdown("---")
                col1,col2,col3,col4 = st.columns(4)
                col1.metric("Batch ID",sb); col2.metric("Steps",len(bd))
                if 'DateStart' in bd.columns:
                    s = bd['DateStart'].min(); e = bd['DateFinish'].max()
                    if pd.notna(s): col3.metric("Started",s.strftime('%m/%d %I:%M %p'))
                    if pd.notna(e): col4.metric("Latest",e.strftime('%m/%d %I:%M %p'))
                st.markdown("---")
                st.subheader("Production Flow")
                st.caption("Each row = one equipment step. Batch moves through these in order. Duration shows processing time per step.")
                for _,row in bd.iterrows():
                    c1,c2,c3,c4 = st.columns([3,2,2,1])
                    with c1:
                        st.markdown(f"**{row.get('Equipment',row.get('FBName','?'))}**")
                        st.caption(f"SCADA tag: {row.get('FBName','')} | Order: {row.get('OrderFB','')}")
                    with c2:
                        if pd.notna(row.get('DateStart')): st.caption(f"Start: {row['DateStart'].strftime('%m/%d %I:%M %p')}")
                        if pd.notna(row.get('DateFinish')): st.caption(f"End: {row['DateFinish'].strftime('%m/%d %I:%M %p')}")
                    with c3:
                        if 'Duration_min' in row and row['Duration_min']>0:
                            d = row['Duration_min']
                            st.metric("Duration",f"{d:.0f} min" if d>60 else f"{d:.1f} min")
                            if d>60: st.caption("Longer than usual — check for delays")
                    with c4:
                        state = row.get('StateDesc','Unknown')
                        if state=='Transferring': st.success(state)
                        elif state in ['Filling','Mixing']: st.warning(state)
                        elif state=='Circuit Error': st.error(state)
                        else: st.info(state)
                    st.markdown("---")
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w: fb.to_excel(w, sheet_name='FlowBatch', index=False)
    out.seek(0)
    st.download_button("Download FlowBatch Excel",data=out,file_name=f"AC_FlowBatch_{datetime.now().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ============================================================================
# RM INTAKE
# ============================================================================

elif page == "RM Intake":
    st.title("Raw Material Intake Events")
    st.caption("Tracks when raw materials are received. Each event = one intake operation in SCADA.")
    if st.session_state.intake_df.empty:
        st.info("No RPIntakeEvents data. Go to **Upload New Data**.")
        st.stop()
    intake = st.session_state.intake_df
    ii = analyze_intake(intake)
    if ii:
        st.subheader("Intake Insights")
        for ins in ii:
            cls = 'alert-medium' if ins['severity']=='MEDIUM' else 'alert-info'
            st.markdown(f"""<div class="{cls}"><strong>{ins['msg']}</strong><br><em>{ins['detail']}</em></div>""", unsafe_allow_html=True)
    st.markdown("---")
    col1,col2,col3 = st.columns(3)
    col1.metric("Total Events",len(intake))
    if 'StateDesc' in intake.columns:
        col2.metric("Completed",len(intake[intake['StateDesc']=='Completed']))
        col3.metric("In Progress",len(intake[intake['StateDesc']=='In Progress']))
    st.markdown("---")
    col1,col2 = st.columns(2)
    with col1:
        st.subheader("Events by Status")
        st.caption("'Started' = initiated. 'In Progress' = receiving. 'Completed' = done. Most should be Completed.")
        if 'StateDesc' in intake.columns:
            sc = intake['StateDesc'].value_counts().reset_index(); sc.columns=['Status','Count']
            fig = px.pie(sc,values='Count',names='Status',color_discrete_sequence=['#1B4332','#40916C','#95D5B2'])
            fig.update_layout(margin=dict(t=10,b=10,l=10,r=10),height=350)
            st.plotly_chart(fig, use_container_width=True)
    with col2:
        st.subheader("Activity Over Time")
        st.caption("When RM intake happens. Peaks = busy receiving. Gaps = no activity (breaks, night shift).")
        if 'DateOperate' in intake.columns:
            ic2 = intake.copy(); ic2['Hour'] = ic2['DateOperate'].dt.floor('h')
            hr3 = ic2.groupby('Hour').size().reset_index(name='Events')
            fig = px.bar(hr3,x='Hour',y='Events',color_discrete_sequence=['#2D6A4F'])
            fig.update_layout(margin=dict(t=10,b=10,l=10,r=10),height=350)
            st.plotly_chart(fig, use_container_width=True)
    st.markdown("---")
    st.subheader("Full Intake Log")
    st.caption("State codes: 0=Started, 2=In Progress, 4=Completed. IdIntake = delivery ID.")
    st.dataframe(intake, use_container_width=True, hide_index=True)
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w: intake.to_excel(w, sheet_name='RMIntake', index=False)
    out.seek(0)
    st.download_button("Download RM Intake Excel",data=out,file_name=f"AC_RMIntake_{datetime.now().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ============================================================================
# DATA EXPLORER
# ============================================================================

elif page == "Data Explorer":
    st.title("Data Explorer")
    st.caption("View raw SCADA data. Use this to verify data quality and understand column structures.")
    st.markdown("---")
    ds = st.selectbox("Dataset",["FlowBatch","AlarmHistory","RPIntakeEvents"])
    if ds=="FlowBatch" and not st.session_state.flowbatch_df.empty: df=st.session_state.flowbatch_df
    elif ds=="AlarmHistory" and not st.session_state.alarm_df.empty: df=st.session_state.alarm_df
    elif ds=="RPIntakeEvents" and not st.session_state.intake_df.empty: df=st.session_state.intake_df
    else: st.info(f"No {ds} data. Upload first."); st.stop()
    col1,col2,col3 = st.columns(3)
    col1.metric("Rows",len(df)); col2.metric("Columns",len(df.columns)); col3.metric("Dataset",ds)
    st.markdown("---")
    st.subheader("Column Details")
    ci = pd.DataFrame({'Column':df.columns,'Type':df.dtypes.astype(str),'Non-Null':df.notnull().sum(),
        'Sample':[str(df[c].iloc[0])[:50] if len(df)>0 else '' for c in df.columns]})
    st.dataframe(ci, use_container_width=True, hide_index=True)
    st.markdown("---")
    st.dataframe(df, use_container_width=True, hide_index=True)
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w: df.to_excel(w, sheet_name=ds, index=False)
    out.seek(0)
    st.download_button(f"Download {ds} Excel",data=out,file_name=f"AC_{ds}_{datetime.now().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
